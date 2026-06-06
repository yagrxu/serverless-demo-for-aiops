import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as sns_subs from 'aws-cdk-lib/aws-sns-subscriptions';
import * as apigatewayv2 from 'aws-cdk-lib/aws-apigatewayv2';
import * as apigatewayv2_integrations from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as path from 'path';

export interface SlackStackProps extends cdk.StackProps {
  /** Project name prefix, e.g. "aiops-cat-demo". */
  readonly projectName: string;
  /** Existing SNS alarm topic ARN (from the observability stack). */
  readonly alarmTopicArn: string;
  /** Secrets Manager ARN for the webhook secret {url, hmac_secret}. */
  readonly webhookSecretArn: string;
  /** Secrets Manager ARN for the Slack secret {bot_token, signing_secret, agent_space_id, operator_role_arn}. */
  readonly slackSecretArn: string;
  /** DevOps Agent operator role ARN the worker assumes (with AgentSpaceId tag). */
  readonly operatorRoleArn: string;
  /**
   * Random per-deployment id (from SSM, see scripts/ensure-deployment-id.sh).
   * Used as the worker role suffix so the operator role trust policy can be
   * scoped to exactly this deployment and multiple deployments don't collide.
   */
  readonly deploymentId: string;
}

/**
 * Slack integration stack for the AIOps Cat Demo.
 *
 * Path A (automated): SNS alarm → Webhook Lambda → HMAC-signed POST → DevOps
 *   Agent webhook → autonomous investigation → DevOps Agent's native Slack push.
 *
 * Path B (interactive): Slack event → API Gateway → Slack Handler (ack <3s) →
 *   async-invokes the Slack Worker → Worker assumes the DevOps Agent operator
 *   role (AgentSpaceId session tag) → create_chat/send_message → parses the
 *   EventStream → chat.postMessage back to Slack.
 *
 * Secrets are referenced by ARN (never created here). The DevOps Agent space,
 * operator role, and webhook are provisioned out of band.
 */
export class SlackStack extends cdk.Stack {
  /** API Gateway endpoint URL for the Slack Events Request URL. */
  readonly apiEndpoint: string;
  /** The Slack Worker Lambda execution role name (suffixed with deploymentId). */
  readonly workerRoleName: string;

  constructor(scope: Construct, id: string, props: SlackStackProps) {
    super(scope, id, props);

    const region = cdk.Stack.of(this).region;
    const account = cdk.Stack.of(this).account;

    // ---------------------------------------------------------------
    // Path A — Webhook Forwarder Lambda (SNS → DevOps Agent webhook)
    // ---------------------------------------------------------------
    const webhookLambda = new lambda.Function(this, 'WebhookForwarder', {
      functionName: `${props.projectName}-webhook-forwarder`,
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      memorySize: 256,
      timeout: cdk.Duration.seconds(30),
      handler: 'handler.lambda_handler',
      // No extra deps — urllib3 + boto3 are in the runtime. Plain asset.
      code: lambda.Code.fromAsset(path.join(__dirname, '../../lambda/webhook-forwarder')),
      logRetention: logs.RetentionDays.ONE_WEEK,
      environment: {
        SECRET_NAME: 'aiops-cat-demo/devops-agent-webhook',
        SERVICE_NAME: props.projectName,
      },
      description: 'Forwards SNS alarm notifications to the DevOps Agent webhook (HMAC-signed).',
    });
    webhookLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [`${props.webhookSecretArn}*`],
    }));

    // ---------------------------------------------------------------
    // Path B — Slack Worker Lambda (async agent call)
    //
    // Needs boto3 >= 1.43 for the `devops-agent` client, which is newer than
    // the Lambda runtime default — so bundle requirements.txt via Docker.
    // Its execution role has a FIXED name (suffixed with deploymentId) so the
    // operator role trust policy can be scoped to it ahead of deploy.
    // ---------------------------------------------------------------
    this.workerRoleName = `${props.projectName}-slack-worker-${props.deploymentId}`;

    const workerRole = new iam.Role(this, 'SlackWorkerRole', {
      roleName: this.workerRoleName,
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Execution role for the Slack Worker Lambda (assumes the DevOps Agent operator role).',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });
    // Read the Slack secret.
    workerRole.addToPolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [`${props.slackSecretArn}*`],
    }));
    // Assume the DevOps Agent operator role WITH session tagging (AgentSpaceId).
    workerRole.addToPolicy(new iam.PolicyStatement({
      actions: ['sts:AssumeRole', 'sts:TagSession'],
      resources: [props.operatorRoleArn],
    }));

    const slackWorkerLambda = new lambda.Function(this, 'SlackWorker', {
      functionName: `${props.projectName}-slack-worker`,
      role: workerRole,
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      memorySize: 256,
      timeout: cdk.Duration.seconds(60),
      handler: 'handler.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../lambda/slack-worker'), {
        bundling: {
          image: lambda.Runtime.PYTHON_3_12.bundlingImage,
          command: [
            'bash', '-c',
            'pip install --no-cache-dir -r requirements.txt -t /asset-output && cp -au . /asset-output',
          ],
          local: {
            tryBundle(outputDir: string) {
              try {
                const { execSync } = require('child_process');
                execSync(
                  `pip install --no-cache-dir -r requirements.txt -t "${outputDir}" && cp -a . "${outputDir}"`,
                  { cwd: path.join(__dirname, '../../lambda/slack-worker'), stdio: 'pipe' },
                );
                return true;
              } catch {
                return false;
              }
            },
          },
        },
      }),
      logRetention: logs.RetentionDays.ONE_WEEK,
      environment: {
        SLACK_SECRET_NAME: 'aiops-cat-demo/slack-bot',
      },
      description: 'Async DevOps Agent chat worker: assume-role → create_chat/send_message → post to Slack.',
    });

    // ---------------------------------------------------------------
    // Path B — Slack Handler (Ack) Lambda (verify + fast ack + async fan-out)
    // ---------------------------------------------------------------
    const slackHandlerLambda = new lambda.Function(this, 'SlackHandler', {
      functionName: `${props.projectName}-slack-handler`,
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      memorySize: 256,
      timeout: cdk.Duration.seconds(10),
      handler: 'handler.lambda_handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../lambda/slack-handler')),
      logRetention: logs.RetentionDays.ONE_WEEK,
      environment: {
        SLACK_SECRET_NAME: 'aiops-cat-demo/slack-bot',
        WORKER_FUNCTION_NAME: slackWorkerLambda.functionName,
      },
      description: 'Verifies Slack signatures, acks <3s, and async-invokes the Slack Worker.',
    });
    slackHandlerLambda.addToRolePolicy(new iam.PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [`${props.slackSecretArn}*`],
    }));
    // Allow the ack Lambda to fire-and-forget invoke the worker.
    slackWorkerLambda.grantInvoke(slackHandlerLambda);

    // ---------------------------------------------------------------
    // HTTP API Gateway — POST /slack/events → Slack Handler (Ack) Lambda
    // ---------------------------------------------------------------
    const httpApi = new apigatewayv2.HttpApi(this, 'SlackHttpApi', {
      apiName: `${props.projectName}-slack-api`,
      description: 'HTTP API for Slack event delivery (events + slash commands).',
    });
    httpApi.addRoutes({
      path: '/slack/events',
      methods: [apigatewayv2.HttpMethod.POST],
      integration: new apigatewayv2_integrations.HttpLambdaIntegration(
        'SlackHandlerIntegration',
        slackHandlerLambda,
      ),
    });

    // ---------------------------------------------------------------
    // Path A — SNS subscription: existing alarm topic → Webhook Lambda
    // ---------------------------------------------------------------
    const alarmTopic = sns.Topic.fromTopicArn(this, 'AlarmTopic', props.alarmTopicArn);
    alarmTopic.addSubscription(new sns_subs.LambdaSubscription(webhookLambda));

    // ---------------------------------------------------------------
    // Outputs
    // ---------------------------------------------------------------
    this.apiEndpoint = httpApi.apiEndpoint;

    new cdk.CfnOutput(this, 'SlackApiEndpoint', {
      value: `${httpApi.apiEndpoint}/slack/events`,
      description: 'Set this as the Slack App Request URL (Events + Slash Commands).',
    });
    new cdk.CfnOutput(this, 'SlackWorkerRoleName', {
      value: this.workerRoleName,
      description: 'Slack Worker execution role (must be allowed by the operator role trust policy).',
    });
    new cdk.CfnOutput(this, 'SlackWorkerRoleArn', {
      value: `arn:aws:iam::${account}:role/${this.workerRoleName}`,
      description: 'Slack Worker execution role ARN.',
    });
    // region referenced to keep linters happy when not otherwise used
    void region;
  }
}

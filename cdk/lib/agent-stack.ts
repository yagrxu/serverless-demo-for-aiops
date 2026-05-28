import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface AgentStackProps extends cdk.StackProps {
  mcpServerUrl: string;
  imageTag: string;
  repos: {
    langgraph: ecr.IRepository;
    strands: ecr.IRepository;
  };
}

/**
 * AgentCore Runtime hosting two independent agents (LangGraph + Strands).
 *
 * Each agent is its own Runtime — no entrypoint router. Clients call
 * each Runtime directly.
 *
 * Images are NOT built here. CI (GitHub Actions) builds each Dockerfile
 * under agents/<name>/ and pushes to the named ECR repo owned by
 * EcrStack with tag `imageTag` (usually the commit SHA). This stack
 * only references the resulting image URI.
 */
export class AgentStack extends cdk.Stack {
  /** ARN of the LangGraph AgentCore Runtime */
  readonly langgraphRuntimeArn: string;
  /** ARN of the Strands AgentCore Runtime */
  readonly strandsRuntimeArn: string;

  constructor(scope: Construct, id: string, props: AgentStackProps) {
    super(scope, id, props);

    const uri = (repo: ecr.IRepository) => `${repo.repositoryUri}:${props.imageTag}`;

    const agentRole = new iam.Role(this, 'AgentCoreExecRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      description: 'AgentCore Runtime execution role for cat-demo agents',
    });
    agentRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'bedrock:InvokeModel',
        'bedrock:InvokeModelWithResponseStream',
        'bedrock:CountTokens',
        'bedrock-agentcore:InvokeGateway',
        'logs:CreateLogGroup',
        'logs:CreateLogStream',
        'logs:PutLogEvents',
        'logs:DescribeLogGroups',
        'logs:DescribeLogStreams',
        'xray:PutTraceSegments',
        'xray:PutTelemetryRecords',
        'cloudwatch:PutMetricData',
      ],
      resources: ['*'],
    }));
    // AgentCore pulls images from ECR using its execution role.
    // grantPull gives BatchGetImage + GetDownloadUrlForLayer per repo.
    // GetAuthorizationToken is account-level and must be granted separately.
    for (const r of Object.values(props.repos)) r.grantPull(agentRole);
    agentRole.addToPolicy(new iam.PolicyStatement({
      actions: ['ecr:GetAuthorizationToken'],
      resources: ['*'],
    }));

    const mkRuntime = (id: string, name: string, imageUri: string) => {
      const runtime = new cdk.CfnResource(this, id, {
        type: 'AWS::BedrockAgentCore::Runtime',
        properties: {
          AgentRuntimeName: name,
          AgentRuntimeArtifact: {
            ContainerConfiguration: { ContainerUri: imageUri },
          },
          RoleArn: agentRole.roleArn,
          NetworkConfiguration: { NetworkMode: 'PUBLIC' },
          EnvironmentVariables: {
            MCP_SERVER_URL: props.mcpServerUrl,
            MODEL_ID: 'us.anthropic.claude-haiku-4-5-20251001-v1:0',
          },
        },
      });
      // Ensure the role + all policies are fully created before the runtime
      runtime.node.addDependency(agentRole);
      return runtime;
    };

    const lgRuntime = mkRuntime('LangGraphRuntime', 'cat_demo_langgraph', uri(props.repos.langgraph));
    const strandsRuntime = mkRuntime('StrandsRuntime', 'cat_demo_strands', uri(props.repos.strands));

    this.langgraphRuntimeArn = cdk.Token.asString(lgRuntime.getAtt('AgentRuntimeArn'));
    this.strandsRuntimeArn = cdk.Token.asString(strandsRuntime.getAtt('AgentRuntimeArn'));

    // --- Tracing: deliver runtime spans to X-Ray ---
    //
    // AgentCore Runtime, like Gateway, has no `TracingEnabled` property.
    // Tracing is wired through the generic CloudWatch Logs delivery
    // model: a DeliverySource(LogType=TRACES) on the runtime ARN paired
    // with a DeliveryDestination of type XRAY.
    //
    // Without this delivery, AgentCore accepts the inbound traceparent
    // but never publishes its own data-plane segment, so trafgen's
    // httpx CLIENT span and the customer container's SERVER span end
    // up in the same trace_id but as two disconnected branches in the
    // X-Ray Service Map.
    //
    // Prerequisite (one-time, per account/region):
    //   aws xray update-trace-segment-destination --destination CloudWatchLogs
    // (already enabled — see gateway-stack.ts for the same rationale).
    const tracesDestination = new cdk.CfnResource(this, 'RuntimeTracesDestination', {
      type: 'AWS::Logs::DeliveryDestination',
      properties: {
        Name: 'cat-demo-runtime-traces-xray',
        DeliveryDestinationType: 'XRAY',
      },
    });

    const wireTraces = (idPrefix: string, runtime: cdk.CfnResource, sourceName: string) => {
      const source = new cdk.CfnResource(this, `${idPrefix}TracesSource`, {
        type: 'AWS::Logs::DeliverySource',
        properties: {
          Name: sourceName,
          LogType: 'TRACES',
          ResourceArn: runtime.getAtt('AgentRuntimeArn'),
        },
      });
      source.addDependency(runtime);

      const delivery = new cdk.CfnResource(this, `${idPrefix}TracesDelivery`, {
        type: 'AWS::Logs::Delivery',
        properties: {
          DeliverySourceName: source.ref,
          DeliveryDestinationArn: tracesDestination.getAtt('Arn'),
        },
      });
      delivery.addDependency(source);
      delivery.addDependency(tracesDestination);
    };

    wireTraces('LangGraphRuntime', lgRuntime, 'cat-demo-langgraph-runtime-traces');
    wireTraces('StrandsRuntime', strandsRuntime, 'cat-demo-strands-runtime-traces');

    new cdk.CfnOutput(this, 'LangGraphRuntimeArn', { value: this.langgraphRuntimeArn });
    new cdk.CfnOutput(this, 'StrandsRuntimeArn', { value: this.strandsRuntimeArn });
  }
}

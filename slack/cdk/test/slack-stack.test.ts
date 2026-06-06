import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { SlackStack } from '../lib/slack-stack';

describe('SlackStack', () => {
  let template: Template;

  const props = {
    projectName: 'aiops-cat-demo',
    alarmTopicArn: 'arn:aws:sns:us-east-1:123456789012:aiops-cat-demo-alarms',
    webhookSecretArn: 'arn:aws:secretsmanager:us-east-1:123456789012:secret:aiops-cat-demo/devops-agent-webhook-AbCdEf',
    slackSecretArn: 'arn:aws:secretsmanager:us-east-1:123456789012:secret:aiops-cat-demo/slack-bot-GhIjKl',
    operatorRoleArn: 'arn:aws:iam::123456789012:role/service-role/DevOpsAgentRole-WebappAdmin-test123',
    deploymentId: 'a1b2c3d4',
  };

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new SlackStack(app, 'TestSlackStack', props);
    template = Template.fromStack(stack);
  });

  describe('Webhook Lambda', () => {
    it('has Python 3.12 runtime, ARM64 architecture, 256 MB memory, and 30s timeout', () => {
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'aiops-cat-demo-webhook-forwarder',
        Runtime: 'python3.12',
        Architectures: ['arm64'],
        MemorySize: 256,
        Timeout: 30,
      });
    });
  });

  describe('Slack Handler Lambda', () => {
    it('has Python 3.12 runtime, ARM64 architecture, 256 MB memory, and 10s timeout', () => {
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'aiops-cat-demo-slack-handler',
        Runtime: 'python3.12',
        Architectures: ['arm64'],
        MemorySize: 256,
        Timeout: 10,
      });
    });
  });

  describe('Slack Worker Lambda', () => {
    it('has Python 3.12 runtime, ARM64 architecture, 256 MB memory, and 60s timeout', () => {
      template.hasResourceProperties('AWS::Lambda::Function', {
        FunctionName: 'aiops-cat-demo-slack-worker',
        Runtime: 'python3.12',
        Architectures: ['arm64'],
        MemorySize: 256,
        Timeout: 60,
      });
    });
  });

  describe('API Gateway HTTP API', () => {
    it('creates an HTTP API', () => {
      template.hasResourceProperties('AWS::ApiGatewayV2::Api', {
        Name: 'aiops-cat-demo-slack-api',
        ProtocolType: 'HTTP',
      });
    });

    it('has a POST /slack/events route', () => {
      template.hasResourceProperties('AWS::ApiGatewayV2::Route', {
        RouteKey: 'POST /slack/events',
      });
    });
  });

  describe('SNS Subscription', () => {
    it('connects the alarm topic to the Webhook Lambda', () => {
      template.hasResourceProperties('AWS::SNS::Subscription', {
        Protocol: 'lambda',
        TopicArn: props.alarmTopicArn,
      });
    });
  });

  describe('IAM Policies', () => {
    it('scopes Webhook Lambda secret access to the webhook secret ARN', () => {
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: 'secretsmanager:GetSecretValue',
              Effect: 'Allow',
              Resource: `${props.webhookSecretArn}*`,
            }),
          ]),
        },
      });
    });

    it('scopes Slack Handler secret access to the Slack secret ARN', () => {
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: 'secretsmanager:GetSecretValue',
              Effect: 'Allow',
              Resource: `${props.slackSecretArn}*`,
            }),
          ]),
        },
      });
    });

    it('scopes Slack Worker assume-role access to the operator role ARN', () => {
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: ['sts:AssumeRole', 'sts:TagSession'],
              Effect: 'Allow',
              Resource: props.operatorRoleArn,
            }),
          ]),
        },
      });
    });
  });

  describe('Reference-only pattern', () => {
    it('does not create any Secrets Manager secret resources', () => {
      template.resourceCountIs('AWS::SecretsManager::Secret', 0);
    });
  });

  describe('Stack Outputs', () => {
    it('includes the API Gateway endpoint URL', () => {
      template.hasOutput('SlackApiEndpoint', {
        Description: 'Set this as the Slack App Request URL (Events + Slash Commands).',
      });
    });

    it('includes the Worker role name and ARN', () => {
      template.hasOutput('SlackWorkerRoleName', {});
      template.hasOutput('SlackWorkerRoleArn', {});
    });
  });
});

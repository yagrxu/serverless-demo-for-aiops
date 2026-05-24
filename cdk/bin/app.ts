#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { Aspects } from 'aws-cdk-lib';
import { AwsSolutionsChecks, NagSuppressions } from 'cdk-nag';
import { DataStack } from '../lib/data-stack';
import { ApiStack } from '../lib/api-stack';
import { GatewayStack } from '../lib/gateway-stack';
import { AgentStack } from '../lib/agent-stack';
import { EcrStack } from '../lib/ecr-stack';
import { UiStack } from '../lib/ui-stack';
import { FargateStack } from '../lib/fargate-stack';
import { ObservabilityStack } from '../lib/observability-stack';
import { TrafgenStack } from '../lib/trafgen-stack';
import { defaultConfig } from '../lib/config';

const app = new cdk.App();
const cfg = defaultConfig;

// This demo always deploys to us-east-1, regardless of the caller's
// default region. AgentCore Runtime is only available in a small set of
// regions, and pinning here keeps test/prod accounts aligned.
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: 'us-east-1',
};

// Image tag for the AgentCore runtimes and chatbot. CI passes the commit
// SHA via `-c imageTag=$GITHUB_SHA`. Local deploys fall back to `latest`.
const imageTag = (app.node.tryGetContext('imageTag') as string) || 'latest';

// Deploying the AgentStack requires images to already be pushed.
// CI does that between EcrStack and AgentStack deploys. For local
// initial deploys, set `-c skipAgents=true` to skip AgentStack.
const skipAgents = app.node.tryGetContext('skipAgents') === 'true';

const ecr = new EcrStack(app, `${cfg.projectName}-ecr`, cfg.projectName, { env });

const data = new DataStack(app, `${cfg.projectName}-data`, { env });

const api = new ApiStack(app, `${cfg.projectName}-api`, {
  env,
  catProfiles: data.catProfiles,
  catNameIndex: data.catNameIndex,
  devices: data.devices,
  deviceTelemetry: data.deviceTelemetry,
  feedingEvents: data.feedingEvents,
  healthMetrics: data.healthMetrics,
  healthAlerts: data.healthAlerts,
});

// Observability_Stack is created at the END of app.ts so it can take
// references from every other stack (Lambdas, DDB tables, CloudFront
// distribution). It owns Application Signals discovery, the three
// persona dashboards, the SNS alarm topic, and all alarms 6.1–6.10.

const gateway = new GatewayStack(app, `${cfg.projectName}-gateway`, {
  env,
  lambdaArns: {
    catProfile: api.catProfileFnArn,
    device: api.deviceFnArn,
    feeding: api.feedingFnArn,
    health: api.healthFnArn,
  },
});

// --- Chatbot Fargate + Agents ---
let chatbotAlbDnsName: string | undefined;

if (cfg.deployAgents && !skipAgents) {
  const agents = new AgentStack(app, `${cfg.projectName}-agents`, {
    env,
    mcpServerUrl: gateway.gatewayUrlValue,
    imageTag,
    repos: ecr.repos,
  });

  const fargate = new FargateStack(app, `${cfg.projectName}-fargate`, {
    env,
    imageTag,
    chatbotRepo: ecr.repos.chatbot,
    langgraphRuntimeArn: agents.langgraphRuntimeArn,
    strandsRuntimeArn: agents.strandsRuntimeArn,
  });
  fargate.addDependency(agents);

  chatbotAlbDnsName = fargate.albDnsName;
} else {
  // When agents are skipped, deploy Fargate with placeholder ARNs.
  const fargate = new FargateStack(app, `${cfg.projectName}-fargate`, {
    env,
    imageTag,
    chatbotRepo: ecr.repos.chatbot,
    langgraphRuntimeArn: 'arn:aws:bedrock-agentcore:us-east-1:PLACEHOLDER:runtime/cat_demo_langgraph',
    strandsRuntimeArn: 'arn:aws:bedrock-agentcore:us-east-1:PLACEHOLDER:runtime/cat_demo_strands',
  });

  chatbotAlbDnsName = fargate.albDnsName;
}

const ui = new UiStack(app, `${cfg.projectName}-ui`, {
  env,
  bundles: cfg.uiBundles,
  apiUrl: api.api.url,
  appRunnerServiceUrl: chatbotAlbDnsName,
  projectName: cfg.projectName,
});

// --- Traffic Generator (optional) ---
// Only construct when `-c trafgenEnabled=true` is passed so it doesn't
// break existing deploys that haven't pushed the trafgen image yet.
const trafgenEnabled = app.node.tryGetContext('trafgenEnabled') === 'true';
if (trafgenEnabled) {
  new TrafgenStack(app, `${cfg.projectName}-trafgen`, {
    env,
    trafgenRepo: ecr.repos.trafgen,
    imageTag,
    apiUrl: api.api.url,
    chatbotUrl: `https://${ui.distribution.distributionDomainName}`,
    langgraphRuntimeArn: 'arn:aws:bedrock-agentcore:us-east-1:PLACEHOLDER:runtime/cat_demo_langgraph',
    strandsRuntimeArn: 'arn:aws:bedrock-agentcore:us-east-1:PLACEHOLDER:runtime/cat_demo_strands',
  });
}

new ObservabilityStack(app, `${cfg.projectName}-observability`, {
  env,
  projectName: cfg.projectName,
  alarmEmail: cfg.alarmEmail,
  lambdas: {
    catProfile: api.catProfileFn,
    device: api.deviceFn,
    feeding: api.feedingFn,
    health: api.healthFn,
  },
  tables: {
    catProfiles: data.catProfiles,
    catNameIndex: data.catNameIndex,
    devices: data.devices,
    deviceTelemetry: data.deviceTelemetry,
    feedingEvents: data.feedingEvents,
    healthMetrics: data.healthMetrics,
    healthAlerts: data.healthAlerts,
  },
  apiAccessLogGroup: api.accessLogGroup,
  cloudfrontDistribution: ui.distribution,
});

// --- cdk-nag: Infrastructure Static Checks ---
// Apply AWS Solutions rule pack when nagEnabled context flag is set.
// Usage: npx cdk synth --no-lookups -c nagEnabled=true
const nagEnabled = app.node.tryGetContext('nagEnabled') === 'true';
if (nagEnabled) {
  Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }));

  // Suppressions for known findings. Each entry requires:
  //   - rule ID (e.g., AwsSolutions-XXX)
  //   - resource path or construct
  //   - justification (≥20 characters)
  // Add suppressions as findings are discovered during the first nag run.
  NagSuppressions.addStackSuppressions(
    cdk.Stack.of(ecr),
    [
      {
        id: 'AwsSolutions-ECR1',
        reason: 'ECR image scanning is not required for this demo application',
      },
    ],
    true,
  );

  NagSuppressions.addStackSuppressions(
    cdk.Stack.of(data),
    [
      {
        id: 'AwsSolutions-DDB3',
        reason: 'Point-in-time recovery is not required for this demo application',
      },
    ],
    true,
  );
}

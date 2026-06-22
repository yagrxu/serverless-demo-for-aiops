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
import { AggregationStack } from '../lib/aggregation-stack';
import { SlackStack } from '../../slack/cdk/lib/slack-stack';
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
  vetRecords: data.vetRecords,
  dailyNutritionRollup: data.dailyNutritionRollup,
  dailyHealthSummary: data.dailyHealthSummary,
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
    vet: api.vetFnArn,
  },
});

// --- Async Aggregation (Phase 5) ---
const aggregation = new AggregationStack(app, `${cfg.projectName}-aggregation`, {
  env,
  feedingEvents: data.feedingEvents,
  healthMetrics: data.healthMetrics,
  dailyNutritionRollup: data.dailyNutritionRollup,
  dailyHealthSummary: data.dailyHealthSummary,
});
aggregation.addDependency(data);

// --- Chatbot Fargate + Agents ---
let chatbotAlbDnsName: string | undefined;
let langgraphRuntimeArn = 'arn:aws:bedrock-agentcore:us-east-1:PLACEHOLDER:runtime/cat_demo_langgraph';
let strandsRuntimeArn = 'arn:aws:bedrock-agentcore:us-east-1:PLACEHOLDER:runtime/cat_demo_strands';

if (cfg.deployAgents && !skipAgents) {
  const agents = new AgentStack(app, `${cfg.projectName}-agents`, {
    env,
    mcpServerUrl: gateway.gatewayUrlValue,
    imageTag,
    repos: ecr.repos,
  });

  langgraphRuntimeArn = agents.langgraphRuntimeArn;
  strandsRuntimeArn = agents.strandsRuntimeArn;

  const fargate = new FargateStack(app, `${cfg.projectName}-fargate`, {
    env,
    imageTag,
    chatbotRepo: ecr.repos.chatbot,
    langgraphRuntimeArn,
    strandsRuntimeArn,
    wxUsersTable: data.wxUsers,
    catProfilesTable: data.catProfiles,
  });
  fargate.addDependency(agents);

  chatbotAlbDnsName = fargate.albDnsName;
} else {
  // When agents are skipped, deploy Fargate with placeholder ARNs.
  const fargate = new FargateStack(app, `${cfg.projectName}-fargate`, {
    env,
    imageTag,
    chatbotRepo: ecr.repos.chatbot,
    langgraphRuntimeArn,
    strandsRuntimeArn,
    wxUsersTable: data.wxUsers,
    catProfilesTable: data.catProfiles,
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
    langgraphRuntimeArn,
    strandsRuntimeArn,
  });
}

const observability = new ObservabilityStack(app, `${cfg.projectName}-observability`, {
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

// --- Slack Integration (optional) ---
// Only construct when `-c slackEnabled=true` is passed so existing
// deploys aren't affected (secrets must be pre-provisioned first).
const slackEnabled = app.node.tryGetContext('slackEnabled') === 'true';
if (slackEnabled) {
  // The Slack Worker role name is suffixed with a random per-deployment id
  // stored in SSM (slack/scripts/ensure-deployment-id.sh). Pass it via context:
  //   -c slackDeploymentId=$(slack/scripts/ensure-deployment-id.sh --profile cloudops-demo)
  const slackDeploymentId = (app.node.tryGetContext('slackDeploymentId') as string) || 'dev';

  const slack = new SlackStack(app, `${cfg.projectName}-slack`, {
    env,
    projectName: cfg.projectName,
    alarmTopicArn: observability.alarmTopicArn,
    webhookSecretArn: (app.node.tryGetContext('webhookSecretArn') as string)
      || `arn:aws:secretsmanager:us-east-1:${env.account}:secret:aiops-cat-demo/devops-agent-webhook`,
    slackSecretArn: (app.node.tryGetContext('slackSecretArn') as string)
      || `arn:aws:secretsmanager:us-east-1:${env.account}:secret:aiops-cat-demo/slack-bot`,
    operatorRoleArn: (app.node.tryGetContext('operatorRoleArn') as string)
      || `arn:aws:iam::${env.account}:role/service-role/DevOpsAgentRole-WebappAdmin-ajf59et7`,
    deploymentId: slackDeploymentId,
  });
  slack.addDependency(observability);
}

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

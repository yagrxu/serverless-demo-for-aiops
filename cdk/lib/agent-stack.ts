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
          EnvironmentVariables: { MCP_SERVER_URL: props.mcpServerUrl },
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

    new cdk.CfnOutput(this, 'LangGraphRuntimeArn', { value: this.langgraphRuntimeArn });
    new cdk.CfnOutput(this, 'StrandsRuntimeArn', { value: this.strandsRuntimeArn });
  }
}

import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ecr from 'aws-cdk-lib/aws-ecr';

/**
 * Named ECR repositories for the AgentCore runtime images and the
 * chatbot App Runner image.
 *
 * Repositories live in their own stack so they're created *before*
 * the CI workflow tries to build+push images. The AgentStack then
 * references the pushed image URI (via CDK context `imageTag`).
 *
 * Lifecycle: keep the last 10 images per repo. Untagged images are
 * expired after 7 days. Repos can be force-deleted (demo-only).
 */
export class EcrStack extends cdk.Stack {
  readonly repos: Record<'langgraph' | 'strands' | 'chatbot', ecr.Repository>;

  constructor(scope: Construct, id: string, projectName: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const mk = (name: 'langgraph' | 'strands' | 'chatbot') =>
      new ecr.Repository(this, `${name}Repo`, {
        repositoryName: `${projectName}-${name}`,
        imageScanOnPush: true,
        emptyOnDelete: true,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
        lifecycleRules: [
          { description: 'Keep last 10 tagged images', maxImageCount: 10 },
          {
            description: 'Expire untagged after 7 days',
            tagStatus: ecr.TagStatus.UNTAGGED,
            maxImageAge: cdk.Duration.days(7),
          },
        ],
      });

    this.repos = {
      langgraph: mk('langgraph'),
      strands: mk('strands'),
      chatbot: mk('chatbot'),
    };

    for (const [k, r] of Object.entries(this.repos)) {
      new cdk.CfnOutput(this, `${k}RepoUri`, { value: r.repositoryUri });
    }
  }
}

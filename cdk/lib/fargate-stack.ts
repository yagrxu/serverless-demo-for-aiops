import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';

export interface FargateStackProps extends cdk.StackProps {
  imageTag: string;
  chatbotRepo: ecr.IRepository;
  langgraphRuntimeArn: string;
  strandsRuntimeArn: string;
  wxUsersTable?: dynamodb.ITable;
  catProfilesTable?: dynamodb.ITable;
}

/**
 * ECS Fargate service for the Next.js chatbot.
 *
 * The chatbot runs server-side API routes that sign requests to
 * AgentCore Runtime with SigV4 via the task role. ALB is restricted
 * to CloudFront-only access via the AWS managed prefix list.
 */
export class FargateStack extends cdk.Stack {
  /** The ALB DNS name for CloudFront origin */
  readonly albDnsName: string;

  constructor(scope: Construct, id: string, props: FargateStackProps) {
    super(scope, id, props);

    // --- VPC ---
    const vpc = new ec2.Vpc(this, 'ChatbotVpc', {
      maxAzs: 2,
      natGateways: 1,
    });

    // --- ECS Cluster ---
    const cluster = new ecs.Cluster(this, 'ChatbotCluster', {
      vpc,
      clusterName: 'aiops-cat-demo-chatbot',
    });

    // --- Task Role (invokes AgentCore Runtime) ---
    const taskRole = new iam.Role(this, 'ChatbotTaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      description: 'Chatbot Fargate task role - invokes AgentCore runtimes',
    });
    taskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock-agentcore:InvokeAgentRuntime'],
      resources: [
        `${props.langgraphRuntimeArn}`,
        `${props.langgraphRuntimeArn}/*`,
        `${props.strandsRuntimeArn}`,
        `${props.strandsRuntimeArn}/*`,
      ],
    }));

    // Grant DDB access for WeChat BFF endpoints
    if (props.wxUsersTable) {
      props.wxUsersTable.grantReadWriteData(taskRole);
    }
    if (props.catProfilesTable) {
      props.catProfilesTable.grantReadData(taskRole);
    }

    // --- Task Definition ---
    const taskDef = new ecs.FargateTaskDefinition(this, 'ChatbotTaskDef', {
      cpu: 512,
      memoryLimitMiB: 1024,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
      taskRole,
    });

    taskDef.addContainer('chatbot', {
      image: ecs.ContainerImage.fromEcrRepository(props.chatbotRepo, props.imageTag),
      portMappings: [{ containerPort: 3000 }],
      environment: {
        LANGGRAPH_RUNTIME_ARN: props.langgraphRuntimeArn,
        STRANDS_RUNTIME_ARN: props.strandsRuntimeArn,
        AWS_REGION: cdk.Stack.of(this).region,
        HOSTNAME: '0.0.0.0',
        PORT: '3000',
        ...(props.wxUsersTable && { WX_USERS_TABLE: props.wxUsersTable.tableName }),
        ...(props.catProfilesTable && { CAT_PROFILES_TABLE: props.catProfilesTable.tableName }),
      },
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'chatbot',
      }),
      healthCheck: {
        command: ['CMD-SHELL', 'wget -q --spider http://localhost:3000/api/health || exit 1'],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(10),
      },
    });

    // --- ALB Security Group (CloudFront only) ---
    const albSg = new ec2.SecurityGroup(this, 'AlbSg', {
      vpc,
      description: 'ALB SG - allows only CloudFront origin-facing IPs',
      allowAllOutbound: true,
    });

    // Use AWS managed prefix list for CloudFront
    albSg.addIngressRule(
      ec2.Peer.prefixList('pl-3b927c52'), // com.amazonaws.global.cloudfront.origin-facing
      ec2.Port.tcp(80),
      'Allow CloudFront origin-facing IPs',
    );

    // --- ALB ---
    const alb = new elbv2.ApplicationLoadBalancer(this, 'ChatbotAlb', {
      vpc,
      internetFacing: true,
      securityGroup: albSg,
    });

    const listener = alb.addListener('HttpListener', {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      open: false, // Don't auto-add 0.0.0.0/0 — we use CloudFront prefix list only
    });

    // --- Fargate Service ---
    const service = new ecs.FargateService(this, 'ChatbotService', {
      cluster,
      taskDefinition: taskDef,
      desiredCount: 1,
      assignPublicIp: false,
    });

    listener.addTargets('ChatbotTarget', {
      port: 3000,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targets: [service],
      healthCheck: {
        path: '/api/health',
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 5,
      },
    });

    // Allow ALB to reach Fargate tasks
    service.connections.allowFrom(albSg, ec2.Port.tcp(3000));

    this.albDnsName = alb.loadBalancerDnsName;

    new cdk.CfnOutput(this, 'AlbUrl', {
      value: `http://${alb.loadBalancerDnsName}`,
      description: 'Chatbot ALB URL (use as CloudFront origin)',
    });
  }
}

import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';

export interface TrafgenStackProps extends cdk.StackProps {
  /** ECR repository for the trafgen image */
  trafgenRepo: ecr.IRepository;
  /** Image tag (commit SHA or 'latest') */
  imageTag: string;
  /** API Gateway URL for the cat-care REST API */
  apiUrl: string;
  /** Chatbot ALB DNS name */
  chatbotUrl: string;
  /** LangGraph AgentCore Runtime ARN */
  langgraphRuntimeArn: string;
  /** Strands AgentCore Runtime ARN */
  strandsRuntimeArn: string;
}

/**
 * CDK stack for the traffic generator Fargate scheduled task.
 *
 * Runs the same `trafgen` CLI as a Fargate task on an hourly
 * EventBridge schedule. Produces trickle traffic against the
 * cat-care demo so AIOps investigation always has a baseline.
 *
 * No static AWS access keys — the task role provides credentials.
 */
export class TrafgenStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: TrafgenStackProps) {
    super(scope, id, props);

    // --- S3 bucket for manifest storage (7-day lifecycle) ---
    const manifestBucket = new s3.Bucket(this, 'ManifestBucket', {
      bucketName: `${id}-manifests`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [
        {
          expiration: cdk.Duration.days(7),
          id: 'ExpireManifestsAfter7Days',
        },
      ],
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    });

    // --- VPC (minimal, 2 AZs, 1 NAT) ---
    const vpc = new ec2.Vpc(this, 'TrafgenVpc', {
      maxAzs: 2,
      natGateways: 1,
    });

    // --- ECS Cluster ---
    const cluster = new ecs.Cluster(this, 'TrafgenCluster', {
      vpc,
      clusterName: 'aiops-cat-demo-trafgen',
    });

    // --- Task Role (s3:PutObject, cloudformation:DescribeStacks) ---
    const taskRole = new iam.Role(this, 'TrafgenTaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      description: 'Trafgen Fargate task role - writes manifests to S3, reads CFN outputs',
    });

    taskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:PutObject'],
      resources: [manifestBucket.arnForObjects('*')],
    }));

    taskRole.addToPolicy(new iam.PolicyStatement({
      actions: ['cloudformation:DescribeStacks'],
      resources: [
        `arn:aws:cloudformation:${this.region}:${this.account}:stack/aiops-cat-demo-*/*`,
      ],
    }));

    // Allow OTel to emit traces and metrics
    taskRole.addToPolicy(new iam.PolicyStatement({
      actions: [
        'xray:PutTraceSegments',
        'xray:PutTelemetryRecords',
        'cloudwatch:PutMetricData',
        'logs:CreateLogStream',
        'logs:PutLogEvents',
        'logs:DescribeLogGroups',
        'logs:DescribeLogStreams',
      ],
      resources: ['*'],
    }));

    // --- Task Definition ---
    const taskDef = new ecs.FargateTaskDefinition(this, 'TrafgenTaskDef', {
      cpu: 512,
      memoryLimitMiB: 1024,
      runtimePlatform: {
        cpuArchitecture: ecs.CpuArchitecture.ARM64,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
      taskRole,
    });

    taskDef.addContainer('trafgen', {
      image: ecs.ContainerImage.fromEcrRepository(props.trafgenRepo, props.imageTag),
      environment: {
        TRAFGEN_API_URL: props.apiUrl,
        TRAFGEN_CHATBOT_URL: props.chatbotUrl,
        TRAFGEN_LANGGRAPH_ARN: props.langgraphRuntimeArn,
        TRAFGEN_STRANDS_ARN: props.strandsRuntimeArn,
        TRAFGEN_S3_BUCKET: manifestBucket.bucketName,
        // OTel: point exporter to the ADOT sidecar
        OTEL_EXPORTER_OTLP_ENDPOINT: 'http://localhost:4317',
        OTEL_SERVICE_NAME: 'trafgen',
        OTEL_RESOURCE_ATTRIBUTES: 'service.name=trafgen,deployment.environment=test,cloud.platform=aws_ecs,cloud.provider=aws',
      },
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'trafgen',
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
    });

    // --- ADOT Collector Sidecar ---
    // Receives OTel traces/metrics from the trafgen container on localhost:4317
    // and exports them to X-Ray and CloudWatch.
    taskDef.addContainer('adot-collector', {
      image: ecs.ContainerImage.fromRegistry(
        'public.ecr.aws/aws-observability/aws-otel-collector:latest'
      ),
      essential: false,
      command: ['--config=/etc/ecs/ecs-xray.yaml'],
      logging: ecs.LogDrivers.awsLogs({
        streamPrefix: 'adot',
        logRetention: logs.RetentionDays.ONE_WEEK,
      }),
      memoryLimitMiB: 64,
    });

    // --- EventBridge Schedule: run every hour ---
    new events.Rule(this, 'TrafgenSchedule', {
      schedule: events.Schedule.rate(cdk.Duration.hours(1)),
      description: 'Run trafgen every hour to produce baseline traffic',
      targets: [
        new targets.EcsTask({
          cluster,
          taskDefinition: taskDef,
          subnetSelection: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
        }),
      ],
    });

    // --- Outputs ---
    new cdk.CfnOutput(this, 'ManifestBucketName', {
      value: manifestBucket.bucketName,
      description: 'S3 bucket for trafgen run manifests',
    });

    new cdk.CfnOutput(this, 'ClusterName', {
      value: cluster.clusterName,
      description: 'ECS cluster running the trafgen task',
    });
  }
}

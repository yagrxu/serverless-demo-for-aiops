import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as path from 'path';
import * as pipes from 'aws-cdk-lib/aws-pipes';
import * as iam from 'aws-cdk-lib/aws-iam';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';

export interface AggregationStackProps extends cdk.StackProps {
  feedingEvents: dynamodb.Table;
  healthMetrics: dynamodb.Table;
  dailyNutritionRollup: dynamodb.Table;
  dailyHealthSummary: dynamodb.Table;
}

/**
 * Phase 5: Async aggregation pipeline.
 *
 * DDB Streams → EventBridge Pipes → SQS → Rollup Lambdas → Rollup Tables
 *
 * Each source table gets a DDB Stream enabled, piped through EventBridge Pipes
 * to a dedicated SQS queue with a DLQ. Rollup Lambdas consume from SQS.
 */
export class AggregationStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: AggregationStackProps) {
    super(scope, id, props);

    const lambdaCommon: Partial<lambda.FunctionProps> = {
      runtime: lambda.Runtime.PYTHON_3_12,
      memorySize: 256,
      timeout: cdk.Duration.seconds(30),
      tracing: lambda.Tracing.ACTIVE,
      logRetention: logs.RetentionDays.ONE_WEEK,
    };

    const bundledCode = (svcDir: string) =>
      lambda.Code.fromAsset(path.join(__dirname, '../lambda', svcDir), {
        bundling: {
          image: lambda.Runtime.PYTHON_3_12.bundlingImage,
          command: [
            'bash', '-c',
            'pip install --no-cache-dir -r requirements.txt -t /asset-output && cp -au . /asset-output',
          ],
        },
      });

    // --- Nutrition rollup pipeline ---
    const nutritionDlq = new sqs.Queue(this, 'NutritionDLQ', {
      retentionPeriod: cdk.Duration.days(14),
    });
    const nutritionQueue = new sqs.Queue(this, 'NutritionQueue', {
      visibilityTimeout: cdk.Duration.seconds(60),
      deadLetterQueue: { queue: nutritionDlq, maxReceiveCount: 3 },
    });

    const nutritionFn = new lambda.Function(this, 'NutritionRollupFn', {
      ...lambdaCommon,
      handler: 'handler.lambda_handler',
      code: bundledCode('rollup-nutrition'),
      environment: {
        FEEDING_EVENTS_TABLE: props.feedingEvents.tableName,
        DAILY_NUTRITION_ROLLUP_TABLE: props.dailyNutritionRollup.tableName,
      },
    } as lambda.FunctionProps);
    props.feedingEvents.grantReadData(nutritionFn);
    props.dailyNutritionRollup.grantReadWriteData(nutritionFn);
    nutritionFn.addEventSource(new SqsEventSource(nutritionQueue, { batchSize: 10 }));

    // --- Health summary pipeline ---
    const healthDlq = new sqs.Queue(this, 'HealthDLQ', {
      retentionPeriod: cdk.Duration.days(14),
    });
    const healthQueue = new sqs.Queue(this, 'HealthQueue', {
      visibilityTimeout: cdk.Duration.seconds(60),
      deadLetterQueue: { queue: healthDlq, maxReceiveCount: 3 },
    });

    const healthFn = new lambda.Function(this, 'HealthSummaryFn', {
      ...lambdaCommon,
      handler: 'handler.lambda_handler',
      code: bundledCode('rollup-health'),
      environment: {
        HEALTH_METRICS_TABLE: props.healthMetrics.tableName,
        DAILY_HEALTH_SUMMARY_TABLE: props.dailyHealthSummary.tableName,
      },
    } as lambda.FunctionProps);
    props.healthMetrics.grantReadData(healthFn);
    props.dailyHealthSummary.grantReadWriteData(healthFn);
    healthFn.addEventSource(new SqsEventSource(healthQueue, { batchSize: 10 }));

    // --- EventBridge Pipes: DDB Stream → SQS ---
    // Pipe role needs stream read + SQS send
    const pipeRole = new iam.Role(this, 'PipeRole', {
      assumedBy: new iam.ServicePrincipal('pipes.amazonaws.com'),
    });
    props.feedingEvents.grantStreamRead(pipeRole);
    props.healthMetrics.grantStreamRead(pipeRole);
    nutritionQueue.grantSendMessages(pipeRole);
    healthQueue.grantSendMessages(pipeRole);

    // Feeding → Nutrition queue
    new pipes.CfnPipe(this, 'FeedingPipe', {
      roleArn: pipeRole.roleArn,
      source: props.feedingEvents.tableStreamArn!,
      sourceParameters: {
        dynamoDbStreamParameters: {
          startingPosition: 'LATEST',
          batchSize: 10,
          maximumRetryAttempts: 3,
        },
      },
      target: nutritionQueue.queueArn,
    });

    // HealthMetrics → Health queue
    new pipes.CfnPipe(this, 'HealthPipe', {
      roleArn: pipeRole.roleArn,
      source: props.healthMetrics.tableStreamArn!,
      sourceParameters: {
        dynamoDbStreamParameters: {
          startingPosition: 'LATEST',
          batchSize: 10,
          maximumRetryAttempts: 3,
        },
      },
      target: healthQueue.queueArn,
    });
  }
}

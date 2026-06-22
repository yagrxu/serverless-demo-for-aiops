import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as path from 'path';
import { applyApplicationSignalsToLambda } from './observability';

export interface ApiStackProps extends cdk.StackProps {
  catProfiles: dynamodb.Table;
  catNameIndex: dynamodb.Table;
  devices: dynamodb.Table;
  deviceTelemetry: dynamodb.Table;
  feedingEvents: dynamodb.Table;
  healthMetrics: dynamodb.Table;
  healthAlerts: dynamodb.Table;
  vetRecords: dynamodb.Table;
  dailyNutritionRollup: dynamodb.Table;
  dailyHealthSummary: dynamodb.Table;
}

/**
 * REST API backed by four Python Lambdas — one per bounded context.
 *
 * Handlers live under cdk/lambda/<service>/ and are the place source-level
 * bugs should be injected for AIOps investigations.
 */
export class ApiStack extends cdk.Stack {
  readonly api: apigateway.RestApi;
  readonly apiUrl: cdk.CfnOutput;
  readonly catProfileFnArn: string;
  readonly deviceFnArn: string;
  readonly feedingFnArn: string;
  readonly healthFnArn: string;
  readonly vetFnArn: string;
  // Function refs and the access log group are exposed so the
  // Observability_Stack can build dashboards / log query definitions
  // against them without re-deriving names.
  readonly catProfileFn: lambda.IFunction;
  readonly deviceFn: lambda.IFunction;
  readonly feedingFn: lambda.IFunction;
  readonly healthFn: lambda.IFunction;
  readonly vetFn: lambda.IFunction;
  readonly accessLogGroup: logs.ILogGroup;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const lambdaCommon: Partial<lambda.FunctionProps> = {
      runtime: lambda.Runtime.PYTHON_3_12,
      memorySize: 256,
      timeout: cdk.Duration.seconds(10),
      tracing: lambda.Tracing.ACTIVE,
      logRetention: logs.RetentionDays.ONE_WEEK,
    };

    // Bundle each handler with its requirements.txt so Powertools
    // (Logger, Metrics) is available without per-region layer ARNs.
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

    // --- cat-profile ---
    const catFn = new lambda.Function(this, 'CatProfileFn', {
      ...lambdaCommon,
      handler: 'handler.lambda_handler',
      code: bundledCode('cat-profile'),
      environment: { CAT_PROFILES_TABLE: props.catProfiles.tableName, CAT_NAME_INDEX_TABLE: props.catNameIndex.tableName },
    } as lambda.FunctionProps);
    props.catProfiles.grantReadWriteData(catFn);
    props.catNameIndex.grantReadWriteData(catFn);

    // --- device ---
    const deviceFn = new lambda.Function(this, 'DeviceFn', {
      ...lambdaCommon,
      handler: 'handler.lambda_handler',
      code: bundledCode('device'),
      environment: {
        DEVICES_TABLE: props.devices.tableName,
        DEVICE_TELEMETRY_TABLE: props.deviceTelemetry.tableName,
        FEEDING_EVENTS_TABLE: props.feedingEvents.tableName,
      },
    } as lambda.FunctionProps);
    props.devices.grantReadWriteData(deviceFn);
    props.deviceTelemetry.grantReadWriteData(deviceFn);
    props.feedingEvents.grantReadData(deviceFn);

    // --- feeding ---
    const feedingFn = new lambda.Function(this, 'FeedingFn', {
      ...lambdaCommon,
      handler: 'handler.lambda_handler',
      code: bundledCode('feeding'),
      environment: {
        FEEDING_EVENTS_TABLE: props.feedingEvents.tableName,
        HEALTH_ALERTS_TABLE: props.healthAlerts.tableName,
        DAILY_LIMIT_GRAMS: '200',
        WET_FOOD_DAILY_LIMIT: '100',
        DRY_FOOD_DAILY_LIMIT: '150',
        MIN_INTERVAL_HOURS: '2',
      },
    } as lambda.FunctionProps);
    props.feedingEvents.grantReadWriteData(feedingFn);
    props.healthAlerts.grantWriteData(feedingFn);

    // --- health ---
    const healthFn = new lambda.Function(this, 'HealthFn', {
      ...lambdaCommon,
      handler: 'handler.lambda_handler',
      code: bundledCode('health'),
      environment: {
        HEALTH_METRICS_TABLE: props.healthMetrics.tableName,
        HEALTH_ALERTS_TABLE: props.healthAlerts.tableName,
        FEEDING_EVENTS_TABLE: props.feedingEvents.tableName,
        DAILY_NUTRITION_ROLLUP_TABLE: props.dailyNutritionRollup.tableName,
        DAILY_HEALTH_SUMMARY_TABLE: props.dailyHealthSummary.tableName,
      },
    } as lambda.FunctionProps);
    props.healthMetrics.grantReadWriteData(healthFn);
    props.healthAlerts.grantReadWriteData(healthFn);
    props.feedingEvents.grantReadData(healthFn);
    props.dailyNutritionRollup.grantReadData(healthFn);
    props.dailyHealthSummary.grantReadData(healthFn);

    // --- vet ---
    const vetFn = new lambda.Function(this, 'VetFn', {
      ...lambdaCommon,
      handler: 'handler.lambda_handler',
      code: bundledCode('vet'),
      environment: {
        VET_RECORDS_TABLE: props.vetRecords.tableName,
      },
    } as lambda.FunctionProps);
    props.vetRecords.grantReadWriteData(vetFn);

    // Wire CloudWatch Application Signals onto every Lambda. The helper
    // is region-portable — it picks the right ADOT layer ARN for the
    // stack's region and attaches the managed policy.
    for (const fn of [catFn, deviceFn, feedingFn, healthFn, vetFn]) {
      applyApplicationSignalsToLambda(fn);
    }

    // Expose Lambda ARNs for GatewayStack and Lambda refs for
    // Observability_Stack.
    this.catProfileFnArn = catFn.functionArn;
    this.deviceFnArn = deviceFn.functionArn;
    this.feedingFnArn = feedingFn.functionArn;
    this.healthFnArn = healthFn.functionArn;
    this.vetFnArn = vetFn.functionArn;
    this.catProfileFn = catFn;
    this.deviceFn = deviceFn;
    this.feedingFn = feedingFn;
    this.healthFn = healthFn;
    this.vetFn = vetFn;

    // --- API Gateway ---
    // JSON access logs to a dedicated log group so Logs Insights queries
    // can join on $context.requestId / $context.xrayTraceId. Required
    // fields per design §API Gateway access log JSON format.
    const apiAccessLogs = new logs.LogGroup(this, 'ApiAccessLogs', {
      logGroupName: '/aws/apigateway/cat-demo-access',
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    this.accessLogGroup = apiAccessLogs;

    const accessLogFormat = JSON.stringify({
      requestId:         '$context.requestId',
      extendedRequestId: '$context.extendedRequestId',
      status:            '$context.status',
      resourcePath:      '$context.resourcePath',
      httpMethod:        '$context.httpMethod',
      responseLatency:   '$context.responseLatency',
      integrationStatus: '$context.integrationStatus',
      integrationLatency:'$context.integrationLatency',
      requestTime:       '$context.requestTime',
      sourceIp:          '$context.identity.sourceIp',
      userAgent:         '$context.identity.userAgent',
      xrayTraceId:       '$context.xrayTraceId',
    });

    this.api = new apigateway.RestApi(this, 'Api', {
      restApiName: 'cat-demo-api',
      deployOptions: {
        stageName: 'prod',
        tracingEnabled: true,
        metricsEnabled: true,
        accessLogDestination: new apigateway.LogGroupLogDestination(apiAccessLogs),
        accessLogFormat: apigateway.AccessLogFormat.custom(accessLogFormat),
      },
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: apigateway.Cors.ALL_METHODS,
      },
    });

    // /cats, /cats/lookup, /cats/{id}
    const cats = this.api.root.addResource('cats');
    cats.addMethod('GET', new apigateway.LambdaIntegration(catFn));
    cats.addMethod('POST', new apigateway.LambdaIntegration(catFn));
    cats.addResource('lookup').addMethod('GET', new apigateway.LambdaIntegration(catFn));
    cats.addResource('{id}').addMethod('GET', new apigateway.LambdaIntegration(catFn));

    // /devices, /devices/{id}, /devices/{id}/commands, /devices/{id}/telemetry
    const devices = this.api.root.addResource('devices');
    devices.addMethod('GET', new apigateway.LambdaIntegration(deviceFn));
    const deviceById = devices.addResource('{id}');
    deviceById.addMethod('GET', new apigateway.LambdaIntegration(deviceFn));
    deviceById.addResource('commands').addMethod('POST', new apigateway.LambdaIntegration(deviceFn));
    deviceById.addResource('telemetry').addMethod('POST', new apigateway.LambdaIntegration(deviceFn));

    // /feedings
    const feedings = this.api.root.addResource('feedings');
    feedings.addMethod('GET', new apigateway.LambdaIntegration(feedingFn));
    feedings.addMethod('POST', new apigateway.LambdaIntegration(feedingFn));

    // /health/{cat_id}, /health/{cat_id}/alerts
    const health = this.api.root.addResource('health').addResource('{cat_id}');
    health.addMethod('GET', new apigateway.LambdaIntegration(healthFn));
    health.addResource('alerts').addMethod('GET', new apigateway.LambdaIntegration(healthFn));

    // /vet/{cat_id}
    const vet = this.api.root.addResource('vet').addResource('{cat_id}');
    vet.addMethod('GET', new apigateway.LambdaIntegration(vetFn));
    vet.addMethod('POST', new apigateway.LambdaIntegration(vetFn));

    this.apiUrl = new cdk.CfnOutput(this, 'ApiUrl', { value: this.api.url });
  }
}

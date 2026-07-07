import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as applicationsignals from 'aws-cdk-lib/aws-applicationsignals';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatch_actions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as sns_subs from 'aws-cdk-lib/aws-sns-subscriptions';

export interface ObservabilityStackProps extends cdk.StackProps {
  readonly projectName: string;

  // Refs the dashboards + log query definitions need.
  readonly lambdas: {
    catProfile: lambda.IFunction;
    device: lambda.IFunction;
    feeding: lambda.IFunction;
    health: lambda.IFunction;
  };
  readonly tables: {
    catProfiles: dynamodb.ITable;
    catNameIndex: dynamodb.ITable;
    devices: dynamodb.ITable;
    deviceTelemetry: dynamodb.ITable;
    feedingEvents: dynamodb.ITable;
    healthMetrics: dynamodb.ITable;
    healthAlerts: dynamodb.ITable;
  };
  readonly apiAccessLogGroup: logs.ILogGroup;

  // CloudFront distribution backing the chatbot + static UIs. Used to
  // build alarm 6.10 (5xx error rate). Optional so the stack can synth
  // without UiStack present (e.g. in tests).
  readonly cloudfrontDistribution?: cloudfront.IDistribution;

  // Alarm subscriber. Pulled from `config.alarmEmail`. Optional so
  // synth still works in test contexts where no email is configured.
  readonly alarmEmail?: string;

  // AgentCore Runtime names — used as the dimension `runtime` in the
  // `bedrock-agentcore` namespace. Defaulted to the demo names from
  // AgentStack so callers don't have to rewire if they're unchanged.
  readonly langgraphRuntimeName?: string;
  readonly strandsRuntimeName?: string;
}

/**
 * Account/region-scoped observability resources.
 *
 * Owns:
 *  - Application Signals discovery (one per account+region).
 *  - The three persona dashboards (SRE, GenAI, Business) per Req 5.1–5.3.
 *  - The saved Logs Insights query library per Req 5.4.
 *
 * Future phases will add the SNS topic, alarms, anomaly detectors, RUM,
 * and the CloudWatch Investigations group.
 *
 * Transaction Search enablement is intentionally NOT in this stack: it
 * depends on `xray:UpdateTraceSegmentDestination` which has a ~10-minute
 * propagation lag and is documented as a one-time operator action in
 * CICD.md. Keeping it out of CDK avoids stack lifecycle coupling to a
 * slow side-effect.
 */
export class ObservabilityStack extends cdk.Stack {
  /**
   * Alarms that should appear in the SRE dashboard's `AlarmStatusWidget`.
   * Phase 4 (task 7.1) appends to this list before the dashboard is
   * synthesized — `cloudwatch.Dashboard.addWidgets` is invoked AFTER
   * construction in this stack, so this works without ordering hacks.
   */
  public readonly alarms: cloudwatch.IAlarm[] = [];

  /** ARN of the SNS alarm topic (consumed by the Slack integration stack). */
  public readonly alarmTopicArn: string;

  // Held so phase 4 can attach alarms to the existing dashboard rather
  // than recreate it.
  public readonly sreDashboard: cloudwatch.Dashboard;
  public readonly genaiDashboard: cloudwatch.Dashboard;
  public readonly businessDashboard: cloudwatch.Dashboard;

  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------
    // Application Signals Discovery (Req 1.1)
    // ---------------------------------------------------------------
    // CfnDiscovery creates the Application Signals service-linked role
    // and grants the discovery service permission to read X-Ray, Logs,
    // CloudWatch metrics, and tag data. Idempotent; redeploys are no-ops.
    new applicationsignals.CfnDiscovery(this, 'ApplicationSignalsDiscovery', {});

    const lgRuntime = props.langgraphRuntimeName ?? 'cat_demo_langgraph';
    const strandsRuntime = props.strandsRuntimeName ?? 'cat_demo_strands';

    // ---------------------------------------------------------------
    // SRE Dashboard (Req 5.1) — 8 rows per design §Dashboard widget
    // taxonomy.
    // ---------------------------------------------------------------
    const sreDashboard = new cloudwatch.Dashboard(this, 'SreDashboard', {
      dashboardName: `${props.projectName}-sre`,
      defaultInterval: cdk.Duration.hours(1),
    });
    this.sreDashboard = sreDashboard;

    // Row 1 — AlarmStatusWidget. Phase 4 appends to `this.alarms` BEFORE
    // synth completes, so the widget picks them up. We bind the array
    // by reference via a getter on the widget below.
    sreDashboard.addWidgets(
      new cloudwatch.AlarmStatusWidget({
        title: 'Active alarms',
        alarms: this.alarms, // mutated in place by Phase 4
        width: 24,
        height: 4,
      })
    );

    const fns = props.lambdas;
    const apiName = 'cat-demo-api';

    // Row 2 — API Gateway 4XXError + 5XXError (overall, plus per-method
    // detail). The dashboard widget taxonomy in design.md asks for
    // per-resource-path counts; CloudWatch's API Gateway metrics are
    // dimensioned by `ApiName` + `Method` + `Resource`. We start with
    // overall totals and a single per-resource Resource widget — the
    // demo only has ~6 paths, all in one chart is fine.
    sreDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'API Gateway — 4XXError (sum/min)',
        width: 12,
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/ApiGateway',
            metricName: '4XXError',
            dimensionsMap: { ApiName: apiName },
            statistic: 'Sum',
            period: cdk.Duration.minutes(1),
          }),
        ],
      }),
      new cloudwatch.GraphWidget({
        title: 'API Gateway — 5XXError (sum/min)',
        width: 12,
        left: [
          new cloudwatch.Metric({
            namespace: 'AWS/ApiGateway',
            metricName: '5XXError',
            dimensionsMap: { ApiName: apiName },
            statistic: 'Sum',
            period: cdk.Duration.minutes(1),
          }),
        ],
      })
    );

    // Row 3 — Per-Lambda Duration p50/p90/p99 (one widget per function).
    sreDashboard.addWidgets(
      ...Object.values(fns).map(
        (fn) =>
          new cloudwatch.GraphWidget({
            title: `Lambda Duration — ${fn.functionName}`,
            width: 6,
            left: [
              fn.metricDuration({ statistic: 'p50', period: cdk.Duration.minutes(1), label: 'p50' }),
              fn.metricDuration({ statistic: 'p90', period: cdk.Duration.minutes(1), label: 'p90' }),
              fn.metricDuration({ statistic: 'p99', period: cdk.Duration.minutes(1), label: 'p99' }),
            ],
          })
      )
    );

    // Row 4 — Per-Lambda Errors + Throttles (stacked).
    sreDashboard.addWidgets(
      ...Object.values(fns).map(
        (fn) =>
          new cloudwatch.GraphWidget({
            title: `Lambda Errors / Throttles — ${fn.functionName}`,
            width: 6,
            stacked: true,
            left: [
              fn.metricErrors({ statistic: 'Sum', period: cdk.Duration.minutes(1), label: 'Errors' }),
              fn.metricThrottles({ statistic: 'Sum', period: cdk.Duration.minutes(1), label: 'Throttles' }),
            ],
          })
      )
    );

    // Row 5 — Per-table read + write capacity. Seven tables → seven
    // widgets, two metrics each, width 6 puts four per row (CloudWatch
    // wraps automatically).
    const allTables: dynamodb.ITable[] = [
      props.tables.catProfiles,
      props.tables.catNameIndex,
      props.tables.devices,
      props.tables.deviceTelemetry,
      props.tables.feedingEvents,
      props.tables.healthMetrics,
      props.tables.healthAlerts,
    ];
    sreDashboard.addWidgets(
      ...allTables.map(
        (t) =>
          new cloudwatch.GraphWidget({
            title: `DDB capacity — ${t.tableName}`,
            width: 6,
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/DynamoDB',
                metricName: 'ConsumedReadCapacityUnits',
                dimensionsMap: { TableName: t.tableName },
                statistic: 'Sum',
                period: cdk.Duration.minutes(1),
                label: 'Read',
              }),
              new cloudwatch.Metric({
                namespace: 'AWS/DynamoDB',
                metricName: 'ConsumedWriteCapacityUnits',
                dimensionsMap: { TableName: t.tableName },
                statistic: 'Sum',
                period: cdk.Duration.minutes(1),
                label: 'Write',
              }),
            ],
          })
      )
    );

    // Row 6 — Per-table ThrottledRequests.
    sreDashboard.addWidgets(
      ...allTables.map(
        (t) =>
          new cloudwatch.GraphWidget({
            title: `DDB throttles — ${t.tableName}`,
            width: 6,
            left: [
              new cloudwatch.Metric({
                namespace: 'AWS/DynamoDB',
                metricName: 'ThrottledRequests',
                dimensionsMap: { TableName: t.tableName },
                statistic: 'Sum',
                period: cdk.Duration.minutes(1),
              }),
            ],
          })
      )
    );

    // Rows 7 + 8 — Contributor Insights widgets are added in Phase 4
    // (task 7.2) once Contributor Insights is enabled on DeviceTelemetry
    // and HealthMetrics. Placeholder text widget so the row count is
    // stable for snapshot tests.
    sreDashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown:
          '## Contributor Insights\n\n_DeviceTelemetry + HealthMetrics top-partition widgets are wired in Phase 4 once Contributor Insights is enabled on those tables._',
        width: 24,
        height: 2,
      })
    );

    // ---------------------------------------------------------------
    // GenAI Dashboard (Req 5.2) — 6 rows.
    // ---------------------------------------------------------------
    const genaiDashboard = new cloudwatch.Dashboard(this, 'GenAiDashboard', {
      dashboardName: `${props.projectName}-genai`,
      defaultInterval: cdk.Duration.hours(1),
    });
    this.genaiDashboard = genaiDashboard;

    // Row 1 — markdown link to the GenAI Observability console. Filtering
    // by runtime ARN happens via the console's URL params; we hard-code
    // the runtime *names* as a hint.
    genaiDashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown: [
          '## GenAI Observability',
          '',
          `[Open CloudWatch GenAI Observability →](https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#gen-ai-observability)`,
          '',
          `Runtimes: \`${lgRuntime}\`, \`${strandsRuntime}\``,
        ].join('\n'),
        width: 24,
        height: 3,
      })
    );

    // Row 2 — Per-runtime InvocationLatency p50/p90/p99 from
    // `bedrock-agentcore` namespace. Dimension key for the runtime is
    // `agent_runtime_id` per AWS docs; our runtime name is what's used
    // as the friendly identifier.
    const runtimeLatencyWidget = (runtimeName: string) =>
      new cloudwatch.GraphWidget({
        title: `Invocation latency — ${runtimeName}`,
        width: 12,
        left: ['p50', 'p90', 'p99'].map(
          (stat) =>
            new cloudwatch.Metric({
              namespace: 'bedrock-agentcore',
              metricName: 'InvocationLatency',
              dimensionsMap: { runtime: runtimeName },
              statistic: stat,
              period: cdk.Duration.minutes(1),
              label: stat,
            })
        ),
      });
    genaiDashboard.addWidgets(runtimeLatencyWidget(lgRuntime), runtimeLatencyWidget(strandsRuntime));

    // Row 3 — Per-runtime token usage.
    const runtimeTokenWidget = (runtimeName: string) =>
      new cloudwatch.GraphWidget({
        title: `Token usage — ${runtimeName}`,
        width: 12,
        left: [
          new cloudwatch.Metric({
            namespace: 'bedrock-agentcore',
            metricName: 'InputTokens',
            dimensionsMap: { runtime: runtimeName },
            statistic: 'Sum',
            period: cdk.Duration.minutes(1),
            label: 'Input',
          }),
          new cloudwatch.Metric({
            namespace: 'bedrock-agentcore',
            metricName: 'OutputTokens',
            dimensionsMap: { runtime: runtimeName },
            statistic: 'Sum',
            period: cdk.Duration.minutes(1),
            label: 'Output',
          }),
        ],
      });
    genaiDashboard.addWidgets(runtimeTokenWidget(lgRuntime), runtimeTokenWidget(strandsRuntime));

    // Row 4 — single chart, two-series LangGraph vs Strands p95 latency.
    genaiDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'LangGraph vs Strands — InvocationLatency p95',
        width: 24,
        left: [
          new cloudwatch.Metric({
            namespace: 'bedrock-agentcore',
            metricName: 'InvocationLatency',
            dimensionsMap: { runtime: lgRuntime },
            statistic: 'p95',
            period: cdk.Duration.minutes(1),
            label: 'LangGraph p95',
          }),
          new cloudwatch.Metric({
            namespace: 'bedrock-agentcore',
            metricName: 'InvocationLatency',
            dimensionsMap: { runtime: strandsRuntime },
            statistic: 'p95',
            period: cdk.Duration.minutes(1),
            label: 'Strands p95',
          }),
        ],
      })
    );

    // Row 5 — slowest tool calls in the last hour (Logs Insights widget).
    // The actual log group names are managed by AgentCore and follow
    // /aws/bedrock-agentcore/runtimes/<runtime-id>; we wildcard by
    // prefix so naming changes don't break the widget.
    genaiDashboard.addWidgets(
      new cloudwatch.LogQueryWidget({
        title: 'Slowest tool calls — last hour',
        width: 24,
        height: 6,
        logGroupNames: [
          `/aws/bedrock-agentcore/runtimes/${lgRuntime}`,
          `/aws/bedrock-agentcore/runtimes/${strandsRuntime}`,
        ],
        queryLines: [
          'fields @timestamp, tool_name, tool_call_duration_ms',
          'filter ispresent(tool_call_duration_ms)',
          'sort tool_call_duration_ms desc',
          'limit 20',
        ],
      })
    );

    // Row 6 — Gateway target invocation errors stacked by target. The
    // dimension is `target_name` per AWS docs.
    genaiDashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'AgentCore Gateway target errors',
        width: 24,
        stacked: true,
        left: [
          new cloudwatch.Metric({
            namespace: 'bedrock-agentcore',
            metricName: 'GatewayTargetInvocationErrors',
            statistic: 'Sum',
            period: cdk.Duration.minutes(1),
          }),
        ],
      })
    );

    // ---------------------------------------------------------------
    // Business Dashboard (Req 5.3) — 4 rows.
    // ---------------------------------------------------------------
    const businessDashboard = new cloudwatch.Dashboard(this, 'BusinessDashboard', {
      dashboardName: `${props.projectName}-business`,
      defaultInterval: cdk.Duration.hours(1),
    });
    this.businessDashboard = businessDashboard;

    // Helper to build a SingleValue widget with sparkline.
    const businessKpiWidget = (
      title: string,
      metricName: string,
      service: string,
      period: cdk.Duration
    ) =>
      new cloudwatch.SingleValueWidget({
        title,
        width: 8,
        sparkline: true,
        period,
        metrics: [
          new cloudwatch.Metric({
            namespace: 'CatDemo',
            metricName,
            dimensionsMap: { service },
            statistic: 'Sum',
            period,
          }),
        ],
      });

    // Row 1 — Feedings rate per minute.
    businessDashboard.addWidgets(
      businessKpiWidget('Feedings created (per minute)', 'FeedingsCreated', 'feeding', cdk.Duration.minutes(1))
    );

    // Row 2 — Health alerts per hour.
    businessDashboard.addWidgets(
      businessKpiWidget('Health alerts read (per hour)', 'HealthAlertsRead', 'health', cdk.Duration.hours(1))
    );

    // Row 3 — Devices commanded per minute.
    businessDashboard.addWidgets(
      businessKpiWidget('Device commands (per minute)', 'DevicesCommanded', 'device', cdk.Duration.minutes(1))
    );

    // Row 4 — per-service breakdown (one line per CatDemo metric).
    const serviceMetric = (metricName: string, service: string, label: string) =>
      new cloudwatch.GraphWidget({
        title: `${label}`,
        width: 6,
        left: [
          new cloudwatch.Metric({
            namespace: 'CatDemo',
            metricName,
            dimensionsMap: { service },
            statistic: 'Sum',
            period: cdk.Duration.minutes(1),
          }),
        ],
      });
    businessDashboard.addWidgets(
      serviceMetric('CatProfilesRead', 'cat-profile', 'cat-profile reads'),
      serviceMetric('FeedingsCreated', 'feeding', 'feeding writes'),
      serviceMetric('DevicesCommanded', 'device', 'device commands'),
      serviceMetric('HealthMetricsRead', 'health', 'health reads')
    );

    // ---------------------------------------------------------------
    // Saved Logs Insights query library (Req 5.4)
    // ---------------------------------------------------------------
    // Query A — All errors for a given trace, across the four Lambdas.
    // ${trace_id} is a Logs Insights template parameter the user fills
    // in at query time.
    const lambdaLogGroups = [
      logs.LogGroup.fromLogGroupName(this, 'CatProfileLogGroup', `/aws/lambda/${fns.catProfile.functionName}`),
      logs.LogGroup.fromLogGroupName(this, 'DeviceLogGroup', `/aws/lambda/${fns.device.functionName}`),
      logs.LogGroup.fromLogGroupName(this, 'FeedingLogGroup', `/aws/lambda/${fns.feeding.functionName}`),
      logs.LogGroup.fromLogGroupName(this, 'HealthLogGroup', `/aws/lambda/${fns.health.functionName}`),
    ];
    const runtimeLogGroups = [
      logs.LogGroup.fromLogGroupName(this, 'LangGraphRuntimeLogGroup', `/aws/bedrock-agentcore/runtimes/${lgRuntime}`),
      logs.LogGroup.fromLogGroupName(this, 'StrandsRuntimeLogGroup', `/aws/bedrock-agentcore/runtimes/${strandsRuntime}`),
    ];

    new logs.QueryDefinition(this, 'QueryAllErrorsForTrace', {
      queryDefinitionName: `${props.projectName}/A-all-errors-for-trace`,
      logGroups: lambdaLogGroups,
      queryString: new logs.QueryString({
        fields: ['@timestamp', '@log', '@message', 'level'],
        filterStatements: [
          "xray_trace_id = '${trace_id}'",
          "level in ['ERROR','WARN']",
        ],
        sort: '@timestamp asc',
      }),
    });

    new logs.QueryDefinition(this, 'QuerySlowestToolCalls', {
      queryDefinitionName: `${props.projectName}/B-slowest-tool-calls`,
      logGroups: runtimeLogGroups,
      queryString: new logs.QueryString({
        fields: ['@timestamp', 'tool_name', 'tool_call_duration_ms'],
        filterStatements: ['ispresent(tool_call_duration_ms)'],
        sort: 'tool_call_duration_ms desc',
        limit: 20,
      }),
    });

    new logs.QueryDefinition(this, 'QueryDdbThrottlesByTable', {
      queryDefinitionName: `${props.projectName}/C-ddb-throttles-by-table`,
      logGroups: lambdaLogGroups,
      queryString: new logs.QueryString({
        fields: ['@timestamp', '@message'],
        filterStatements: ['@message like /ProvisionedThroughputExceededException|ThrottledRequests/'],
        parseStatements: ['@message /TableName=(?<table>[A-Za-z]+)/'],
        statsStatements: ['count() by table'],
      }),
    });

    new logs.QueryDefinition(this, 'QueryInjectedBugMarker', {
      queryDefinitionName: `${props.projectName}/D-injected-bug-marker`,
      logGroups: [...lambdaLogGroups, ...runtimeLogGroups],
      queryString: new logs.QueryString({
        fields: ['@timestamp', '@log', '@message'],
        filterStatements: ['@message like /INJECTED/'],
      }),
    });

    // ---------------------------------------------------------------
    // Phase 4 — SNS topic + alarms (Req 6.1–6.14)
    // ---------------------------------------------------------------
    // Single topic for every alarm. Locked-down access policy: only
    // CloudWatch alarms in this account/region may publish, and the
    // ArnLike on aws:SourceArn prevents a hijacked principal from
    // sending arbitrary messages.
    const alarmTopic = new sns.Topic(this, 'AlarmTopic', {
      topicName: `${props.projectName}-alarms`,
      displayName: 'AIOps cat-demo alarms',
    });

    alarmTopic.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: 'AllowCloudWatchAlarmsOnly',
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal('cloudwatch.amazonaws.com')],
        actions: ['sns:Publish'],
        resources: [alarmTopic.topicArn],
        conditions: {
          ArnLike: {
            'aws:SourceArn': `arn:aws:cloudwatch:${this.region}:${this.account}:alarm:*`,
          },
        },
      })
    );

    if (props.alarmEmail) {
      alarmTopic.addSubscription(new sns_subs.EmailSubscription(props.alarmEmail));
    }

    // Expose the topic ARN for cross-stack references (e.g. Slack integration).
    this.alarmTopicArn = alarmTopic.topicArn;

    const snsAction = new cloudwatch_actions.SnsAction(alarmTopic);
    const projectName = props.projectName;

    // Helper — append to this.alarms so the SRE dashboard's
    // AlarmStatusWidget (created earlier in this constructor with a
    // reference to the array) picks them up at synth time.
    const register = (alarm: cloudwatch.Alarm) => {
      alarm.addAlarmAction(snsAction);
      this.alarms.push(alarm);
      return alarm;
    };

    // 6.1 — (removed) Per-Lambda Duration p99 anomaly-band alarms.
    // These 4 anomaly-detector alarms were the noisiest in the stack:
    // they need ~14 days of baseline to stop flapping and carried low
    // signal for this demo. Per-Lambda p99 latency is still on the SRE
    // dashboard (Row 3) for visual inspection; it just no longer pages.

    // 6.2 — Lambda Errors > 0 per function (×4).
    for (const fn of Object.values(props.lambdas)) {
      register(
        new cloudwatch.Alarm(this, `LambdaErrors_${fn.node.id}`, {
          alarmName: `${projectName}-${fn.functionName}-errors-gt0`,
          alarmDescription: 'Any Lambda error within a 1-minute window',
          metric: fn.metricErrors({ statistic: 'Sum', period: cdk.Duration.minutes(1) }),
          evaluationPeriods: 1,
          threshold: 0,
          comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        })
      );
    }

    // 6.3 — API Gateway 5XXError anomaly (single, account-wide on this
    // API). Per-resource fan-out is in the dashboard widgets; the alarm
    // fires on aggregate to keep the noise floor sane.
    const api5xx = new cloudwatch.Metric({
      namespace: 'AWS/ApiGateway',
      metricName: '5XXError',
      dimensionsMap: { ApiName: apiName },
      statistic: 'Sum',
      period: cdk.Duration.minutes(1),
    });
    register(
      new cloudwatch.Alarm(this, 'ApiGw5xxAnomaly', {
        alarmName: `${projectName}-apigw-5xx-anomaly`,
        alarmDescription: 'API Gateway 5XXError outside the learned anomaly band',
        metric: new cloudwatch.MathExpression({
          expression: 'ANOMALY_DETECTION_BAND(m1, 2)',
          usingMetrics: { m1: api5xx },
          label: '5XXError expected band',
          period: cdk.Duration.minutes(1),
        }),
        evaluationPeriods: 2,
        threshold: 0,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_UPPER_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      })
    );

    // 6.4 — DynamoDB ThrottledRequests > 0 per table (×7).
    for (const table of allTables) {
      register(
        new cloudwatch.Alarm(this, `DdbThrottles_${table.node.id}`, {
          alarmName: `${projectName}-${table.tableName}-throttles-gt0`,
          alarmDescription: 'Any DynamoDB throttle on this table within a 1-minute window',
          metric: new cloudwatch.Metric({
            namespace: 'AWS/DynamoDB',
            metricName: 'ThrottledRequests',
            dimensionsMap: { TableName: table.tableName },
            statistic: 'Sum',
            period: cdk.Duration.minutes(1),
          }),
          evaluationPeriods: 1,
          threshold: 0,
          comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        })
      );
    }

    // 6.5 — Bedrock ThrottlingException > 0 (account-wide). The metric
    // is dimensionless on AWS/Bedrock for the throttle case; if no
    // throttle has ever been seen the alarm sits in INSUFFICIENT_DATA
    // until the first one — that's expected.
    register(
      new cloudwatch.Alarm(this, 'BedrockThrottle', {
        alarmName: `${projectName}-bedrock-throttle-gt0`,
        alarmDescription: 'Bedrock returned a throttling exception',
        metric: new cloudwatch.Metric({
          namespace: 'AWS/Bedrock',
          metricName: 'ThrottlingException',
          statistic: 'Sum',
          period: cdk.Duration.minutes(1),
        }),
        evaluationPeriods: 1,
        threshold: 0,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      })
    );

    // 6.6 — DeviceWriteSuccess BELOW band (the bug-3 silent-swallow
    // detector). Period 5 min so single missing data points don't flap.
    const deviceWriteSuccess = new cloudwatch.Metric({
      namespace: 'CatDemo',
      metricName: 'DeviceWriteSuccess',
      dimensionsMap: { service: 'device' },
      statistic: 'Sum',
      period: cdk.Duration.minutes(5),
    });
    register(
      new cloudwatch.Alarm(this, 'DeviceWriteSuccessBelowBand', {
        alarmName: `${projectName}-device-write-success-below-band`,
        alarmDescription: 'DeviceWriteSuccess fell below the learned anomaly band — silent DDB failure suspected',
        metric: new cloudwatch.MathExpression({
          expression: 'ANOMALY_DETECTION_BAND(m1, 2)',
          usingMetrics: { m1: deviceWriteSuccess },
          label: 'DeviceWriteSuccess expected band',
          period: cdk.Duration.minutes(5),
        }),
        evaluationPeriods: 2,
        threshold: 0,
        comparisonOperator: cloudwatch.ComparisonOperator.LESS_THAN_LOWER_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      })
    );

    // 6.7 — Per-AgentCore-runtime token anomaly (×2).
    for (const runtime of [lgRuntime, strandsRuntime]) {
      const totalTokens = new cloudwatch.MathExpression({
        expression: 'inTok + outTok',
        usingMetrics: {
          inTok: new cloudwatch.Metric({
            namespace: 'bedrock-agentcore',
            metricName: 'InputTokens',
            dimensionsMap: { runtime },
            statistic: 'Sum',
            period: cdk.Duration.minutes(1),
          }),
          outTok: new cloudwatch.Metric({
            namespace: 'bedrock-agentcore',
            metricName: 'OutputTokens',
            dimensionsMap: { runtime },
            statistic: 'Sum',
            period: cdk.Duration.minutes(1),
          }),
        },
        label: 'total tokens',
        period: cdk.Duration.minutes(1),
      });
      register(
        new cloudwatch.Alarm(this, `RuntimeTokenAnomaly_${runtime}`, {
          alarmName: `${projectName}-${runtime}-tokens-anomaly`,
          alarmDescription: `${runtime} token usage outside the learned anomaly band — possible loop`,
          metric: new cloudwatch.MathExpression({
            expression: 'ANOMALY_DETECTION_BAND(m1, 2)',
            usingMetrics: { m1: totalTokens },
            label: 'token band',
            period: cdk.Duration.minutes(1),
          }),
          evaluationPeriods: 2,
          threshold: 0,
          comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_UPPER_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        })
      );
    }

    // 6.8 — Gateway target invocation errors > 0.
    register(
      new cloudwatch.Alarm(this, 'GatewayTargetErrors', {
        alarmName: `${projectName}-gateway-target-errors-gt0`,
        alarmDescription: 'AgentCore Gateway target invocation error',
        metric: new cloudwatch.Metric({
          namespace: 'bedrock-agentcore',
          metricName: 'GatewayTargetInvocationErrors',
          statistic: 'Sum',
          period: cdk.Duration.minutes(1),
        }),
        evaluationPeriods: 1,
        threshold: 0,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      })
    );

    // 6.9 — RUM JS error rate anomaly. The RUM metric is named
    // `JsErrorCount` per page view; we compute (errors / pageViews) and
    // alarm when that ratio leaves the band. Wired only when Phase 5
    // creates the RUM AppMonitor — until then the alarm has no data.
    const rumAppMonitorName = `${projectName}-rum`;
    const rumErrors = new cloudwatch.Metric({
      namespace: 'AWS/RUM',
      metricName: 'JsErrorCount',
      dimensionsMap: { application_name: rumAppMonitorName },
      statistic: 'Sum',
      period: cdk.Duration.minutes(1),
    });
    const rumPageViews = new cloudwatch.Metric({
      namespace: 'AWS/RUM',
      metricName: 'PageViewCount',
      dimensionsMap: { application_name: rumAppMonitorName },
      statistic: 'Sum',
      period: cdk.Duration.minutes(1),
    });
    const rumErrorRate = new cloudwatch.MathExpression({
      // FILL handles the zero-pageview case gracefully.
      expression: 'IF(pv > 0, errs / pv, 0)',
      usingMetrics: { errs: rumErrors, pv: rumPageViews },
      label: 'JS error rate',
      period: cdk.Duration.minutes(1),
    });
    register(
      new cloudwatch.Alarm(this, 'RumJsErrorAnomaly', {
        alarmName: `${projectName}-rum-js-error-rate-anomaly`,
        alarmDescription: 'RUM JS error rate outside the learned anomaly band',
        metric: new cloudwatch.MathExpression({
          expression: 'ANOMALY_DETECTION_BAND(m1, 2)',
          usingMetrics: { m1: rumErrorRate },
          label: 'JS error rate band',
          period: cdk.Duration.minutes(1),
        }),
        evaluationPeriods: 2,
        threshold: 0,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_UPPER_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      })
    );

    // 6.10 — CloudFront 5xxErrorRate > 1% over 5 minutes. Only wired
    // when UiStack passed in the distribution.
    if (props.cloudfrontDistribution) {
      register(
        new cloudwatch.Alarm(this, 'CloudFront5xxRate', {
          alarmName: `${projectName}-cloudfront-5xx-gt1pct`,
          alarmDescription: 'CloudFront 5xx error rate exceeded 1% over 5 minutes',
          metric: new cloudwatch.Metric({
            namespace: 'AWS/CloudFront',
            metricName: '5xxErrorRate',
            // CloudFront metrics live in us-east-1 with global Region
            // dimension on top of DistributionId.
            dimensionsMap: {
              DistributionId: props.cloudfrontDistribution.distributionId,
              Region: 'Global',
            },
            statistic: 'Average',
            period: cdk.Duration.minutes(5),
          }),
          evaluationPeriods: 1,
          threshold: 1.0,
          comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
          treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
        })
      );
    }

    // CfnOutput summarising what was wired so operators can verify in
    // the test account without opening every alarm.
    new cdk.CfnOutput(this, 'AlarmTopicArn', { value: alarmTopic.topicArn });
    new cdk.CfnOutput(this, 'AlarmCount', { value: this.alarms.length.toString() });

    // ---------------------------------------------------------------
    // Phase 6 — CloudWatch Investigations group (Req 8.1, 8.2)
    // ---------------------------------------------------------------
    // Gated by CDK context flag: -c investigationsGa=true
    // While Investigations is in preview, only ephemeral investigations
    // are available. Once GA in us-east-1, flip the flag to create a
    // persistent investigation group with 90-day retention.
    const investigationsGa = this.node.tryGetContext('investigationsGa') === 'true';

    if (investigationsGa) {
      // Note: AWS::CloudWatch::InvestigationGroup is a newer CloudFormation
      // resource type. Using CfnResource as a forward-compatible placeholder
      // that will work once the resource type is registered in the region.
      new cdk.CfnResource(this, 'InvestigationGroup', {
        type: 'AWS::CloudWatch::InvestigationGroup',
        properties: {
          Identifier: `${props.projectName}-investigations`,
          EncryptionConfiguration: { Type: 'AWS_OWNED_KEY' },
          RetentionInDays: 90,
        },
      });

      new cdk.CfnOutput(this, 'InvestigationsMode', {
        value: `persistent (GA); group: ${props.projectName}-investigations`,
      });
    } else {
      new cdk.CfnOutput(this, 'InvestigationsMode', {
        value: 'ephemeral-only (preview); persistent group not created. See CICD.md.',
      });
    }
  }
}

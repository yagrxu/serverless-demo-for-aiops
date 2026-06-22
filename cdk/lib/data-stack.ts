import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';

/**
 * DynamoDB tables for the cat-care demo.
 *
 * One table per bounded context — not single-table design. This keeps
 * each Lambda's IAM surface small and the failure modes easy to reason
 * about during AIOps investigations.
 */
export class DataStack extends cdk.Stack {
  readonly catProfiles: dynamodb.Table;
  readonly catNameIndex: dynamodb.Table;
  readonly devices: dynamodb.Table;
  readonly deviceTelemetry: dynamodb.Table;
  readonly feedingEvents: dynamodb.Table;
  readonly healthMetrics: dynamodb.Table;
  readonly healthAlerts: dynamodb.Table;
  readonly wxUsers: dynamodb.Table;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const common: Partial<dynamodb.TableProps> = {
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.DESTROY, // demo only
    };

    this.catProfiles = new dynamodb.Table(this, 'CatProfiles', {
      ...common,
      partitionKey: { name: 'cat_id', type: dynamodb.AttributeType.STRING },
    });

    this.catNameIndex = new dynamodb.Table(this, 'CatNameIndex', {
      ...common,
      partitionKey: { name: 'name', type: dynamodb.AttributeType.STRING },
    });

    this.devices = new dynamodb.Table(this, 'Devices', {
      ...common,
      partitionKey: { name: 'device_id', type: dynamodb.AttributeType.STRING },
    });
    this.devices.addGlobalSecondaryIndex({
      indexName: 'by-cat',
      partitionKey: { name: 'cat_id', type: dynamodb.AttributeType.STRING },
    });

    this.deviceTelemetry = new dynamodb.Table(this, 'DeviceTelemetry', {
      ...common,
      partitionKey: { name: 'device_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'ts', type: dynamodb.AttributeType.STRING },
      // Phase 4 (Req 6.11) — top-partition + throttle visibility for the
      // hot-partition bug scenario. AccessedAndThrottledKeys captures
      // both heaviest readers/writers and the keys that experienced
      // throttling. Idempotent on redeploy.
      contributorInsightsEnabled: true,
    });

    this.feedingEvents = new dynamodb.Table(this, 'FeedingEvents', {
      ...common,
      partitionKey: { name: 'cat_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'ts', type: dynamodb.AttributeType.STRING },
    });

    this.healthMetrics = new dynamodb.Table(this, 'HealthMetrics', {
      ...common,
      partitionKey: { name: 'cat_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'ts', type: dynamodb.AttributeType.STRING },
      // Phase 4 (Req 6.12) — full-table-scan bug scenario uses this to
      // surface the partition that's being hit hardest.
      contributorInsightsEnabled: true,
    });

    this.healthAlerts = new dynamodb.Table(this, 'HealthAlerts', {
      ...common,
      partitionKey: { name: 'cat_id', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'alert_id', type: dynamodb.AttributeType.STRING },
    });

    this.wxUsers = new dynamodb.Table(this, 'WxUsers', {
      ...common,
      partitionKey: { name: 'openid', type: dynamodb.AttributeType.STRING },
      timeToLiveAttribute: 'ttl',
    });
  }
}

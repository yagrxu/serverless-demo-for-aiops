import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as applicationsignals from 'aws-cdk-lib/aws-applicationsignals';

/**
 * Account/region-scoped observability resources.
 *
 * Currently owns just the CloudWatch Application Signals discovery
 * resource — required exactly once per account+region for the
 * Application Signals Service Map to populate. The stack is the
 * future home for dashboards, alarms, anomaly detectors, the SNS
 * topic, log query definitions, and the Investigations group as
 * subsequent phases land.
 *
 * Transaction Search enablement is intentionally NOT in this stack:
 * it depends on `xray:UpdateTraceSegmentDestination` which has a
 * 10-minute propagation lag and is documented as a one-time
 * operator action in CICD.md. Keeping it out of CDK avoids stack
 * lifecycle coupling to a slow side-effect.
 */
export class ObservabilityStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // CfnDiscovery creates the Application Signals service-linked role
    // and grants the discovery service permission to read X-Ray, Logs,
    // CloudWatch metrics, and tag data. Idempotent; redeploys are no-ops.
    new applicationsignals.CfnDiscovery(this, 'ApplicationSignalsDiscovery', {});
  }
}

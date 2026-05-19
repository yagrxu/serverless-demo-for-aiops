import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';

/**
 * Region-portable wiring for CloudWatch Application Signals on Lambda.
 *
 * AWS publishes the AWSOpenTelemetryDistroPython layer in every region but
 * the publisher account ID and version vary. This file is the single
 * place we maintain the table.
 *
 * Source: https://aws-otel.github.io/docs/getting-started/lambda
 * (section "AWS Lambda Layer for OpenTelemetry ARNs", Python tab).
 *
 * Update versions by re-checking that page; the helper falls back to a
 * conservative version when the deployment region is not yet listed,
 * which still works as long as the publisher account ID is correct.
 */

interface AdotLayerInfo {
  /** AWS account ID that publishes the layer in this region. */
  account: string;
  /** Latest published layer version we've checked. */
  version: number;
}

// As of 2026-05. The map is exhaustive enough for the regions we
// realistically deploy to. If a CI run targets a region not in this
// map, deployment fails fast with a clear message — better than
// silently producing a broken ARN.
const ADOT_PYTHON_LAYERS: Record<string, AdotLayerInfo> = {
  // Most-used regions (publisher 615299751070)
  'us-east-1':      { account: '615299751070', version: 25 },
  'us-east-2':      { account: '615299751070', version: 22 },
  'us-west-1':      { account: '615299751070', version: 29 },
  'us-west-2':      { account: '615299751070', version: 29 },
  'ca-central-1':   { account: '615299751070', version: 22 },
  'sa-east-1':      { account: '615299751070', version: 22 },
  'eu-west-1':      { account: '615299751070', version: 22 },
  'eu-west-2':      { account: '615299751070', version: 22 },
  'eu-west-3':      { account: '615299751070', version: 22 },
  'eu-north-1':     { account: '615299751070', version: 22 },
  'eu-central-1':   { account: '615299751070', version: 22 },
  'ap-northeast-1': { account: '615299751070', version: 22 },
  'ap-northeast-2': { account: '615299751070', version: 22 },
  'ap-south-1':     { account: '615299751070', version: 22 },
  'ap-southeast-1': { account: '615299751070', version: 21 },
  'ap-southeast-2': { account: '615299751070', version: 22 },
  'ap-northeast-3': { account: '615299751070', version: 21 },

  // Regions with their own publisher accounts
  'af-south-1':     { account: '904233096616', version: 19 },
  'ap-east-1':      { account: '888577020596', version: 19 },
  'ap-south-2':     { account: '796973505492', version: 19 },
  'ap-southeast-3': { account: '039612877180', version: 19 },
  'ap-southeast-4': { account: '713881805771', version: 19 },
  'ap-southeast-5': { account: '152034782359', version: 10 },
  'ap-southeast-7': { account: '980416031188', version: 10 },
  'ca-west-1':      { account: '595944127152', version: 10 },
  'eu-central-2':   { account: '156041407956', version: 19 },
  'eu-south-1':     { account: '257394471194', version: 19 },
  'eu-south-2':     { account: '490004653786', version: 19 },
  'il-central-1':   { account: '746669239226', version: 19 },
  'me-central-1':   { account: '739275441131', version: 19 },
  'me-south-1':     { account: '980921751758', version: 19 },
  'mx-central-1':   { account: '610118373846', version: 10 },

  // China partition
  'cn-north-1':     { account: '440179912924', version: 10 },
  'cn-northwest-1': { account: '440180067931', version: 10 },
};

const APPLICATION_SIGNALS_MANAGED_POLICY =
  'CloudWatchLambdaApplicationSignalsExecutionRolePolicy';

/**
 * Compute the AWS-published ADOT Python layer ARN for a given region.
 *
 * Throws at synth time if the region is not in our table — better to
 * fail fast than to silently mint a garbage ARN.
 */
export function adotPythonLayerArn(region: string): string {
  const info = ADOT_PYTHON_LAYERS[region];
  if (!info) {
    throw new Error(
      `[observability] No ADOT Python layer ARN configured for region "${region}". ` +
      `Update cdk/lib/observability.ts with the entry from ` +
      `https://aws-otel.github.io/docs/getting-started/lambda`,
    );
  }
  // China uses aws-cn partition; everything else uses aws.
  const partition = region.startsWith('cn-') ? 'aws-cn' : 'aws';
  return `arn:${partition}:lambda:${region}:${info.account}:layer:AWSOpenTelemetryDistroPython:${info.version}`;
}

/**
 * Wire CloudWatch Application Signals onto a Lambda function:
 *
 *  1. Attach the region-matched AWSOpenTelemetryDistroPython layer.
 *  2. Set AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument so the layer
 *     auto-instruments the handler.
 *  3. Attach the managed IAM policy that grants the function permission
 *     to send Application Signals data.
 *
 * The companion `enableApplicationSignalsDiscovery(scope)` should be
 * called exactly once per account/region (typically from an
 * Observability_Stack) so the Application Signals service-linked role
 * is created.
 */
export function applyApplicationSignalsToLambda(fn: lambda.Function): void {
  const region = cdk.Stack.of(fn).region;
  fn.addLayers(
    lambda.LayerVersion.fromLayerVersionArn(
      fn,
      'AdotPythonLayer',
      adotPythonLayerArn(region),
    ),
  );
  fn.addEnvironment('AWS_LAMBDA_EXEC_WRAPPER', '/opt/otel-instrument');
  if (fn.role) {
    fn.role.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName(
        APPLICATION_SIGNALS_MANAGED_POLICY,
      ),
    );
  }
}

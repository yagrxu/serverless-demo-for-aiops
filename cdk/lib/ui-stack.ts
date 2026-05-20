import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as rum from 'aws-cdk-lib/aws-rum';
import * as path from 'path';
import * as fs from 'fs';

export interface UiStackProps extends cdk.StackProps {
  bundles: { name: string; path: string }[]; // path is relative to cdk/
  apiUrl: string;
  /** When provided, the default CloudFront behavior routes to App Runner instead of S3. */
  appRunnerServiceUrl?: string;
  /** Project name used for resource naming (e.g. 'aiops-cat-demo'). */
  projectName?: string;
}

/**
 * Static hosting for the React UIs (device-simulator, admin-console)
 * fronted by CloudFront + OAC. When an App Runner service URL is
 * provided, the chatbot is served from App Runner as the default
 * origin and the static UIs are served under path-based behaviors.
 *
 * Path routing:
 *   /                  -> App Runner (chatbot) or S3 (fallback)
 *   /device-simulator  -> S3
 *   /admin-console     -> S3
 *   /api/*             -> App Runner (no caching)
 *
 * UI bundles are built out-of-band (`npm run build` in each ui/<name>/)
 * and picked up from ui/<name>/dist. If a bundle is missing, the stack
 * falls back to a tiny placeholder so `cdk synth` still works.
 */
export class UiStack extends cdk.Stack {
  // Exposed so the Observability_Stack can build the CloudFront 5xx
  // alarm (Phase 4) and the Origin Request Policy attachment (Phase 5)
  // against the same distribution this stack created.
  public readonly distribution: cloudfront.Distribution;

  constructor(scope: Construct, id: string, props: UiStackProps) {
    super(scope, id, props);

    const bucket = new s3.Bucket(this, 'UiBucket', {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true, // demo only
      enforceSSL: true,
    });

    const s3Origin = origins.S3BucketOrigin.withOriginAccessControl(bucket);

    // --- Build the distribution based on whether App Runner is available ---
    let distribution: cloudfront.Distribution;

    if (props.appRunnerServiceUrl) {
      // App Runner is the default origin (chatbot). S3 serves static UIs.
      const appRunnerOrigin = new origins.HttpOrigin(props.appRunnerServiceUrl, {
        protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
      });

      // No-cache policy for dynamic App Runner content
      const noCachePolicy = new cloudfront.CachePolicy(this, 'NoCachePolicy', {
        cachePolicyName: 'aiops-cat-demo-no-cache',
        defaultTtl: cdk.Duration.seconds(0),
        minTtl: cdk.Duration.seconds(0),
        maxTtl: cdk.Duration.seconds(0),
      });

      distribution = new cloudfront.Distribution(this, 'UiDistribution', {
        defaultBehavior: {
          origin: appRunnerOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: noCachePolicy,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        },
        additionalBehaviors: {
          '/device-simulator/*': {
            origin: s3Origin,
            viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
          },
          '/admin-console/*': {
            origin: s3Origin,
            viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
          },
        },
      });
    } else {
      // Fallback: all UIs from S3 (original behavior)
      distribution = new cloudfront.Distribution(this, 'UiDistribution', {
        defaultRootObject: 'index.html',
        defaultBehavior: {
          origin: s3Origin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        },
        errorResponses: [
          { httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html' },
          { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html' },
        ],
      });
    }

    // Expose the constructed distribution for cross-stack consumers
    // (Observability_Stack alarms + Phase 5 Origin Request Policy).
    this.distribution = distribution;

    // --- RUM App Monitor + Origin Request Policy (Phase 5) ---
    // Guarded by CDK context flag: -c rumEnabled=true
    const rumEnabled = this.node.tryGetContext('rumEnabled') === 'true';
    const projectName = props.projectName || 'aiops-cat-demo';

    if (rumEnabled) {
      // Cognito Identity Pool for unauthenticated RUM access
      const rumIdentityPool = new cognito.CfnIdentityPool(this, 'RumIdentityPool', {
        identityPoolName: `${projectName}-rum-identity-pool`,
        allowUnauthenticatedIdentities: true,
      });

      // IAM role for unauthenticated RUM guests
      const rumGuestRole = new iam.Role(this, 'RumGuestRole', {
        assumedBy: new iam.FederatedPrincipal(
          'cognito-identity.amazonaws.com',
          {
            StringEquals: {
              'cognito-identity.amazonaws.com:aud': rumIdentityPool.ref,
            },
            'ForAnyValue:StringLike': {
              'cognito-identity.amazonaws.com:amr': 'unauthenticated',
            },
          },
          'sts:AssumeRoleWithWebIdentity',
        ),
      });

      rumGuestRole.addToPolicy(new iam.PolicyStatement({
        actions: ['rum:PutRumEvents'],
        resources: [
          cdk.Arn.format({
            service: 'rum',
            resource: 'appmonitor',
            resourceName: `${projectName}-rum`,
          }, this),
        ],
      }));

      // Attach the role to the identity pool
      new cognito.CfnIdentityPoolRoleAttachment(this, 'RumIdentityPoolRoles', {
        identityPoolId: rumIdentityPool.ref,
        roles: {
          unauthenticated: rumGuestRole.roleArn,
        },
      });

      // CloudWatch RUM App Monitor
      const appMonitor = new rum.CfnAppMonitor(this, 'CatDemoRumMonitor', {
        name: `${projectName}-rum`,
        domain: distribution.distributionDomainName,
        cwLogEnabled: true,
        appMonitorConfiguration: {
          allowCookies: false,
          enableXRay: true,
          sessionSampleRate: 1.0,
          telemetries: ['errors', 'performance', 'http'],
          identityPoolId: rumIdentityPool.ref,
          guestRoleArn: rumGuestRole.roleArn,
        },
      });

      // CfnOutputs for UI build consumption
      new cdk.CfnOutput(this, 'RumAppMonitorId', { value: appMonitor.attrId });
      new cdk.CfnOutput(this, 'RumIdentityPoolId', { value: rumIdentityPool.ref });
      new cdk.CfnOutput(this, 'RumGuestRoleArn', { value: rumGuestRole.roleArn });
      new cdk.CfnOutput(this, 'RumRegion', { value: this.region });
    }

    // --- Origin Request Policy for trace correlation headers ---
    // Forwards traceparent, X-Amzn-Trace-Id, and Session-Id headers
    // from the browser through CloudFront to all origins.
    // Behaviors that already use ALL_VIEWER (e.g. App Runner default)
    // inherently forward these headers, so we only patch behaviors
    // that lack an origin request policy.
    const correlationHeadersPolicy = new cloudfront.OriginRequestPolicy(this, 'CorrelationHeadersPolicy', {
      originRequestPolicyName: `${projectName}-correlation-headers`,
      headerBehavior: cloudfront.OriginRequestHeaderBehavior.allowList(
        'traceparent',
        'X-Amzn-Trace-Id',
        'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id',
      ),
    });

    // Attach the origin request policy to behaviors on the distribution.
    // The L2 Distribution construct doesn't support post-hoc modification,
    // so we use addPropertyOverride on the CfnDistribution.
    const cfnDistribution = distribution.node.defaultChild as cloudfront.CfnDistribution;

    if (props.appRunnerServiceUrl) {
      // App Runner default behavior already uses ALL_VIEWER which forwards
      // all headers. Only patch the S3 additional behaviors.
      cfnDistribution.addPropertyOverride(
        'DistributionConfig.CacheBehaviors.0.OriginRequestPolicyId',
        correlationHeadersPolicy.originRequestPolicyId,
      );
      cfnDistribution.addPropertyOverride(
        'DistributionConfig.CacheBehaviors.1.OriginRequestPolicyId',
        correlationHeadersPolicy.originRequestPolicyId,
      );
    } else {
      // S3-only fallback: patch the default behavior
      cfnDistribution.addPropertyOverride(
        'DistributionConfig.DefaultCacheBehavior.OriginRequestPolicyId',
        correlationHeadersPolicy.originRequestPolicyId,
      );
    }

    // Deploy each bundle under its own prefix. Generate a placeholder
    // if the bundle directory doesn't exist yet so synth won't explode.
    const placeholderDir = path.join(__dirname, '../.ui-placeholder');
    if (!fs.existsSync(placeholderDir)) {
      fs.mkdirSync(placeholderDir, { recursive: true });
      fs.writeFileSync(
        path.join(placeholderDir, 'index.html'),
        `<!doctype html><html><body><h1>UI not built yet</h1>
<p>Run the per-UI build under ui/ and redeploy.</p></body></html>`
      );
    }

    // When App Runner is serving the chatbot, skip deploying chatbot to S3
    const bundlesToDeploy = props.appRunnerServiceUrl
      ? props.bundles.filter(b => b.name !== 'chatbot')
      : props.bundles;

    for (const b of bundlesToDeploy) {
      const absPath = path.join(__dirname, '..', b.path);
      const source = fs.existsSync(absPath)
        ? s3deploy.Source.asset(absPath)
        : s3deploy.Source.asset(placeholderDir);

      new s3deploy.BucketDeployment(this, `Deploy_${b.name}`, {
        sources: [source],
        destinationBucket: bucket,
        destinationKeyPrefix: b.name === 'chatbot' ? '' : b.name,
        distribution,
        distributionPaths: [b.name === 'chatbot' ? '/*' : `/${b.name}/*`],
        prune: false,
      });
    }

    new cdk.CfnOutput(this, 'UiUrl', {
      value: `https://${distribution.distributionDomainName}`,
    });
    new cdk.CfnOutput(this, 'ApiUrlRef', { value: props.apiUrl });
  }
}

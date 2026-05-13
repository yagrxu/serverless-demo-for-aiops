import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as path from 'path';
import * as fs from 'fs';

export interface UiStackProps extends cdk.StackProps {
  bundles: { name: string; path: string }[]; // path is relative to cdk/
  apiUrl: string;
  /** When provided, the default CloudFront behavior routes to App Runner instead of S3. */
  appRunnerServiceUrl?: string;
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

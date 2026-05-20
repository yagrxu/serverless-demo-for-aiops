/**
 * CloudWatch RUM bootstrap module.
 * Import this at the top of each UI app's entry point to enable RUM.
 * In local dev (env vars unset), this is a no-op.
 */
import { AwsRum, AwsRumConfig } from 'aws-rum-web';

const RUM_APP_MONITOR_ID = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_RUM_APP_MONITOR_ID) || '';
const RUM_IDENTITY_POOL_ID = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_RUM_IDENTITY_POOL_ID) || '';
const RUM_REGION = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_RUM_REGION) || 'us-east-1';

let rum: AwsRum | null = null;

export function initRum(): AwsRum | null {
  if (!RUM_APP_MONITOR_ID || !RUM_IDENTITY_POOL_ID) {
    // Local dev — RUM env vars not set, skip initialization
    return null;
  }

  if (rum) return rum;

  try {
    const config: AwsRumConfig = {
      sessionSampleRate: 1,
      identityPoolId: RUM_IDENTITY_POOL_ID,
      endpoint: `https://dataplane.rum.${RUM_REGION}.amazonaws.com`,
      telemetries: ['errors', 'performance', 'http'],
      allowCookies: false,
      enableXRay: true,
    };

    rum = new AwsRum(RUM_APP_MONITOR_ID, '1.0.0', RUM_REGION, config);
    return rum;
  } catch (err) {
    console.warn('[RUM] Failed to initialize:', err);
    return null;
  }
}

/**
 * Record a custom RUM event when a correlation header could not be
 * attached to an outgoing request. No-ops when RUM is not initialized.
 */
export function recordCorrelationAttachFailure(headerName: string): void {
  rum?.recordEvent('CorrelationHeaderAttachFailure', { headerName });
}

export { rum };

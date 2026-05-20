/**
 * CloudWatch RUM bootstrap module for the chatbot (Next.js).
 * Import this at the top of the app layout to enable RUM.
 * In local dev (env vars unset), this is a no-op.
 *
 * Uses NEXT_PUBLIC_ env vars instead of VITE_ since the chatbot
 * is built with Next.js, not Vite.
 */
'use client';
import { AwsRum, AwsRumConfig } from 'aws-rum-web';

const RUM_APP_MONITOR_ID = process.env.NEXT_PUBLIC_RUM_APP_MONITOR_ID || '';
const RUM_IDENTITY_POOL_ID = process.env.NEXT_PUBLIC_RUM_IDENTITY_POOL_ID || '';
const RUM_REGION = process.env.NEXT_PUBLIC_RUM_REGION || 'us-east-1';

let rum: AwsRum | null = null;

export function initRum(): AwsRum | null {
  if (typeof window === 'undefined') {
    // Server-side — RUM is browser-only
    return null;
  }

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

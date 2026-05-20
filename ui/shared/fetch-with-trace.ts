/**
 * Fetch wrapper that attaches trace correlation headers.
 * Falls back gracefully if headers can't be attached.
 */

/**
 * Generate a W3C traceparent header value.
 * Format: version-traceId-parentId-flags
 */
function generateTraceparent(): string {
  const traceId = Array.from(crypto.getRandomValues(new Uint8Array(16))).map(b => b.toString(16).padStart(2, '0')).join('');
  const parentId = Array.from(crypto.getRandomValues(new Uint8Array(8))).map(b => b.toString(16).padStart(2, '0')).join('');
  return `00-${traceId}-${parentId}-01`;
}

/**
 * Fetch with trace correlation headers attached.
 * If header attachment fails, the request proceeds without them and
 * a warning is logged (CorrelationHeaderAttachFailure path).
 */
export async function fetchWithTrace(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  try {
    if (!headers.has('traceparent')) { headers.set('traceparent', generateTraceparent()); }
  } catch { console.warn('[Trace] Failed to attach correlation headers'); }
  return fetch(input, { ...init, headers });
}

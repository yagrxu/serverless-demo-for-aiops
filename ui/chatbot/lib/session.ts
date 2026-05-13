/**
 * AgentCore Runtime Session ID helper (browser-only).
 *
 * The session ID is stable for the lifetime of a browser session and is
 * persisted in localStorage. The chatbot forwards it to the BFF as an
 * HTTP header, which then passes it to `InvokeAgentRuntime` so every
 * span emitted by either agent carries a `session.id` attribute.
 *
 * See docs/architecture.md and .kiro/specs/observability/design.md.
 */
const STORAGE_KEY = 'rumSessionId';
export const SESSION_HEADER = 'x-amzn-bedrock-agentcore-runtime-session-id';

export function getSessionId(): string {
  if (typeof window === 'undefined') {
    // Running on the server during SSR — should not happen for this helper.
    throw new Error('getSessionId must be called in the browser');
  }

  let id = window.localStorage.getItem(STORAGE_KEY);
  if (!id) {
    id = window.crypto.randomUUID();
    window.localStorage.setItem(STORAGE_KEY, id);
  }
  return id;
}

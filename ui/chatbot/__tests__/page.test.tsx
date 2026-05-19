/**
 * Baseline test for ui/chatbot — validates the test framework is wired up
 * and exercises the session utility from lib/session.ts.
 */
import { getSessionId, SESSION_HEADER } from '@/lib/session';

const MOCK_UUID = '550e8400-e29b-41d4-a716-446655440000';

describe('lib/session', () => {
  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(window, 'crypto', {
      value: { randomUUID: () => MOCK_UUID },
      writable: true,
    });
  });

  it('returns a UUID session ID and persists it in localStorage', () => {
    const id = getSessionId();

    expect(id).toBe(MOCK_UUID);

    // Should persist in localStorage
    expect(window.localStorage.getItem('rumSessionId')).toBe(MOCK_UUID);
  });

  it('returns the same session ID on subsequent calls', () => {
    const first = getSessionId();
    const second = getSessionId();

    expect(second).toBe(first);
  });

  it('exports the expected SESSION_HEADER constant', () => {
    expect(SESSION_HEADER).toBe('x-amzn-bedrock-agentcore-runtime-session-id');
  });
});

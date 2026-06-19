const JWT_SECRET = process.env.WX_JWT_SECRET || 'dev-secret-change-me';

export interface WxSession {
  openid: string;
  iat: number;
  exp: number;
}

/** Verify and decode a JWT from the Authorization header. Returns null if invalid. */
export async function verifyWxToken(request: Request): Promise<WxSession | null> {
  const auth = request.headers.get('Authorization');
  if (!auth?.startsWith('Bearer ')) return null;

  const token = auth.slice(7);
  const parts = token.split('.');
  if (parts.length !== 3) return null;

  try {
    const [headerB64, payloadB64, sigB64] = parts;
    const unsigned = `${headerB64}.${payloadB64}`;

    const key = await crypto.subtle.importKey(
      'raw',
      new TextEncoder().encode(JWT_SECRET),
      { name: 'HMAC', hash: 'SHA-256' },
      false,
      ['verify'],
    );
    const sig = Buffer.from(sigB64, 'base64url');
    const valid = await crypto.subtle.verify(
      'HMAC',
      key,
      sig,
      new TextEncoder().encode(unsigned),
    );
    if (!valid) return null;

    const payload = JSON.parse(Buffer.from(payloadB64, 'base64url').toString()) as WxSession;
    if (payload.exp && payload.exp < Math.floor(Date.now() / 1000)) return null;

    return payload;
  } catch {
    return null;
  }
}

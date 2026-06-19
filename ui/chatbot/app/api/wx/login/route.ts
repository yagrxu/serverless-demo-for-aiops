import { NextResponse } from 'next/server';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, PutCommand } from '@aws-sdk/lib-dynamodb';

const WX_APPID = process.env.WX_APPID || '';
const WX_SECRET = process.env.WX_SECRET || '';
const JWT_SECRET = process.env.WX_JWT_SECRET || 'dev-secret-change-me';
const WX_USERS_TABLE = process.env.WX_USERS_TABLE || 'WxUsers';
const TTL_DAYS = 30;

const ddb = DynamoDBDocumentClient.from(
  new DynamoDBClient({ region: process.env.AWS_REGION || 'us-east-1' }),
);

/**
 * POST /api/wx/login
 * Body: { code: string }
 * Returns: { token: string, openid: string }
 *
 * Exchanges WeChat login code for openid via code2session,
 * stores/updates the user record, and returns a signed JWT.
 */
export async function POST(request: Request) {
  let body: { code?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const { code } = body;
  if (!code) {
    return NextResponse.json({ error: 'code is required' }, { status: 400 });
  }

  // Exchange code for openid via WeChat API
  let openid: string;
  let sessionKey: string;

  if (process.env.LOCAL_MODE === 'true') {
    // In local dev, skip WeChat API and use code as openid
    openid = `dev_${code}`;
    sessionKey = 'dev-session-key';
  } else {
    const wxUrl = `https://api.weixin.qq.com/sns/jscode2session?appid=${WX_APPID}&secret=${WX_SECRET}&js_code=${code}&grant_type=authorization_code`;
    const wxRes = await fetch(wxUrl);
    const wxData = await wxRes.json();

    if (wxData.errcode) {
      return NextResponse.json(
        { error: `WeChat error: ${wxData.errmsg}` },
        { status: 401 },
      );
    }
    openid = wxData.openid;
    sessionKey = wxData.session_key;
  }

  // Upsert WxUsers record
  const now = Date.now();
  const ttl = Math.floor(now / 1000) + TTL_DAYS * 86400;
  await ddb.send(new PutCommand({
    TableName: WX_USERS_TABLE,
    Item: {
      openid,
      last_active: new Date(now).toISOString(),
      ttl,
    },
  }));

  // Mint a simple JWT (HS256)
  const token = await mintJwt({ openid, iat: Math.floor(now / 1000), exp: ttl });

  return NextResponse.json({ token, openid });
}

/** Minimal HMAC-SHA256 JWT without external deps */
async function mintJwt(payload: Record<string, unknown>): Promise<string> {
  const header = { alg: 'HS256', typ: 'JWT' };
  const enc = (obj: unknown) =>
    Buffer.from(JSON.stringify(obj)).toString('base64url');
  const unsigned = `${enc(header)}.${enc(payload)}`;
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(JWT_SECRET),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(unsigned));
  return `${unsigned}.${Buffer.from(sig).toString('base64url')}`;
}

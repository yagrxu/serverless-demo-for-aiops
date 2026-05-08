import { NextResponse } from 'next/server';
import { getAppConfig } from '@/lib/agent-client';

export async function GET() {
  const config = getAppConfig();
  return NextResponse.json({
    status: 'ok',
    mode: config.localMode ? 'local' : 'production',
    timestamp: new Date().toISOString(),
  });
}

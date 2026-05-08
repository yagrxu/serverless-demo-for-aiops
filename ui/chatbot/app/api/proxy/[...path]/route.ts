import { NextResponse } from 'next/server';

/**
 * API proxy — forwards requests to the REST API (API Gateway in production,
 * local API shim in development). This allows all UIs to use relative paths
 * like `/api/proxy/cats` without knowing the API Gateway URL.
 */

const API_URL = process.env.API_URL || 'http://localhost:8000';

export async function GET(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const apiPath = '/' + path.join('/');
  const url = new URL(request.url);
  const queryString = url.search;

  const res = await fetch(`${API_URL}${apiPath}${queryString}`, {
    headers: { 'Content-Type': 'application/json' },
  });

  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export async function POST(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const apiPath = '/' + path.join('/');
  const reqBody = await request.text();

  const res = await fetch(`${API_URL}${apiPath}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: reqBody,
  });

  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { 'Content-Type': 'application/json' },
  });
}

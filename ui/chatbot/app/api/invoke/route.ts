import { NextResponse } from 'next/server';
import { invokeAgent, getAppConfig } from '@/lib/agent-client';

interface InvokeRequest {
  message: string;
  agent: 'langgraph' | 'strands' | 'both';
}

interface InvokeResponse {
  langgraph?: string;
  strands?: string;
  error?: string;
}

const SESSION_HEADER = 'x-amzn-bedrock-agentcore-runtime-session-id';

export async function POST(request: Request) {
  // Session ID is required — it's what the AgentCore Runtime uses as the
  // OTel baggage session.id attribute. Missing header means the client
  // isn't initialized correctly, so fail fast.
  const sessionId = request.headers.get(SESSION_HEADER);
  if (!sessionId) {
    return NextResponse.json(
      { error: 'missing session id header' },
      { status: 400 },
    );
  }

  // Validate request body
  let body: any;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'Invalid JSON' }, { status: 400 });
  }

  const { message, agent } = body as Partial<InvokeRequest>;

  if (!message || typeof message !== 'string' || message.trim() === '') {
    return NextResponse.json({ error: 'message is required' }, { status: 400 });
  }
  if (message.length > 4096) {
    return NextResponse.json({ error: 'message exceeds 4096 characters' }, { status: 400 });
  }
  if (!agent || !['langgraph', 'strands', 'both'].includes(agent)) {
    return NextResponse.json({ error: 'agent must be langgraph, strands, or both' }, { status: 400 });
  }

  const config = getAppConfig();
  const response: InvokeResponse = {};
  const promises: Promise<void>[] = [];

  if (agent === 'langgraph' || agent === 'both') {
    promises.push(
      invokeAgent('langgraph', message, config, sessionId)
        .then(text => { response.langgraph = text; })
        .catch(err => { response.langgraph = `Error: ${err.message}`; })
    );
  }

  if (agent === 'strands' || agent === 'both') {
    promises.push(
      invokeAgent('strands', message, config, sessionId)
        .then(text => { response.strands = text; })
        .catch(err => { response.strands = `Error: ${err.message}`; })
    );
  }

  await Promise.all(promises);
  return NextResponse.json(response);
}

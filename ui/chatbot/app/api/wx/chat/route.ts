import { verifyWxToken } from '@/lib/wx-auth';
import { getAppConfig } from '@/lib/agent-client';

const DEFAULT_FRAMEWORK = process.env.WX_AGENT_FRAMEWORK || 'strands';

/**
 * POST /api/wx/chat
 * Body: { message: string, cat_id: string, session_id?: string }
 * Auth: Bearer <jwt>
 * Returns: SSE stream of agent tokens
 *
 * The mini program uses wx.request with enableChunked:true to consume SSE.
 */
export async function POST(request: Request) {
  const session = await verifyWxToken(request);
  if (!session) {
    return new Response(JSON.stringify({ error: 'Unauthorized' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  let body: { message?: string; cat_id?: string; session_id?: string };
  try {
    body = await request.json();
  } catch {
    return new Response(JSON.stringify({ error: 'Invalid JSON' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const { message, cat_id, session_id } = body;
  if (!message || !cat_id) {
    return new Response(JSON.stringify({ error: 'message and cat_id required' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const config = getAppConfig();
  const agentSessionId = session_id || `wx_${session.openid}_${Date.now()}`;
  const framework = DEFAULT_FRAMEWORK as 'langgraph' | 'strands';

  // Prepend cat context to message
  const enrichedMessage = `[当前猫咪ID: ${cat_id}] ${message}`;

  // Call the agent and stream back via SSE
  const agentUrl = framework === 'langgraph' ? config.langgraphUrl : config.strandsUrl;

  const stream = new ReadableStream({
    async start(controller) {
      const encoder = new TextEncoder();
      const send = (event: string, data: string) => {
        controller.enqueue(encoder.encode(`event: ${event}\ndata: ${data}\n\n`));
      };

      try {
        if (config.localMode) {
          // Local mode: non-streaming call, send result as one chunk
          const res = await fetch(`${agentUrl}/invocations`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': agentSessionId,
            },
            body: JSON.stringify({ input: { message: enrichedMessage }, sessionId: agentSessionId }),
          });

          if (!res.ok) {
            send('error', JSON.stringify({ error: `Agent returned ${res.status}` }));
            controller.close();
            return;
          }

          const resBody = await res.json();
          const text = resBody.response ?? JSON.stringify(resBody);
          // Simulate streaming by chunking the response
          const chunkSize = 20;
          for (let i = 0; i < text.length; i += chunkSize) {
            send('token', JSON.stringify({ content: text.slice(i, i + chunkSize) }));
          }
        } else {
          // Production: call AgentCore Runtime (non-streaming for now, chunk the response)
          const { invokeAgent } = await import('@/lib/agent-client');
          const text = await invokeAgent(framework, enrichedMessage, config, agentSessionId);
          const chunkSize = 20;
          for (let i = 0; i < text.length; i += chunkSize) {
            send('token', JSON.stringify({ content: text.slice(i, i + chunkSize) }));
          }
        }

        send('done', JSON.stringify({ session_id: agentSessionId }));
      } catch (err: any) {
        send('error', JSON.stringify({ error: err.message }));
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}

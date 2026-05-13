export interface AppConfig {
  localMode: boolean;
  langgraphUrl: string;
  strandsUrl: string;
  langgraphRuntimeArn: string;
  strandsRuntimeArn: string;
  awsRegion: string;
}

export function getAppConfig(): AppConfig {
  return {
    localMode: process.env.LOCAL_MODE === 'true',
    langgraphUrl: process.env.LANGGRAPH_URL || 'http://localhost:8081',
    strandsUrl: process.env.STRANDS_URL || 'http://localhost:8082',
    langgraphRuntimeArn: process.env.LANGGRAPH_RUNTIME_ARN || '',
    strandsRuntimeArn: process.env.STRANDS_RUNTIME_ARN || '',
    awsRegion: process.env.AWS_REGION || 'us-east-1',
  };
}

export async function invokeAgent(
  agent: 'langgraph' | 'strands',
  message: string,
  config: AppConfig,
  sessionId: string,
): Promise<string> {
  if (config.localMode) {
    const url = agent === 'langgraph' ? config.langgraphUrl : config.strandsUrl;
    return invokeLocal(url, message, sessionId);
  } else {
    const arn = agent === 'langgraph' ? config.langgraphRuntimeArn : config.strandsRuntimeArn;
    return invokeRuntime(arn, message, sessionId, config.awsRegion);
  }
}

async function invokeLocal(url: string, message: string, sessionId: string): Promise<string> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);

  try {
    const res = await fetch(`${url}/invocations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': sessionId,
      },
      body: JSON.stringify({ input: { message } }),
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new Error(`Agent returned ${res.status}`);
    }

    const body = await res.json();
    return body.response ?? JSON.stringify(body, null, 2);
  } catch (err: any) {
    if (err.name === 'AbortError') {
      throw new Error('Request timed out after 30s');
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

async function invokeRuntime(
  arn: string,
  message: string,
  sessionId: string,
  region: string,
): Promise<string> {
  // AgentCore Runtime is invoked via a SigV4-signed HTTP POST to:
  // POST /runtimes/{agentRuntimeArn}/invocations
  // The session id header is passed through so AgentCore stamps every
  // OTel span with `session.id`.
  const { SignatureV4 } = await import('@smithy/signature-v4');
  const { Sha256 } = await import('@aws-crypto/sha256-js');
  const { defaultProvider } = await import('@aws-sdk/credential-provider-node');
  const { HttpRequest } = await import('@smithy/protocol-http');

  const encodedArn = encodeURIComponent(arn);
  const hostname = `bedrock-agentcore.${region}.amazonaws.com`;
  const path = `/runtimes/${encodedArn}/invocations`;
  const payload = JSON.stringify({ input: { message } });

  const request = new HttpRequest({
    method: 'POST',
    protocol: 'https:',
    hostname,
    path,
    headers: {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': sessionId,
      host: hostname,
    },
    body: payload,
  });

  const signer = new SignatureV4({
    credentials: defaultProvider(),
    region,
    service: 'bedrock-agentcore',
    sha256: Sha256,
  });

  const signed = await signer.sign(request);

  const url = `https://${hostname}${path}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: signed.headers as Record<string, string>,
    body: payload,
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`AgentCore Runtime returned ${res.status}: ${errText}`);
  }

  const body = await res.json();
  return body.response ?? body.output ?? JSON.stringify(body, null, 2);
}

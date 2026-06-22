"""Strands agent for the cat-care demo.

Uses the Strands Agent class with BedrockModel and MCP client tools loaded
dynamically from the MCP Server. The MCP client and Agent are constructed
**per request** so that the OTel context active during the request handler
is propagated into the MCPClient background thread (Strands uses
`contextvars.copy_context()` at `start()` time — see Strands SDK
mcp_client.py). Constructing the client at module import made the
background thread's context snapshot useless, which produced an orphan
trace for every gateway call.

OTel tracing is provided by `opentelemetry-instrument` which wraps the
process via the Dockerfile CMD. No manual TracerProvider setup here.
"""

import tracing_extras  # noqa: F401 — attaches CodeMetadataSpanProcessor, no-op without OTel

import asyncio
import json
import os
from pathlib import Path

import boto3
from botocore.credentials import Credentials
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel
from strands import Agent
from strands.models.bedrock import BedrockModel
from strands.tools.mcp import MCPClient

from streamable_http_sigv4 import streamablehttp_client_with_sigv4
from prompt_loader import get_prompt

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8083/mcp")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

PROMPT_NAME = "cat_care_assistant"

# ---------------------------------------------------------------------------
# Model registry — resolve friendly IDs to Bedrock model IDs
# ---------------------------------------------------------------------------
_MODELS_JSON = Path(__file__).resolve().parent.parent / "shared" / "models.json"
_MODEL_REGISTRY: dict[str, str] = {}
if _MODELS_JSON.exists():
    for m in json.loads(_MODELS_JSON.read_text()):
        _MODEL_REGISTRY[m["id"]] = m["model_id"]


def _resolve_model_id(model_id: str | None) -> str | None:
    """Resolve a registry ID (e.g. 'nova-pro') to a Bedrock model ID."""
    if not model_id:
        return None
    # If it's a registry key, resolve it; otherwise pass through as raw Bedrock ID
    return _MODEL_REGISTRY.get(model_id, model_id)


# ---------------------------------------------------------------------------
# Reusable model — model construction is cheap and stateless, so it stays
# at module level. The MCP client and Agent are built per request.
# ---------------------------------------------------------------------------

_model = BedrockModel(
    model_id=MODEL_ID,
    region_name="us-east-1",
)


def _create_mcp_client() -> MCPClient:
    """Create MCP client with appropriate transport/auth for the target URL.

    When MCP_SERVER_URL points to an AgentCore Gateway (*.gateway.bedrock-
    agentcore.*), we use SigV4-signed Streamable HTTP. Otherwise plain
    Streamable HTTP for local development.
    """
    if "gateway.bedrock-agentcore" in MCP_SERVER_URL:
        # Production: AgentCore Gateway requires SigV4
        session = boto3.Session()
        creds = session.get_credentials().get_frozen_credentials()

        def transport_factory():
            return streamablehttp_client_with_sigv4(
                url=MCP_SERVER_URL,
                credentials=Credentials(
                    access_key=creds.access_key,
                    secret_key=creds.secret_key,
                    token=creds.token,
                ),
                service="bedrock-agentcore",
                region=AWS_REGION,
            )

        return MCPClient(transport_factory)
    else:
        # Local: plain Streamable HTTP (no auth)
        return MCPClient(lambda: streamablehttp_client(MCP_SERVER_URL))


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Invocation(BaseModel):
    prompt: str = ""
    input: dict | None = None
    messages: list = []
    sessionId: str = ""
    model_id: str | None = None
    prompt_version: int | None = None


@app.get("/ping")
def ping():
    return {"status": "ok"}


def _run_agent(
    user_content: str,
    model_id: str | None = None,
    session_id: str = "",
    prompt_version: int | None = None,
) -> str:
    """Build a fresh MCPClient + Agent inside the calling thread, run one
    invocation, then tear down. Done synchronously so MCPClient.start()
    captures the OTel context active in this thread (the request task
    that the runtime's server span has activated).

    If the MCP server is unreachable, falls back to running the agent
    without tools so it can still answer questions using the model.
    """
    tools = []
    mcp_client = None
    try:
        mcp_client = _create_mcp_client()
        mcp_client.start()
        tools = mcp_client.list_tools_sync()
    except Exception:
        import traceback
        traceback.print_exc()
        print(f"[WARN] MCP server at {MCP_SERVER_URL} is unreachable. Running agent without tools.")
        mcp_client = None

    effective_model = _model
    resolved = _resolve_model_id(model_id)
    if resolved and resolved != MODEL_ID:
        effective_model = BedrockModel(model_id=resolved, region_name=AWS_REGION)

    system_prompt = get_prompt(PROMPT_NAME, session_id=session_id, version=prompt_version)

    try:
        agent = Agent(
            model=effective_model,
            system_prompt=system_prompt,
            tools=tools,
        )
        return str(agent(user_content))
    finally:
        if mcp_client is not None:
            try:
                mcp_client.stop()
            except Exception:
                pass


@app.post("/invocations")
async def invocations(payload: Invocation):
    # Support both Omni format (prompt) and original format (input.message)
    if payload.prompt:
        message = payload.prompt
        cat_id = None
    else:
        message = (payload.input or {}).get("message", "")
        cat_id = (payload.input or {}).get("cat_id")

    user_content = message
    if cat_id:
        user_content = f"[Context: current cat_id is '{cat_id}']\n{message}"

    try:
        # asyncio.to_thread copies contextvars (PEP 567) including the
        # OTel context, so MCPClient.start() in the worker thread sees
        # the runtime's server span as the active parent.
        result = await asyncio.to_thread(
            _run_agent, user_content, payload.model_id, payload.sessionId, payload.prompt_version
        )
        return {"agent": "strands", "response": result}
    except Exception:
        import traceback
        traceback.print_exc()
        return {
            "agent": "strands",
            "response": (
                "I'm having trouble connecting to my language model. "
                "Please check that AWS credentials are configured and "
                "the model is enabled in Bedrock."
            ),
        }

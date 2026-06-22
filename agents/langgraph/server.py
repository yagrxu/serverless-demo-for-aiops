"""LangGraph ReAct agent for the cat-care demo.

Uses ``create_react_agent`` with ``ChatBedrockConverse`` and MCP client
tools loaded dynamically from the MCP Server. The agent and its MCP tools
are built **inside the request handler** so the MCP client / httpx
transport opens its session within the request's OpenTelemetry context.
This keeps the Gateway POST under the runtime's root trace.

Pattern mirrors the AWS-official sample at
sample-smart-home-assistant-agent-on-agentcore/agent/agent.py.

OTel tracing is provided by ``opentelemetry-instrument`` which wraps the
process via the Dockerfile CMD. No manual TracerProvider setup here.
"""

import tracing_extras  # noqa: F401 — attaches CodeMetadataSpanProcessor, no-op without OTel

import json as _json
import os
import traceback
from pathlib import Path as _Path

import boto3
from botocore.credentials import Credentials
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_aws import ChatBedrockConverse
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from streamable_http_sigv4 import SigV4HTTPXAuth
from prompt_loader import get_prompt

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8083/mcp")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Model registry — resolve friendly IDs to Bedrock model IDs
_MODELS_JSON = _Path(__file__).resolve().parent.parent / "shared" / "models.json"
_MODEL_REGISTRY: dict[str, str] = {}
if _MODELS_JSON.exists():
    for _m in _json.loads(_MODELS_JSON.read_text()):
        _MODEL_REGISTRY[_m["id"]] = _m["model_id"]


def _resolve_model_id(model_id: str | None) -> str | None:
    if not model_id:
        return None
    return _MODEL_REGISTRY.get(model_id, model_id)

# Build the LLM once — it's stateless and safe to share across requests.
_llm = ChatBedrockConverse(model=MODEL_ID, region_name=AWS_REGION)


def _build_mcp_connection_config() -> dict:
    """Build MCP connection config with appropriate auth for the target URL.

    Called per-request so SigV4 credentials are refreshed and the auth
    handler is created inside the request's OTel context.
    """
    config: dict = {"url": MCP_SERVER_URL, "transport": "streamable_http"}
    if "gateway.bedrock-agentcore" in MCP_SERVER_URL:
        # Production: AgentCore Gateway requires SigV4
        session = boto3.Session()
        creds = session.get_credentials().get_frozen_credentials()
        config["auth"] = SigV4HTTPXAuth(
            Credentials(
                access_key=creds.access_key,
                secret_key=creds.secret_key,
                token=creds.token,
            ),
            service="bedrock-agentcore",
            region=AWS_REGION,
        )
    return config


async def _build_agent_with_tools(
    model_id: str | None = None,
    session_id: str = "",
    prompt_version: int | None = None,
):
    """Build a fresh MCP client + tools + ReAct agent inside the request.

    ``langchain-mcp-adapters`` opens a new MCP session for every tool call
    using the closure captured at ``get_tools`` time, so building per-request
    keeps every Gateway POST under the active trace.
    """
    llm = _llm
    if model_id and model_id != MODEL_ID:
        resolved = _resolve_model_id(model_id)
        if resolved and resolved != MODEL_ID:
            llm = ChatBedrockConverse(model=resolved, region_name=AWS_REGION)

    system_prompt = get_prompt("cat_care_assistant", session_id=session_id, version=prompt_version)

    client = MultiServerMCPClient({"cat-care": _build_mcp_connection_config()})
    tools = await client.get_tools()
    return create_react_agent(model=llm, tools=tools, prompt=system_prompt)


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
    messages: list = []
    sessionId: str = ""
    input: dict | None = None
    model_id: str | None = None
    prompt_version: int | None = None


@app.get("/ping")
def ping():
    return {"status": "ok"}


@app.post("/invocations")
async def invocations(payload: Invocation):
    # Support both Omni Studios format (prompt/messages) and legacy format (input dict)
    if payload.input:
        message = payload.input.get("message", "")
        cat_id = payload.input.get("cat_id")
    else:
        message = payload.prompt
        cat_id = None

    user_content = message
    if cat_id:
        user_content = f"[Context: current cat_id is '{cat_id}']\n{message}"

    try:
        agent = await _build_agent_with_tools(
            model_id=payload.model_id,
            session_id=payload.sessionId,
            prompt_version=payload.prompt_version,
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_content}]},
        )
        final_message = result["messages"][-1]
        return {"agent": "langgraph", "response": final_message.content}
    except Exception:
        traceback.print_exc()
        return {
            "agent": "langgraph",
            "response": (
                "I'm having trouble connecting to my language model. "
                "Please check that AWS credentials are configured and "
                "the model is enabled in Bedrock."
            ),
        }

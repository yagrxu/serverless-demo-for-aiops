"""LangGraph ReAct agent for the cat-care demo.

Uses create_react_agent with ChatBedrockConverse and MCP client tools loaded
dynamically from the MCP Server. The agent is built once at module level
and reused across requests. Each invocation creates a fresh message list
(stateless per request).

OTel tracing is provided by `opentelemetry-instrument` which wraps the
process via the Dockerfile CMD. No manual TracerProvider setup here.
"""

import asyncio
import os

import boto3
from botocore.credentials import Credentials
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langchain_aws import ChatBedrockConverse
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from streamable_http_sigv4 import SigV4HTTPXAuth

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8083/mcp")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
#MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

SYSTEM_PROMPT = (
    "You are a helpful cat-care assistant. You help users manage their cats' "
    "feeding schedules, health monitoring, and IoT devices (feeders, fountains, "
    "trackers). Use the available tools to look up real data before answering. "
    "Be concise and friendly.\n\n"
    "IMPORTANT: Most tools require a cat_id (e.g., 'hotpot', 'bbq'), not a cat name. "
    "When the user refers to a cat by name or nickname (e.g., '火锅', '锅锅', '烧烤', '烤烤'), "
    "you MUST first call lookup_cat_by_name to get the cat_id, then use that cat_id "
    "in subsequent tool calls like get_feedings, get_health_metrics, etc.\n\n"
    "If a cat_id is already provided in the context, you can skip the lookup and use it directly."
)

# ---------------------------------------------------------------------------
# MCP client — loads tools from MCP Server (local) or AgentCore Gateway (prod)
#
# When MCP_SERVER_URL points to an AgentCore Gateway, we pass SigV4 auth
# to the MultiServerMCPClient. Otherwise plain Streamable HTTP for local.
# Connection is deferred to the FastAPI lifespan to avoid calling
# asyncio.run() inside an already-running event loop (uvicorn).
# ---------------------------------------------------------------------------

from contextlib import asynccontextmanager

agent = None


def _build_mcp_connection_config() -> dict:
    """Build MCP connection config with appropriate auth for the target URL."""
    config: dict = {"url": MCP_SERVER_URL, "transport": "streamable_http"}
    if "gateway.bedrock-agentcore" in MCP_SERVER_URL:
        # Production: AgentCore Gateway — add SigV4 auth
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


@asynccontextmanager
async def lifespan(application: FastAPI):
    global agent
    conn_config = _build_mcp_connection_config()
    client = MultiServerMCPClient({"cat-care": conn_config})
    tools = await client.get_tools()
    llm = ChatBedrockConverse(model=MODEL_ID, region_name=AWS_REGION)
    agent = create_react_agent(model=llm, tools=tools, prompt=SYSTEM_PROMPT)
    yield


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(lifespan=lifespan)
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
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_content}]},
        )
        final_message = result["messages"][-1]
        return {"agent": "langgraph", "response": final_message.content}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {
            "agent": "langgraph",
            "response": (
                "I'm having trouble connecting to my language model. "
                "Please check that AWS credentials are configured and "
                "the model is enabled in Bedrock."
            ),
        }

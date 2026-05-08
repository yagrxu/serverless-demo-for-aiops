"""Strands agent for the cat-care demo.

Uses the Strands Agent class with BedrockModel and MCP client tools loaded
dynamically from the MCP Server. The agent is built once at module level and
reused across requests. Each invocation creates a fresh conversation (stateless
per request).
"""

import tracing  # noqa: F401 — must be first import (OTel setup)

import asyncio
import os

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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8083/mcp")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

SYSTEM_PROMPT = (
    "You are a helpful cat-care assistant. You help users manage their cats' "
    "feeding schedules, health monitoring, and IoT devices (feeders, fountains, "
    "trackers). Use the available tools to look up real data before answering. "
    "Be concise and friendly.\n\n"
    "Most tools require a cat_id, not a cat name. When the user refers to a cat "
    "by name or nickname, resolve it to a cat_id first before calling other tools."
)

# ---------------------------------------------------------------------------
# MCP client — connects to MCP Server (local) or AgentCore Gateway (prod)
#
# When MCP_SERVER_URL points to an AgentCore Gateway (*.gateway.bedrock-
# agentcore.*), we use SigV4-signed Streamable HTTP. Otherwise plain
# Streamable HTTP for local development.
# ---------------------------------------------------------------------------


def _create_mcp_client() -> MCPClient:
    """Create MCP client with appropriate transport/auth for the target URL."""
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


mcp_client = _create_mcp_client()

# ---------------------------------------------------------------------------
# Build the Strands agent once at module level
# ---------------------------------------------------------------------------

_model = BedrockModel(
    model_id=MODEL_ID,
    region_name="us-east-1",
)

strands_agent = Agent(
    model=_model,
    system_prompt=SYSTEM_PROMPT,
    tools=[mcp_client],
)

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


@app.get("/ping")
def ping():
    return {"status": "ok"}


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
        result = await asyncio.to_thread(strands_agent, user_content)
        return {"agent": "strands", "response": str(result)}
    except Exception:
        return {
            "agent": "strands",
            "response": (
                "I'm having trouble connecting to my language model. "
                "Please check that AWS credentials are configured and "
                "the model is enabled in Bedrock."
            ),
        }

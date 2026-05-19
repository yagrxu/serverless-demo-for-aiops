"""MCP Tool Bridge — connects to the MCP Server to provide tools for Nova Sonic.

Replaces the demo's hardcoded ToolRegistry with one that dynamically loads
tools from the MCP Server at localhost:8083 using the Streamable HTTP
(JSON-RPC) protocol.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from logging_utils import ConsoleLogger

logger = logging.getLogger("voice_agent.mcp_tools")

# Default MCP Server endpoint
DEFAULT_MCP_URL = "http://localhost:8083/mcp"


class MCPToolRegistry:
    """Tool registry that loads tool definitions from an MCP Server.

    Implements the same interface as the demo's ToolRegistry:
    - to_bedrock_config() → dict for Nova Sonic promptStart
    - get(name) → tool definition or None
    - names() → list of tool names
    """

    def __init__(self, mcp_url: str = DEFAULT_MCP_URL) -> None:
        self._mcp_url = mcp_url
        self._tools: dict[str, dict] = {}  # name → {description, inputSchema}
        self._loaded = False

    async def load(self) -> None:
        """Fetch tool definitions from the MCP Server via tools/list."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self._mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {},
                    },
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()

            if "result" in data and "tools" in data["result"]:
                for tool in data["result"]["tools"]:
                    name = tool.get("name", "")
                    description = tool.get("description", "")
                    # Truncate description to 200 chars (Nova Sonic limit)
                    if len(description) > 200:
                        description = description[:197] + "..."
                    input_schema = tool.get("inputSchema", {"type": "object", "properties": {}})
                    self._tools[name] = {
                        "description": description,
                        "inputSchema": input_schema,
                    }
                self._loaded = True
                logger.info("Loaded %d tools from MCP Server: %s", len(self._tools), list(self._tools.keys()))
            else:
                logger.warning("MCP tools/list returned unexpected response: %s", data)

        except Exception as exc:
            logger.error("Failed to load tools from MCP Server at %s: %s", self._mcp_url, exc)
            # Continue with empty registry — the agent will work without tools

    def get(self, name: str) -> dict | None:
        """Return tool definition dict or None."""
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def to_bedrock_config(self) -> dict:
        """Return the toolConfiguration payload for Nova Sonic promptStart.

        Shape:
            {
              "tools": [
                {
                  "toolSpec": {
                    "name": <tool_name>,
                    "description": <description>,
                    "inputSchema": {"json": <json_schema_as_string>}
                  }
                },
                ...
              ]
            }
        """
        return {
            "tools": [
                {
                    "toolSpec": {
                        "name": name,
                        "description": defn["description"],
                        "inputSchema": {"json": json.dumps(defn["inputSchema"])},
                    }
                }
                for name, defn in self._tools.items()
            ]
        }


class MCPToolDispatcher:
    """Dispatches tool calls to the MCP Server via tools/call.

    Implements the same interface as the demo's ToolDispatcher:
    - dispatch(tool_use_id, tool_name, arguments) → dict result
    """

    def __init__(
        self,
        registry: MCPToolRegistry,
        logger_instance: ConsoleLogger,
        mcp_url: str = DEFAULT_MCP_URL,
        timeout_s: float = 10.0,
    ) -> None:
        self._registry = registry
        self._logger = logger_instance
        self._mcp_url = mcp_url
        self._timeout_s = timeout_s
        self._call_id = 100  # incrementing JSON-RPC id

    async def dispatch(
        self,
        tool_use_id: str,
        tool_name: str,
        arguments: dict,
    ) -> dict:
        """Execute a tool call via the MCP Server."""
        # Log the tool call
        self._logger.tool_call(tool_name, arguments)

        # Check if tool exists in registry
        tool = self._registry.get(tool_name)
        if tool is None:
            result = {"error": "unknown_tool", "tool": tool_name}
            self._logger.tool_result(tool_name, result)
            return result

        # Call the MCP Server
        self._call_id += 1
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.post(
                    self._mcp_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": self._call_id,
                        "method": "tools/call",
                        "params": {
                            "name": tool_name,
                            "arguments": arguments,
                        },
                    },
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()

            if "result" in data:
                mcp_result = data["result"]
                # MCP tools/call returns {content: [{type: "text", text: "..."}]}
                # Extract the text content and parse as JSON if possible
                result = self._extract_result(mcp_result)
            elif "error" in data:
                error_info = data["error"]
                result = {"error": error_info.get("message", "MCP error")}
            else:
                result = {"error": "unexpected_response"}

        except httpx.TimeoutException:
            result = {"error": "tool_timeout"}
        except Exception as exc:
            message = str(exc)[:200] or type(exc).__name__[:200]
            result = {"error": message}

        self._logger.tool_result(tool_name, result)
        return result

    @staticmethod
    def _extract_result(mcp_result: Any) -> dict:
        """Extract a usable dict from the MCP tools/call response.

        MCP returns: {content: [{type: "text", text: "..."}], isError: bool}
        We try to parse the text as JSON; if that fails, wrap it in a dict.
        """
        if not isinstance(mcp_result, dict):
            return {"result": str(mcp_result)}

        content_list = mcp_result.get("content", [])
        is_error = mcp_result.get("isError", False)

        if is_error:
            # Extract error text
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "text":
                    return {"error": item.get("text", "unknown error")}
            return {"error": "tool_error"}

        # Extract text content
        texts = []
        for item in content_list:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))

        combined = "\n".join(texts) if texts else ""

        # Try to parse as JSON
        try:
            parsed = json.loads(combined)
            if isinstance(parsed, dict):
                return parsed
            return {"result": parsed}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {"result": combined}

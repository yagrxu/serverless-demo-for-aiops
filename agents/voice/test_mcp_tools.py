"""Unit tests for the MCP Tool Bridge (mcp_tools.py).

Tests MCPToolRegistry and MCPToolDispatcher without requiring a running
MCP Server — all HTTP calls are mocked.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_tools import MCPToolRegistry, MCPToolDispatcher
from logging_utils import ConsoleLogger


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

MOCK_TOOLS_LIST_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "tools": [
            {
                "name": "list_cats",
                "description": "List all registered cats",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
            {
                "name": "get_cat",
                "description": "Get a cat by ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {"cat_id": {"type": "string"}},
                    "required": ["cat_id"],
                },
            },
            {
                "name": "long_description_tool",
                "description": "A" * 250,  # exceeds 200 char limit
                "inputSchema": {"type": "object", "properties": {}},
            },
        ],
    },
}

MOCK_TOOL_CALL_SUCCESS = {
    "jsonrpc": "2.0",
    "id": 101,
    "result": {
        "content": [
            {"type": "text", "text": json.dumps([{"cat_id": "cat-1", "name": "Whiskers"}])},
        ],
        "isError": False,
    },
}

MOCK_TOOL_CALL_ERROR = {
    "jsonrpc": "2.0",
    "id": 102,
    "result": {
        "content": [{"type": "text", "text": "Cat not found"}],
        "isError": True,
    },
}


def _mock_response(json_data):
    """Create a mock httpx.Response that behaves like a real one."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_data
    return resp


# ---------------------------------------------------------------------------
# MCPToolRegistry tests
# ---------------------------------------------------------------------------


class TestMCPToolRegistry:
    """Test MCPToolRegistry loads tools and converts to Bedrock config."""

    @pytest.mark.asyncio
    async def test_load_tools_from_mcp_server(self):
        """Registry loads tools from a mocked MCP Server response."""
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(MOCK_TOOLS_LIST_RESPONSE)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_tools.httpx.AsyncClient", return_value=mock_client):
            registry = MCPToolRegistry(mcp_url="http://mock:8083/mcp")
            await registry.load()

        assert registry.names() == ["list_cats", "get_cat", "long_description_tool"]
        assert registry.get("list_cats") is not None
        assert registry.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_description_truncation(self):
        """Descriptions longer than 200 chars are truncated."""
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(MOCK_TOOLS_LIST_RESPONSE)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_tools.httpx.AsyncClient", return_value=mock_client):
            registry = MCPToolRegistry(mcp_url="http://mock:8083/mcp")
            await registry.load()

        tool = registry.get("long_description_tool")
        assert tool is not None
        assert len(tool["description"]) == 200
        assert tool["description"].endswith("...")

    @pytest.mark.asyncio
    async def test_to_bedrock_config_format(self):
        """to_bedrock_config() returns the correct Nova Sonic shape."""
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(MOCK_TOOLS_LIST_RESPONSE)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_tools.httpx.AsyncClient", return_value=mock_client):
            registry = MCPToolRegistry(mcp_url="http://mock:8083/mcp")
            await registry.load()

        config = registry.to_bedrock_config()
        assert "tools" in config
        assert len(config["tools"]) == 3

        first_tool = config["tools"][0]
        assert "toolSpec" in first_tool
        spec = first_tool["toolSpec"]
        assert spec["name"] == "list_cats"
        assert spec["description"] == "List all registered cats"
        assert "json" in spec["inputSchema"]
        parsed_schema = json.loads(spec["inputSchema"]["json"])
        assert parsed_schema["type"] == "object"

    @pytest.mark.asyncio
    async def test_load_handles_connection_error(self):
        """Registry handles connection errors gracefully (empty tools)."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_tools.httpx.AsyncClient", return_value=mock_client):
            registry = MCPToolRegistry(mcp_url="http://mock:8083/mcp")
            await registry.load()

        assert registry.names() == []
        assert registry.to_bedrock_config() == {"tools": []}

    @pytest.mark.asyncio
    async def test_empty_registry_before_load(self):
        """Registry is empty before load() is called."""
        registry = MCPToolRegistry(mcp_url="http://mock:8083/mcp")
        assert registry.names() == []
        assert registry.get("anything") is None
        assert registry.to_bedrock_config() == {"tools": []}


# ---------------------------------------------------------------------------
# MCPToolDispatcher tests
# ---------------------------------------------------------------------------


class TestMCPToolDispatcher:
    """Test MCPToolDispatcher dispatches tool calls via MCP protocol."""

    def _make_registry_with_tools(self) -> MCPToolRegistry:
        """Create a pre-loaded registry (bypass HTTP)."""
        registry = MCPToolRegistry(mcp_url="http://mock:8083/mcp")
        registry._tools = {
            "list_cats": {
                "description": "List all cats",
                "inputSchema": {"type": "object", "properties": {}},
            },
            "get_cat": {
                "description": "Get a cat by ID",
                "inputSchema": {
                    "type": "object",
                    "properties": {"cat_id": {"type": "string"}},
                    "required": ["cat_id"],
                },
            },
        }
        registry._loaded = True
        return registry

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool(self):
        """Dispatching an unknown tool returns an error dict."""
        registry = self._make_registry_with_tools()
        dispatcher = MCPToolDispatcher(
            registry=registry, logger_instance=ConsoleLogger(),
            mcp_url="http://mock:8083/mcp",
        )

        result = await dispatcher.dispatch("use-1", "nonexistent_tool", {})
        assert result == {"error": "unknown_tool", "tool": "nonexistent_tool"}

    @pytest.mark.asyncio
    async def test_dispatch_successful_call(self):
        """Dispatching a known tool returns parsed JSON result."""
        registry = self._make_registry_with_tools()
        dispatcher = MCPToolDispatcher(
            registry=registry, logger_instance=ConsoleLogger(),
            mcp_url="http://mock:8083/mcp",
        )

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(MOCK_TOOL_CALL_SUCCESS)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_tools.httpx.AsyncClient", return_value=mock_client):
            result = await dispatcher.dispatch("use-1", "list_cats", {})

        assert isinstance(result, dict)
        assert "result" in result
        assert result["result"][0]["cat_id"] == "cat-1"

    @pytest.mark.asyncio
    async def test_dispatch_tool_error_response(self):
        """Dispatching a tool that returns isError=True returns error dict."""
        registry = self._make_registry_with_tools()
        dispatcher = MCPToolDispatcher(
            registry=registry, logger_instance=ConsoleLogger(),
            mcp_url="http://mock:8083/mcp",
        )

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_response(MOCK_TOOL_CALL_ERROR)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_tools.httpx.AsyncClient", return_value=mock_client):
            result = await dispatcher.dispatch("use-2", "get_cat", {"cat_id": "cat-999"})

        assert result == {"error": "Cat not found"}

    @pytest.mark.asyncio
    async def test_dispatch_timeout(self):
        """Dispatching a tool that times out returns timeout error."""
        import httpx as httpx_mod

        registry = self._make_registry_with_tools()
        dispatcher = MCPToolDispatcher(
            registry=registry, logger_instance=ConsoleLogger(),
            mcp_url="http://mock:8083/mcp", timeout_s=0.1,
        )

        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx_mod.TimeoutException("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_tools.httpx.AsyncClient", return_value=mock_client):
            result = await dispatcher.dispatch("use-3", "list_cats", {})

        assert result == {"error": "tool_timeout"}

    @pytest.mark.asyncio
    async def test_dispatch_connection_error(self):
        """Dispatching when MCP Server is down returns error."""
        registry = self._make_registry_with_tools()
        dispatcher = MCPToolDispatcher(
            registry=registry, logger_instance=ConsoleLogger(),
            mcp_url="http://mock:8083/mcp",
        )

        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("mcp_tools.httpx.AsyncClient", return_value=mock_client):
            result = await dispatcher.dispatch("use-4", "list_cats", {})

        assert "error" in result
        assert "Connection refused" in result["error"]


# ---------------------------------------------------------------------------
# MCPToolDispatcher._extract_result tests
# ---------------------------------------------------------------------------


class TestExtractResult:
    """Test the static _extract_result helper."""

    def test_json_text_content(self):
        """Parses JSON text content into a dict."""
        mcp_result = {
            "content": [{"type": "text", "text": '{"cat_id": "cat-1", "name": "Felix"}'}],
            "isError": False,
        }
        result = MCPToolDispatcher._extract_result(mcp_result)
        assert result == {"cat_id": "cat-1", "name": "Felix"}

    def test_plain_text_content(self):
        """Non-JSON text is wrapped in a result dict."""
        mcp_result = {
            "content": [{"type": "text", "text": "Hello world"}],
            "isError": False,
        }
        result = MCPToolDispatcher._extract_result(mcp_result)
        assert result == {"result": "Hello world"}

    def test_error_content(self):
        """isError=True extracts error text."""
        mcp_result = {
            "content": [{"type": "text", "text": "Not found"}],
            "isError": True,
        }
        result = MCPToolDispatcher._extract_result(mcp_result)
        assert result == {"error": "Not found"}

    def test_multiple_text_items(self):
        """Multiple text items are joined with newlines."""
        mcp_result = {
            "content": [
                {"type": "text", "text": "line1"},
                {"type": "text", "text": "line2"},
            ],
            "isError": False,
        }
        result = MCPToolDispatcher._extract_result(mcp_result)
        assert result == {"result": "line1\nline2"}

    def test_non_dict_input(self):
        """Non-dict input is stringified."""
        result = MCPToolDispatcher._extract_result("raw string")
        assert result == {"result": "raw string"}

    def test_empty_content(self):
        """Empty content list returns empty result."""
        mcp_result = {"content": [], "isError": False}
        result = MCPToolDispatcher._extract_result(mcp_result)
        assert result == {"result": ""}

    def test_json_array_content(self):
        """JSON array is wrapped in result key."""
        mcp_result = {
            "content": [{"type": "text", "text": '[{"id": 1}, {"id": 2}]'}],
            "isError": False,
        }
        result = MCPToolDispatcher._extract_result(mcp_result)
        assert result == {"result": [{"id": 1}, {"id": 2}]}

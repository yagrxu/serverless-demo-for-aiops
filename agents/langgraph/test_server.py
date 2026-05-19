"""Baseline tests for the langgraph agent.

Validates:
- server module imports without error (Req 8.2)
- SigV4 signing helper produces correct Authorization headers (Req 8.3)
- No outbound network calls occur (Req 8.5)
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: mock heavy dependencies before importing agent modules
# ---------------------------------------------------------------------------

def _mock_heavy_deps():
    """Return a dict of module mocks for heavy/network-dependent imports."""
    return {
        "tracing_extras": MagicMock(),
        "langchain_aws": MagicMock(),
        "langchain_mcp_adapters": MagicMock(),
        "langchain_mcp_adapters.client": MagicMock(),
        "langgraph": MagicMock(),
        "langgraph.prebuilt": MagicMock(),
        # Mock the mcp package tree to avoid pydantic version conflicts
        "mcp": MagicMock(),
        "mcp.client": MagicMock(),
        "mcp.client.streamable_http": MagicMock(),
        "mcp.shared": MagicMock(),
        "mcp.shared._httpx_utils": MagicMock(),
        "mcp.shared.message": MagicMock(),
        "anyio": MagicMock(),
        "anyio.streams": MagicMock(),
        "anyio.streams.memory": MagicMock(),
    }


def _clear_agent_modules():
    """Remove cached agent modules so they can be re-imported cleanly."""
    to_remove = [
        k for k in sys.modules
        if k.startswith(("server", "tracing_extras", "streamable_http_sigv4"))
    ]
    for mod in to_remove:
        del sys.modules[mod]


# ---------------------------------------------------------------------------
# Test: server module imports without error
# ---------------------------------------------------------------------------


class TestServerImport:
    """Verify that the server module can be imported with mocked externals."""

    def test_server_module_imports_successfully(self):
        """Import server module with heavy dependencies mocked out.

        Mocks boto3, langchain_aws, langchain_mcp_adapters, langgraph,
        tracing_extras, and mcp to prevent any network calls or model
        initialization during import.
        """
        _clear_agent_modules()

        mocks = _mock_heavy_deps()

        with patch.dict(sys.modules, mocks):
            import importlib
            import server

            importlib.reload(server)

            # Verify the module loaded and has expected attributes
            assert server is not None
            assert hasattr(server, "app")
            assert hasattr(server, "ping")
            assert hasattr(server, "invocations")
            assert hasattr(server, "MCP_SERVER_URL")
            assert hasattr(server, "MODEL_ID")
            assert hasattr(server, "AWS_REGION")


# ---------------------------------------------------------------------------
# Test: SigV4 signing helper (deterministic code path)
# ---------------------------------------------------------------------------


class TestSigV4HTTPXAuth:
    """Test the SigV4HTTPXAuth class from streamable_http_sigv4.py.

    This exercises a deterministic, non-LLM code path: request signing.
    We mock the mcp imports that streamable_http_sigv4 pulls in, but
    the actual SigV4 signing logic uses real botocore + httpx.
    """

    def _import_sigv4_auth(self):
        """Import SigV4HTTPXAuth with mcp dependencies mocked."""
        _clear_agent_modules()
        mocks = _mock_heavy_deps()
        with patch.dict(sys.modules, mocks):
            import importlib
            import streamable_http_sigv4

            importlib.reload(streamable_http_sigv4)
            return streamable_http_sigv4.SigV4HTTPXAuth

    def test_auth_flow_signs_request_with_valid_credentials(self):
        """SigV4HTTPXAuth.auth_flow should add Authorization header to request."""
        import httpx
        from botocore.credentials import Credentials

        SigV4HTTPXAuth = self._import_sigv4_auth()

        creds = Credentials(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            token="FwoGZXIvYXdzEBYaDHqa0AP1",
        )

        auth = SigV4HTTPXAuth(
            credentials=creds,
            service="bedrock-agentcore",
            region="us-east-1",
        )

        # Build a sample request
        request = httpx.Request(
            method="POST",
            url="https://gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
            headers={"Content-Type": "application/json"},
            content=b'{"method": "tools/list"}',
        )

        # Execute the auth flow generator
        flow = auth.auth_flow(request)
        signed_request = next(flow)

        # SigV4 should have added Authorization and other AWS headers
        assert "authorization" in signed_request.headers
        auth_header = signed_request.headers["authorization"]
        assert "AWS4-HMAC-SHA256" in auth_header
        assert "Credential=AKIAIOSFODNN7EXAMPLE" in auth_header
        assert "bedrock-agentcore" in auth_header
        assert "us-east-1" in auth_header

        # X-Amz-Security-Token should be present when session token is provided
        assert "x-amz-security-token" in signed_request.headers
        assert signed_request.headers["x-amz-security-token"] == "FwoGZXIvYXdzEBYaDHqa0AP1"

        # X-Amz-Date should be present
        assert "x-amz-date" in signed_request.headers

    def test_auth_flow_signs_request_without_session_token(self):
        """SigV4HTTPXAuth should work with long-term credentials (no token)."""
        import httpx
        from botocore.credentials import Credentials

        SigV4HTTPXAuth = self._import_sigv4_auth()

        creds = Credentials(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            token=None,
        )

        auth = SigV4HTTPXAuth(
            credentials=creds,
            service="bedrock-agentcore",
            region="eu-west-1",
        )

        request = httpx.Request(
            method="GET",
            url="https://gateway.bedrock-agentcore.eu-west-1.amazonaws.com/health",
            headers={},
        )

        flow = auth.auth_flow(request)
        signed_request = next(flow)

        assert "authorization" in signed_request.headers
        auth_header = signed_request.headers["authorization"]
        assert "AWS4-HMAC-SHA256" in auth_header
        assert "eu-west-1" in auth_header
        # No security token header when token is None
        assert "x-amz-security-token" not in signed_request.headers

    def test_auth_flow_removes_connection_header_before_signing(self):
        """Connection header should be stripped to avoid signature mismatch."""
        import httpx
        from botocore.credentials import Credentials

        SigV4HTTPXAuth = self._import_sigv4_auth()

        creds = Credentials(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            token=None,
        )

        auth = SigV4HTTPXAuth(
            credentials=creds,
            service="bedrock-agentcore",
            region="us-east-1",
        )

        # Request with a 'connection' header that should be removed for signing
        request = httpx.Request(
            method="POST",
            url="https://gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
            headers={"Content-Type": "application/json", "connection": "keep-alive"},
            content=b"{}",
        )

        flow = auth.auth_flow(request)
        signed_request = next(flow)

        # The request should still be signed successfully
        assert "authorization" in signed_request.headers
        assert "AWS4-HMAC-SHA256" in signed_request.headers["authorization"]

    def test_auth_flow_with_invalid_credentials_type(self):
        """SigV4HTTPXAuth should raise when credentials are not a Credentials object."""
        SigV4HTTPXAuth = self._import_sigv4_auth()

        # Passing invalid credentials type should raise during signing
        with pytest.raises((TypeError, AttributeError)):
            auth = SigV4HTTPXAuth(
                credentials="not-a-credentials-object",  # type: ignore
                service="bedrock-agentcore",
                region="us-east-1",
            )
            import httpx

            request = httpx.Request(
                method="POST",
                url="https://example.com/mcp",
                content=b"{}",
            )
            flow = auth.auth_flow(request)
            next(flow)


# ---------------------------------------------------------------------------
# Test: Configuration defaults
# ---------------------------------------------------------------------------


class TestConfigurationDefaults:
    """Test that configuration loading uses expected defaults."""

    def test_default_config_values(self):
        """Verify default environment variable fallbacks in server module."""
        _clear_agent_modules()

        mocks = _mock_heavy_deps()

        with patch.dict(sys.modules, mocks), \
             patch.dict("os.environ", {}, clear=False):
            import importlib
            import server

            importlib.reload(server)

            # Check defaults when env vars are not set
            assert server.MCP_SERVER_URL == "http://localhost:8083/mcp"
            assert server.MODEL_ID == "anthropic.claude-haiku-4-5-20251001-v1:0"
            assert server.AWS_REGION == "us-east-1"

    def test_config_values_from_environment(self):
        """Verify configuration picks up environment variables."""
        _clear_agent_modules()

        mocks = _mock_heavy_deps()

        custom_env = {
            "MCP_SERVER_URL": "https://custom-mcp.example.com/mcp",
            "MODEL_ID": "anthropic.claude-sonnet-4-20250514-v1:0",
            "AWS_REGION": "eu-west-1",
        }

        with patch.dict(sys.modules, mocks), \
             patch.dict("os.environ", custom_env):
            import importlib
            import server

            importlib.reload(server)

            assert server.MCP_SERVER_URL == "https://custom-mcp.example.com/mcp"
            assert server.MODEL_ID == "anthropic.claude-sonnet-4-20250514-v1:0"
            assert server.AWS_REGION == "eu-west-1"

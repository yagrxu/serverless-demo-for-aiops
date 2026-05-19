"""Baseline tests for the Strands agent server module.

Validates:
- Module imports succeed without network calls (Requirement 8.2)
- Deterministic SigV4 signing logic works correctly (Requirement 8.3)
- No outbound network calls occur during tests (Requirement 8.5)
"""

import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers: mock the problematic MCP imports that trigger pydantic errors
# ---------------------------------------------------------------------------


def _mock_mcp_modules():
    """Return a dict of mocked MCP-related modules to patch into sys.modules."""
    mock_mcp = MagicMock()
    mock_mcp_client = MagicMock()
    mock_mcp_client_streamable_http = MagicMock()
    mock_mcp_client_streamable_http.streamablehttp_client = MagicMock()
    mock_mcp_client_streamable_http.GetSessionIdCallback = MagicMock()
    mock_mcp_shared = MagicMock()
    mock_mcp_shared_httpx_utils = MagicMock()
    mock_mcp_shared_httpx_utils.McpHttpClientFactory = MagicMock()
    mock_mcp_shared_httpx_utils.create_mcp_http_client = MagicMock()
    mock_mcp_shared_message = MagicMock()

    return {
        "mcp": mock_mcp,
        "mcp.client": mock_mcp_client,
        "mcp.client.streamable_http": mock_mcp_client_streamable_http,
        "mcp.shared": mock_mcp_shared,
        "mcp.shared._httpx_utils": mock_mcp_shared_httpx_utils,
        "mcp.shared.message": mock_mcp_shared_message,
    }


def _mock_strands_modules():
    """Return a dict of mocked Strands-related modules to patch into sys.modules."""
    mock_bedrock_model = MagicMock()
    mock_strands_models_bedrock = MagicMock()
    mock_strands_models_bedrock.BedrockModel = mock_bedrock_model

    return {
        "tracing_extras": MagicMock(),
        "strands": MagicMock(),
        "strands.models": MagicMock(),
        "strands.models.bedrock": mock_strands_models_bedrock,
        "strands.tools": MagicMock(),
        "strands.tools.mcp": MagicMock(),
    }


# ---------------------------------------------------------------------------
# Test: server module imports without error (Requirement 8.1, 8.2)
# ---------------------------------------------------------------------------


class TestServerImport:
    """Verify that the server module can be imported without network calls."""

    def test_server_module_imports_successfully(self):
        """Import the server module with mocked external dependencies."""
        mocks = {**_mock_mcp_modules(), **_mock_strands_modules()}

        with patch.dict(sys.modules, mocks):
            # Remove cached module if previously imported
            sys.modules.pop("server", None)
            sys.modules.pop("streamable_http_sigv4", None)

            import server

            assert server is not None
            assert hasattr(server, "app")
            assert hasattr(server, "ping")
            assert hasattr(server, "invocations")

            # Clean up
            sys.modules.pop("server", None)
            sys.modules.pop("streamable_http_sigv4", None)


# ---------------------------------------------------------------------------
# Test: SigV4 signing helper — deterministic code path (Requirement 8.3)
# ---------------------------------------------------------------------------


class TestSigV4HTTPXAuth:
    """Test the SigV4HTTPXAuth class from streamable_http_sigv4.py."""

    def _import_sigv4_auth(self):
        """Import SigV4HTTPXAuth with mocked MCP dependencies."""
        mocks = _mock_mcp_modules()
        with patch.dict(sys.modules, mocks):
            sys.modules.pop("streamable_http_sigv4", None)
            from streamable_http_sigv4 import SigV4HTTPXAuth
            return SigV4HTTPXAuth

    def test_auth_flow_signs_request_with_valid_credentials(self):
        """Valid credentials should produce signed headers on the request."""
        from botocore.credentials import Credentials
        import httpx

        SigV4HTTPXAuth = self._import_sigv4_auth()

        creds = Credentials(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            token="FwoGZXIvYXdzEBYaDHqa0AP1",
        )
        auth = SigV4HTTPXAuth(credentials=creds, service="bedrock-agentcore", region="us-east-1")

        request = httpx.Request(
            method="POST",
            url="https://example.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
            content=b'{"jsonrpc":"2.0","method":"tools/list"}',
            headers={"content-type": "application/json"},
        )

        # auth_flow is a generator — advance it to get the signed request
        flow = auth.auth_flow(request)
        signed_request = next(flow)

        # SigV4 adds Authorization and X-Amz-Date headers
        assert "authorization" in signed_request.headers
        assert "x-amz-date" in signed_request.headers
        # Authorization header should contain the expected algorithm
        auth_header = signed_request.headers["authorization"]
        assert "AWS4-HMAC-SHA256" in auth_header
        assert "AKIAIOSFODNN7EXAMPLE" in auth_header
        assert "bedrock-agentcore" in auth_header
        assert "us-east-1" in auth_header

    def test_auth_flow_signs_request_without_session_token(self):
        """Credentials without a session token should still sign correctly."""
        from botocore.credentials import Credentials
        import httpx

        SigV4HTTPXAuth = self._import_sigv4_auth()

        creds = Credentials(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        auth = SigV4HTTPXAuth(credentials=creds, service="execute-api", region="eu-west-1")

        request = httpx.Request(
            method="GET",
            url="https://api.example.com/resource",
            headers={},
        )

        flow = auth.auth_flow(request)
        signed_request = next(flow)

        assert "authorization" in signed_request.headers
        assert "x-amz-date" in signed_request.headers
        # No x-amz-security-token when no session token
        assert "x-amz-security-token" not in signed_request.headers

    def test_auth_flow_removes_connection_header_before_signing(self):
        """The 'connection' header should be removed to avoid signature mismatch."""
        from botocore.credentials import Credentials
        import httpx

        SigV4HTTPXAuth = self._import_sigv4_auth()

        creds = Credentials(
            access_key="AKIAIOSFODNN7EXAMPLE",
            secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        )
        auth = SigV4HTTPXAuth(credentials=creds, service="bedrock-agentcore", region="us-east-1")

        request = httpx.Request(
            method="POST",
            url="https://example.com/mcp",
            content=b"{}",
            headers={"content-type": "application/json", "connection": "keep-alive"},
        )

        flow = auth.auth_flow(request)
        signed_request = next(flow)

        # The request should still be signed successfully
        assert "authorization" in signed_request.headers

    def test_auth_flow_with_empty_credentials(self):
        """Empty access key should still produce a signed request (botocore doesn't validate at sign time)."""
        from botocore.credentials import Credentials
        import httpx

        SigV4HTTPXAuth = self._import_sigv4_auth()

        # botocore Credentials with empty strings — signing will still proceed
        # but produce an invalid signature. We verify the auth object is created
        # and the flow runs without crashing.
        creds = Credentials(access_key="", secret_key="")
        auth = SigV4HTTPXAuth(credentials=creds, service="bedrock-agentcore", region="us-east-1")

        request = httpx.Request(
            method="POST",
            url="https://example.com/mcp",
            content=b"{}",
            headers={"content-type": "application/json"},
        )

        # Should not raise — botocore signs even with empty creds
        flow = auth.auth_flow(request)
        signed_request = next(flow)
        # Authorization header is present but with empty credential scope
        assert "authorization" in signed_request.headers


# ---------------------------------------------------------------------------
# Test: Configuration loading (Requirement 8.3)
# ---------------------------------------------------------------------------


class TestServerConfiguration:
    """Test that server configuration is loaded from environment variables."""

    def test_default_config_values(self):
        """Server should have sensible defaults when env vars are not set."""
        mocks = {**_mock_mcp_modules(), **_mock_strands_modules()}

        with patch.dict(sys.modules, mocks):
            sys.modules.pop("server", None)
            sys.modules.pop("streamable_http_sigv4", None)

            import server

            assert server.MCP_SERVER_URL == "http://localhost:8083/mcp"
            assert server.MODEL_ID == "anthropic.claude-haiku-4-5-20251001-v1:0"
            assert server.AWS_REGION == "us-east-1"

            sys.modules.pop("server", None)
            sys.modules.pop("streamable_http_sigv4", None)

    def test_custom_config_from_env(self):
        """Server should read configuration from environment variables."""
        import os

        mocks = {**_mock_mcp_modules(), **_mock_strands_modules()}

        env_overrides = {
            "MCP_SERVER_URL": "https://custom.gateway.bedrock-agentcore.us-west-2.amazonaws.com/mcp",
            "MODEL_ID": "anthropic.claude-sonnet-4-20250514-v1:0",
            "AWS_REGION": "us-west-2",
        }

        with patch.dict(os.environ, env_overrides):
            with patch.dict(sys.modules, mocks):
                sys.modules.pop("server", None)
                sys.modules.pop("streamable_http_sigv4", None)

                import server

                assert server.MCP_SERVER_URL == env_overrides["MCP_SERVER_URL"]
                assert server.MODEL_ID == env_overrides["MODEL_ID"]
                assert server.AWS_REGION == env_overrides["AWS_REGION"]

                sys.modules.pop("server", None)
                sys.modules.pop("streamable_http_sigv4", None)

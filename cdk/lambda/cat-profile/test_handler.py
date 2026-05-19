"""Baseline tests for cat-profile Lambda handler.

Validates:
- Handler module imports without error
- Handler returns 2xx statusCode for a valid API Gateway proxy event

Uses unittest.mock to mock DynamoDB — no real AWS calls.
"""
import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

HANDLER_PATH = os.path.join(os.path.dirname(__file__), "handler.py")
MODULE_NAME = "cat_profile_handler"


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """Set required environment variables before handler import."""
    monkeypatch.setenv("CAT_PROFILES_TABLE", "test-cat-profiles")
    monkeypatch.setenv("CAT_NAME_INDEX_TABLE", "test-cat-name-index")
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "cat-profile")
    monkeypatch.setenv("POWERTOOLS_METRICS_NAMESPACE", "CatDemo")


@pytest.fixture()
def mock_tables():
    """Patch boto3 DynamoDB resource and tables, then import handler."""
    mock_ddb_resource = MagicMock()
    mock_table = MagicMock()
    mock_name_index = MagicMock()

    mock_ddb_resource.Table.side_effect = lambda name: (
        mock_table if name == "test-cat-profiles" else mock_name_index
    )

    with patch("boto3.resource", return_value=mock_ddb_resource):
        # Remove cached module so we get a fresh import with mocks
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]

        spec = importlib.util.spec_from_file_location(MODULE_NAME, HANDLER_PATH)
        handler_module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = handler_module
        spec.loader.exec_module(handler_module)

        yield {
            "module": handler_module,
            "table": mock_table,
            "name_index": mock_name_index,
        }

        # Cleanup
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]


def _api_gw_event(method: str, resource: str, body=None, path_params=None, query_params=None):
    """Create a representative API Gateway proxy event."""
    return {
        "httpMethod": method,
        "resource": resource,
        "path": resource,
        "body": json.dumps(body) if body else None,
        "pathParameters": path_params,
        "queryStringParameters": query_params,
        "headers": {"Content-Type": "application/json"},
        "requestContext": {
            "requestId": "test-request-id",
            "stage": "test",
        },
    }


class TestHandlerImport:
    """Test that the handler module imports without error."""

    def test_handler_module_imports(self, mock_tables):
        """Handler module should import successfully."""
        handler_module = mock_tables["module"]
        assert handler_module is not None
        assert hasattr(handler_module, "lambda_handler")
        assert callable(handler_module.lambda_handler)


class TestHandlerResponse:
    """Test that handler returns 2xx statusCode for valid API Gateway proxy events."""

    def test_list_cats_returns_200(self, mock_tables):
        """GET /cats should return 200 with a list of cats."""
        handler_module = mock_tables["module"]
        mock_table = mock_tables["table"]

        # Mock DynamoDB scan response
        mock_table.scan.return_value = {"Items": [{"cat_id": "cat-1", "name": "Whiskers"}]}

        event = _api_gw_event("GET", "/cats")
        ctx = MagicMock()
        ctx.client_context = None

        result = handler_module.lambda_handler(event, ctx)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert isinstance(body, list)

    def test_create_cat_returns_201(self, mock_tables):
        """POST /cats should return 201 with the created cat."""
        handler_module = mock_tables["module"]
        mock_table = mock_tables["table"]
        mock_name_index = mock_tables["name_index"]

        # Mock DynamoDB put_item (no return needed)
        mock_table.put_item.return_value = {}
        mock_name_index.put_item.return_value = {}

        event = _api_gw_event("POST", "/cats", body={"name": "Mittens", "breed": "Tabby"})
        ctx = MagicMock()
        ctx.client_context = None

        result = handler_module.lambda_handler(event, ctx)

        assert result["statusCode"] == 201
        body = json.loads(result["body"])
        assert body["name"] == "Mittens"
        assert "cat_id" in body

    def test_get_cat_by_id_returns_200(self, mock_tables):
        """GET /cats/{id} should return 200 when cat exists."""
        handler_module = mock_tables["module"]
        mock_table = mock_tables["table"]

        # Mock DynamoDB get_item response
        mock_table.get_item.return_value = {"Item": {"cat_id": "cat-123", "name": "Felix"}}

        event = _api_gw_event("GET", "/cats/{id}", path_params={"id": "cat-123"})
        ctx = MagicMock()
        ctx.client_context = None

        result = handler_module.lambda_handler(event, ctx)

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["cat_id"] == "cat-123"

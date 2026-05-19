"""Baseline tests for the feeding Lambda handler.

Validates:
- Handler module imports without error
- Handler returns 2xx for a valid API Gateway proxy event (GET with cat_id)
- Handler returns 2xx for a valid POST event (record feeding)
"""
import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_HANDLER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "handler.py")
_MODULE_NAME = "feeding_handler"


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """Set required environment variables before handler import."""
    monkeypatch.setenv("FEEDING_EVENTS_TABLE", "test-feeding-events")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("POWERTOOLS_METRICS_NAMESPACE", "CatDemo")
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "feeding")


@pytest.fixture()
def mock_handler():
    """Import the handler module with mocked boto3."""
    mock_table = MagicMock()
    mock_ddb = MagicMock()
    mock_ddb.Table.return_value = mock_table

    with patch("boto3.resource", return_value=mock_ddb):
        if _MODULE_NAME in sys.modules:
            del sys.modules[_MODULE_NAME]

        spec = importlib.util.spec_from_file_location(_MODULE_NAME, _HANDLER_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = mod
        spec.loader.exec_module(mod)

        yield mod, mock_table

    if _MODULE_NAME in sys.modules:
        del sys.modules[_MODULE_NAME]


def _make_api_gw_event(method="GET", path="/feedings", query_params=None, body=None):
    """Create a representative API Gateway proxy event."""
    return {
        "httpMethod": method,
        "path": path,
        "queryStringParameters": query_params,
        "body": json.dumps(body) if body else None,
        "headers": {"Content-Type": "application/json"},
        "requestContext": {
            "requestId": "test-request-id",
            "stage": "prod",
        },
        "pathParameters": None,
        "isBase64Encoded": False,
    }


class TestHandlerImport:
    """Test that the handler module can be imported without error."""

    def test_import_handler_module(self, mock_handler):
        """Handler module imports successfully when DynamoDB is mocked."""
        mod, _ = mock_handler
        assert mod is not None
        assert hasattr(mod, "lambda_handler")


class TestHandlerInvocation:
    """Test handler invocation with mocked AWS services."""

    def test_get_feedings_returns_200(self, mock_handler):
        """GET /feedings?cat_id=cat-1 returns statusCode 200."""
        mod, mock_table = mock_handler
        mock_table.query.return_value = {"Items": []}

        event = _make_api_gw_event(
            method="GET",
            query_params={"cat_id": "cat-1"},
        )
        context = MagicMock()
        context.client_context = None

        response = mod.lambda_handler(event, context)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert isinstance(body, list)

    def test_post_feeding_returns_201(self, mock_handler):
        """POST /feedings with valid body returns statusCode 201."""
        mod, mock_table = mock_handler
        mock_table.put_item.return_value = {}

        event = _make_api_gw_event(
            method="POST",
            body={
                "cat_id": "cat-1",
                "amount_grams": 50,
                "food_type": "wet",
            },
        )
        context = MagicMock()
        context.client_context = None

        response = mod.lambda_handler(event, context)

        assert response["statusCode"] == 201
        body = json.loads(response["body"])
        assert body["cat_id"] == "cat-1"
        assert body["food_type"] == "wet"

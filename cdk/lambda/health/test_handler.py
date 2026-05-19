"""Baseline tests for the health Lambda handler.

Validates:
- Handler module imports without error
- Handler returns 2xx for a valid API Gateway proxy event (GET /health/{cat_id})
- Handler returns 2xx for alerts route (GET /health/{cat_id}/alerts)
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    """Set required environment variables before importing the handler."""
    monkeypatch.setenv("HEALTH_METRICS_TABLE", "test-health-metrics")
    monkeypatch.setenv("HEALTH_ALERTS_TABLE", "test-health-alerts")
    monkeypatch.setenv("POWERTOOLS_SERVICE_NAME", "health")
    monkeypatch.setenv("POWERTOOLS_METRICS_NAMESPACE", "CatDemo")


_HANDLER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "handler.py")
_MODULE_NAME = "health_handler"


@pytest.fixture()
def reload_handler():
    """Reload the handler module with mocked boto3 DynamoDB resource."""
    mock_table = MagicMock()
    mock_table.query.return_value = {"Items": []}

    mock_ddb = MagicMock()
    mock_ddb.Table.return_value = mock_table

    with patch("boto3.resource", return_value=mock_ddb):
        # Remove cached module to force reimport with mock
        if _MODULE_NAME in sys.modules:
            del sys.modules[_MODULE_NAME]

        import importlib.util
        spec = importlib.util.spec_from_file_location(_MODULE_NAME, _HANDLER_PATH)
        handler = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = handler
        spec.loader.exec_module(handler)

        yield handler, mock_table

    # Cleanup
    if _MODULE_NAME in sys.modules:
        del sys.modules[_MODULE_NAME]


def _make_apigw_event(method="GET", resource="/health/{cat_id}", cat_id="cat-123"):
    """Create a representative API Gateway proxy event."""
    return {
        "httpMethod": method,
        "resource": resource,
        "path": resource.replace("{cat_id}", cat_id),
        "pathParameters": {"cat_id": cat_id},
        "queryStringParameters": None,
        "headers": {"Content-Type": "application/json"},
        "body": None,
        "isBase64Encoded": False,
        "requestContext": {
            "resourceId": "test",
            "resourcePath": resource,
            "httpMethod": method,
            "requestId": "test-request-id",
            "identity": {},
            "stage": "test",
        },
    }


def test_handler_module_imports(reload_handler):
    """Test that the handler module imports without raising any exception."""
    handler, _ = reload_handler
    assert handler is not None
    assert hasattr(handler, "lambda_handler")


def test_handler_get_health_metrics_returns_2xx(reload_handler):
    """Test handler returns 2xx statusCode for GET /health/{cat_id}."""
    handler, mock_table = reload_handler
    mock_table.query.return_value = {
        "Items": [{"cat_id": "cat-123", "metric": "weight", "value": 4.5}]
    }

    event = _make_apigw_event(method="GET", resource="/health/{cat_id}", cat_id="cat-123")
    context = MagicMock()
    context.client_context = None

    response = handler.lambda_handler(event, context)

    assert isinstance(response, dict)
    assert "statusCode" in response
    assert 200 <= response["statusCode"] <= 299


def test_handler_get_health_alerts_returns_2xx(reload_handler):
    """Test handler returns 2xx statusCode for GET /health/{cat_id}/alerts."""
    handler, mock_table = reload_handler
    mock_table.query.return_value = {
        "Items": [{"cat_id": "cat-123", "alert": "low_activity"}]
    }

    event = _make_apigw_event(method="GET", resource="/health/{cat_id}/alerts", cat_id="cat-123")
    context = MagicMock()
    context.client_context = None

    response = handler.lambda_handler(event, context)

    assert isinstance(response, dict)
    assert "statusCode" in response
    assert 200 <= response["statusCode"] <= 299

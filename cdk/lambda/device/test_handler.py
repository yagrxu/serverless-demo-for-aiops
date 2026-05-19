"""Baseline tests for the device Lambda handler.

Validates:
- Handler module imports without error
- Handler returns 2xx statusCode for a valid API Gateway proxy event
- AWS services (DynamoDB) are mocked — no real AWS calls
"""
import json
import importlib
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _set_env(monkeypatch):
    """Set required environment variables before importing the handler."""
    monkeypatch.setenv("DEVICES_TABLE", "test-devices")
    monkeypatch.setenv("DEVICE_TELEMETRY_TABLE", "test-device-telemetry")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("POWERTOOLS_METRICS_NAMESPACE", "CatDemo")


def _load_handler():
    """Import the handler module using importlib (avoids 'lambda' keyword issue in path)."""
    handler_dir = os.path.dirname(os.path.abspath(__file__))
    if handler_dir not in sys.path:
        sys.path.insert(0, handler_dir)
    # Remove cached module to pick up fresh env vars and mocks
    if "handler" in sys.modules:
        del sys.modules["handler"]
    return importlib.import_module("handler")


def _make_apigw_event(method="GET", resource="/devices", path_params=None, body=None):
    """Create a representative API Gateway proxy event."""
    return {
        "httpMethod": method,
        "resource": resource,
        "path": resource,
        "pathParameters": path_params,
        "queryStringParameters": None,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body) if body else None,
        "requestContext": {
            "requestId": "test-request-id",
            "stage": "test",
        },
        "isBase64Encoded": False,
    }


def _make_context():
    """Create a mock Lambda context."""
    ctx = MagicMock()
    ctx.client_context = None
    ctx.function_name = "test-device"
    ctx.memory_limit_in_mb = 128
    ctx.invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test"
    ctx.aws_request_id = "test-request-id"
    return ctx


def test_handler_module_imports():
    """Test that the handler module imports without error."""
    with patch("boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        handler_module = _load_handler()
        assert handler_module is not None
        assert hasattr(handler_module, "lambda_handler")


def test_handler_list_devices_returns_2xx():
    """Test that handler returns 2xx for GET /devices."""
    with patch("boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_table.scan.return_value = {"Items": []}
        mock_resource.return_value.Table.return_value = mock_table

        handler_module = _load_handler()

        event = _make_apigw_event(method="GET", resource="/devices")
        response = handler_module.lambda_handler(event, _make_context())

        assert 200 <= response["statusCode"] <= 299


def test_handler_get_device_returns_2xx():
    """Test that handler returns 2xx for GET /devices/{id} with existing device."""
    with patch("boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {"device_id": "dev-001", "name": "Feeder Alpha", "status": "online"}
        }
        mock_resource.return_value.Table.return_value = mock_table

        handler_module = _load_handler()

        event = _make_apigw_event(
            method="GET",
            resource="/devices/{id}",
            path_params={"id": "dev-001"},
        )
        response = handler_module.lambda_handler(event, _make_context())

        assert 200 <= response["statusCode"] <= 299


def test_handler_post_command_returns_2xx():
    """Test that handler returns 2xx for POST /devices/{id}/commands."""
    with patch("boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}
        mock_resource.return_value.Table.return_value = mock_table

        handler_module = _load_handler()

        event = _make_apigw_event(
            method="POST",
            resource="/devices/{id}/commands",
            path_params={"id": "dev-001"},
            body={"command": "feed", "args": {"amount": 50}},
        )
        response = handler_module.lambda_handler(event, _make_context())

        assert 200 <= response["statusCode"] <= 299

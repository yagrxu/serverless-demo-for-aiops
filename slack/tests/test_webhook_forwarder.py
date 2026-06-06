"""Integration-style tests for the webhook forwarder Lambda.

These tests verify the handler end-to-end with mocked external services
(Secrets Manager, HTTP endpoint).
"""

import json
from unittest.mock import MagicMock, patch

import sys
import importlib
from pathlib import Path

_wf_path = str(Path(__file__).resolve().parent.parent / "lambda" / "webhook-forwarder")
sys.path.insert(0, _wf_path)

# Import under a unique name to avoid collision with slack-handler's handler.py
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "webhook_handler",
    Path(__file__).resolve().parent.parent / "lambda" / "webhook-forwarder" / "handler.py",
)
_wh_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_wh_module)

build_webhook_payload = _wh_module.build_webhook_payload
compute_hmac_signature = _wh_module.compute_hmac_signature
lambda_handler = _wh_module.lambda_handler
validate_sns_message = _wh_module.validate_sns_message


def _make_sns_event(alarm_name="test-alarm", state="ALARM", reason="Threshold crossed", timestamp="2026-01-15T10:00:00.000Z"):
    """Build a synthetic SNS event matching the Lambda trigger format."""
    message = {
        "AlarmName": alarm_name,
        "NewStateValue": state,
        "NewStateReason": reason,
        "StateChangeTime": timestamp,
    }
    return {"Records": [{"Sns": {"Message": json.dumps(message)}}]}


class TestValidateSnsMessage:
    def test_valid_message_passes(self):
        msg = {
            "AlarmName": "test",
            "NewStateValue": "ALARM",
            "NewStateReason": "reason",
            "StateChangeTime": "2026-01-01T00:00:00Z",
        }
        # Should not raise
        validate_sns_message(msg)

    def test_missing_alarm_name_raises(self):
        msg = {
            "NewStateValue": "ALARM",
            "NewStateReason": "reason",
            "StateChangeTime": "2026-01-01T00:00:00Z",
        }
        try:
            validate_sns_message(msg)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "AlarmName" in str(e)

    def test_empty_field_raises(self):
        msg = {
            "AlarmName": "",
            "NewStateValue": "ALARM",
            "NewStateReason": "reason",
            "StateChangeTime": "2026-01-01T00:00:00Z",
        }
        try:
            validate_sns_message(msg)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "AlarmName" in str(e)


class TestBuildWebhookPayload:
    def test_maps_fields_correctly(self):
        msg = {
            "AlarmName": "aiops-cat-demo-feeding-errors",
            "NewStateValue": "ALARM",
            "NewStateReason": "Threshold Crossed",
            "StateChangeTime": "2026-01-15T10:00:00.000Z",
        }
        payload = build_webhook_payload(msg)

        assert payload["eventType"] == "incident"
        assert payload["action"] == "created"
        assert payload["priority"] == "HIGH"
        assert payload["title"] == "aiops-cat-demo-feeding-errors"
        assert payload["description"] == "Threshold Crossed"
        assert payload["timestamp"]  # current time, not the alarm time
        assert payload["service"] == "aiops-cat-demo"
        assert "aiops-cat-demo-feeding-errors" in payload["incidentId"]


class TestComputeHmacSignature:
    def test_deterministic(self):
        sig1 = compute_hmac_signature('{"key":"value"}', "secret", "2026-01-01T00:00:00Z")
        sig2 = compute_hmac_signature('{"key":"value"}', "secret", "2026-01-01T00:00:00Z")
        assert sig1 == sig2

    def test_different_secret_different_sig(self):
        sig1 = compute_hmac_signature('{"key":"value"}', "secret1", "2026-01-01T00:00:00Z")
        sig2 = compute_hmac_signature('{"key":"value"}', "secret2", "2026-01-01T00:00:00Z")
        assert sig1 != sig2


class TestLambdaHandler:
    def test_successful_forwarding(self):
        event = _make_sns_event()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.data = b"ok"

        mock_pool = MagicMock()
        mock_pool.request.return_value = mock_response

        mock_secret = {"url": "https://devops-agent.example.com/webhook", "hmac_secret": "test-secret"}

        with patch.object(_wh_module, "http", mock_pool), patch.object(_wh_module, "get_secret", return_value=mock_secret):
            result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        mock_pool.request.assert_called_once()
        call_args = mock_pool.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "https://devops-agent.example.com/webhook"

    def test_non_2xx_raises(self):
        event = _make_sns_event()
        mock_response = MagicMock()
        mock_response.status = 403
        mock_response.data = b"forbidden"

        mock_pool = MagicMock()
        mock_pool.request.return_value = mock_response

        mock_secret = {"url": "https://example.com/webhook", "hmac_secret": "secret"}

        with patch.object(_wh_module, "http", mock_pool), patch.object(_wh_module, "get_secret", return_value=mock_secret):
            try:
                lambda_handler(event, None)
                assert False, "Should have raised RuntimeError"
            except RuntimeError as e:
                assert "403" in str(e)

    def test_missing_fields_raises(self):
        event = {"Records": [{"Sns": {"Message": json.dumps({"AlarmName": "test"})}}]}
        mock_secret = {"url": "https://example.com/webhook", "hmac_secret": "secret"}

        with patch.object(_wh_module, "get_secret", return_value=mock_secret):
            try:
                lambda_handler(event, None)
                assert False, "Should have raised ValueError"
            except ValueError:
                pass

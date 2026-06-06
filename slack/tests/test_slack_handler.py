"""Integration-style tests for the Slack handler Lambda.

These tests verify the handler end-to-end with mocked external services.
"""

import hashlib
import hmac as hmac_mod
import json
import time
from unittest.mock import MagicMock, patch

import sys
import importlib.util
from pathlib import Path

_sh_path = Path(__file__).resolve().parent.parent / "lambda" / "slack-handler" / "handler.py"
_spec = importlib.util.spec_from_file_location("slack_handler", _sh_path)
_sh_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sh_module)

verify_slack_signature = _sh_module.verify_slack_signature
is_bot_event = _sh_module.is_bot_event
extract_user_text = _sh_module.extract_user_text
truncate = _sh_module.truncate
handle_url_verification = _sh_module.handle_url_verification
lambda_handler = _sh_module.lambda_handler


def _compute_slack_sig(body: str, timestamp: str, secret: str) -> str:
    """Compute a valid Slack signature for testing."""
    sig_basestring = f"v0:{timestamp}:{body}"
    return "v0=" + hmac_mod.new(
        secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class TestVerifySlackSignature:
    def test_valid_signature_accepted(self):
        body = '{"type":"event_callback"}'
        secret = "test_signing_secret"
        timestamp = str(int(time.time()))
        sig = _compute_slack_sig(body, timestamp, secret)

        assert verify_slack_signature(body, timestamp, sig, secret) is True

    def test_wrong_signature_rejected(self):
        body = '{"type":"event_callback"}'
        secret = "correct_secret"
        timestamp = str(int(time.time()))
        wrong_sig = "v0=0000000000000000000000000000000000000000000000000000000000000000"

        assert verify_slack_signature(body, timestamp, wrong_sig, secret) is False

    def test_expired_timestamp_rejected(self):
        body = '{"type":"event_callback"}'
        secret = "test_secret"
        old_timestamp = str(int(time.time()) - 400)  # 6+ minutes ago
        sig = _compute_slack_sig(body, old_timestamp, secret)

        assert verify_slack_signature(body, old_timestamp, sig, secret) is False


class TestIsBotEvent:
    def test_bot_event_detected(self):
        assert is_bot_event({"bot_id": "B123", "text": "hello"}) is True

    def test_user_event_not_flagged(self):
        assert is_bot_event({"user": "U123", "text": "hello"}) is False


class TestExtractUserText:
    def test_strips_mention(self):
        event = {"text": "<@U12345> what is the error rate?", "user": "U999", "channel": "C123"}
        result = extract_user_text(event)
        assert "<@U12345>" not in result
        assert "what is the error rate?" in result

    def test_truncates_long_text(self):
        event = {"text": "x" * 5000, "user": "U999", "channel": "C123"}
        result = extract_user_text(event)
        assert len(result) <= 4000

    def test_empty_text_after_mention(self):
        event = {"text": "<@U12345>   ", "user": "U999", "channel": "C123"}
        result = extract_user_text(event)
        assert result.strip() == ""


class TestTruncate:
    def test_short_message_unchanged(self):
        assert truncate("hello") == "hello"

    def test_long_message_truncated(self):
        result = truncate("x" * 5000)
        assert len(result) == 4000


class TestHandleUrlVerification:
    def test_echoes_challenge(self):
        body = {"type": "url_verification", "challenge": "abc123xyz"}
        response = handle_url_verification(body)
        assert response["statusCode"] == 200
        assert json.loads(response["body"])["challenge"] == "abc123xyz"


class TestLambdaHandler:
    def _make_event(self, body: str, signing_secret: str):
        """Build an API Gateway event with valid Slack signature."""
        timestamp = str(int(time.time()))
        sig = _compute_slack_sig(body, timestamp, signing_secret)
        return {
            "headers": {
                "x-slack-signature": sig,
                "x-slack-request-timestamp": timestamp,
                "content-type": "application/json",
            },
            "body": body,
            "isBase64Encoded": False,
        }

    def test_url_verification(self):
        signing_secret = "test_secret"
        body = json.dumps({"type": "url_verification", "challenge": "test_challenge_123"})
        event = self._make_event(body, signing_secret)

        mock_secrets = {
            "signing_secret": signing_secret,
            "bot_token": "xoxb-fake",
            "devops_agent_space_id": "space-123",
        }

        with patch.object(_sh_module, "get_secret", return_value=mock_secrets):
            result = lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert json.loads(result["body"])["challenge"] == "test_challenge_123"

    def test_invalid_signature_returns_401(self):
        event = {
            "headers": {
                "x-slack-signature": "v0=invalid",
                "x-slack-request-timestamp": str(int(time.time())),
                "content-type": "application/json",
            },
            "body": '{"type":"event_callback"}',
            "isBase64Encoded": False,
        }

        mock_secrets = {
            "signing_secret": "real_secret",
            "bot_token": "xoxb-fake",
            "devops_agent_space_id": "space-123",
        }

        with patch.object(_sh_module, "get_secret", return_value=mock_secrets):
            result = lambda_handler(event, None)

        assert result["statusCode"] == 401

    def test_bot_event_ignored(self):
        signing_secret = "test_secret"
        body = json.dumps({
            "type": "event_callback",
            "event": {"type": "app_mention", "bot_id": "B123", "text": "echo", "channel": "C1", "user": "U1"},
        })
        event = self._make_event(body, signing_secret)

        mock_secrets = {
            "signing_secret": signing_secret,
            "bot_token": "xoxb-fake",
            "devops_agent_space_id": "space-123",
        }

        with patch.object(_sh_module, "get_secret", return_value=mock_secrets):
            result = lambda_handler(event, None)

        assert result["statusCode"] == 200

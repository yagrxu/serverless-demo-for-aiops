"""Tests for the Webhook Forwarder Lambda (Path A).

Rewritten to match the live-verified handler implementation:
  - signature is BASE64 of the raw HMAC-SHA256 digest (NOT hex), no "sha256=" prefix
  - the signed/header timestamp is the payload's own (current-time) timestamp
  - the secret bundle uses keys {"url", "hmac_secret"}
  - incidentId is unique per invocation

Unit tests use plain pytest; property tests use Hypothesis (>=100 examples).
All boto3 / network calls are mocked — runs with no AWS creds, no network.
"""

import base64
import hashlib
import hmac
import importlib.util
import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Robustly load the sibling handler.py by absolute path. All three lambda dirs
# contain a file literally named "handler.py", so a plain `import handler`
# would collide across directories. Loading by path under a unique module name
# avoids that collision entirely.
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location(
    "handler_under_test", pathlib.Path(__file__).resolve().parent / "handler.py"
)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Text without lone surrogates / control chars, safe to .encode("utf-8").
_safe_chars = st.characters(min_codepoint=32, max_codepoint=0x10FFFF, blacklist_categories=("Cs",))
safe_text = st.text(alphabet=_safe_chars, min_size=0, max_size=200)
nonempty_safe_text = st.text(alphabet=_safe_chars, min_size=1, max_size=200)


@st.composite
def valid_sns_messages(draw):
    """A complete, valid SNS alarm message (all four required fields present)."""
    return {
        "AlarmName": draw(nonempty_safe_text),
        "NewStateValue": draw(st.sampled_from(["ALARM", "OK", "INSUFFICIENT_DATA"])),
        "NewStateReason": draw(nonempty_safe_text),
        "StateChangeTime": draw(nonempty_safe_text),
    }


@st.composite
def sns_messages_missing_fields(draw):
    """An SNS message where >=1 required field is omitted, empty, or None."""
    fields = ["AlarmName", "NewStateValue", "NewStateReason", "StateChangeTime"]
    to_break = draw(
        st.lists(st.sampled_from(fields), min_size=1, max_size=4, unique=True)
    )
    message = {}
    for field in fields:
        if field in to_break:
            action = draw(st.sampled_from(["omit", "empty", "none"]))
            if action == "empty":
                message[field] = ""
            elif action == "none":
                message[field] = None
            # "omit" -> leave the key out entirely
        else:
            message[field] = draw(nonempty_safe_text)
    return message


def _valid_event():
    sns_message = {
        "AlarmName": "feeding-fn-errors",
        "NewStateValue": "ALARM",
        "NewStateReason": "Threshold crossed: errors > 5",
        "StateChangeTime": "2024-01-01T00:00:00.000Z",
    }
    return {"Records": [{"Sns": {"Message": json.dumps(sns_message)}}]}


# ---------------------------------------------------------------------------
# Property 1: build_webhook_payload preserves alarm data + unique incidentId
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(sns_message=valid_sns_messages())
def test_payload_preserves_data_and_unique_incident_id(sns_message):
    """Property 1: webhook payload preserves alarm data and gives each build a
    UNIQUE incidentId / Validates: Requirements 1.2"""
    p1 = handler.build_webhook_payload(sns_message)
    p2 = handler.build_webhook_payload(sns_message)

    # Field mapping
    assert p1["title"] == sns_message["AlarmName"]
    assert p1["description"] == sns_message["NewStateReason"]
    assert p1["service"] == handler.SERVICE_NAME
    assert p1["eventType"] == "incident"
    assert p1["action"] == "created"
    assert p1["priority"] == "HIGH"
    # timestamp is the current signing time (ISO-8601, "...Z"), not StateChangeTime
    assert isinstance(p1["timestamp"], str) and p1["timestamp"].endswith("Z")

    # incidentId is unique per invocation for identical input
    assert p1["incidentId"] != p2["incidentId"]
    assert sns_message["AlarmName"] in p1["incidentId"]


# ---------------------------------------------------------------------------
# Property 2: HMAC webhook signing is deterministic, base64, verifiable
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    body_str=safe_text,
    secret=st.text(alphabet=_safe_chars, min_size=1, max_size=100),
    other_secret=st.text(alphabet=_safe_chars, min_size=1, max_size=100),
    timestamp=nonempty_safe_text,
)
def test_hmac_signature_is_base64_deterministic_verifiable(
    body_str, secret, other_secret, timestamp
):
    """Property 2: HMAC webhook signing is deterministic, base64-encoded, and
    verifiable / Validates: Requirements 1.3, 6.1, 6.3"""
    sig1 = handler.compute_hmac_signature(body_str, secret, timestamp)
    sig2 = handler.compute_hmac_signature(body_str, secret, timestamp)

    # Deterministic
    assert sig1 == sig2

    # Base64 (NOT hex) of the raw digest — decodes to exactly 32 bytes (SHA-256)
    assert not sig1.startswith("sha256=")
    decoded = base64.b64decode(sig1)
    assert len(decoded) == 32

    # Matches an independent base64(HMAC-SHA256) computation over "{ts}:{body}"
    expected = base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}:{body_str}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    assert sig1 == expected

    # A different secret yields a different signature
    assume(secret != other_secret)
    assert handler.compute_hmac_signature(body_str, other_secret, timestamp) != sig1


# ---------------------------------------------------------------------------
# Property 3: missing required fields are rejected
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(message=sns_messages_missing_fields())
def test_missing_fields_rejected(message):
    """Property 3: validate_sns_message raises when a required field is missing
    or empty / Validates: Requirements 1.8"""
    with pytest.raises(ValueError):
        handler.validate_sns_message(message)


def test_validate_accepts_complete_message():
    """All four fields present and non-empty -> no exception."""
    handler.validate_sns_message(
        {
            "AlarmName": "a",
            "NewStateValue": "ALARM",
            "NewStateReason": "r",
            "StateChangeTime": "t",
        }
    )


# ---------------------------------------------------------------------------
# Property 4: non-2xx webhook responses propagate as exceptions
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(status_code=st.integers(min_value=100, max_value=599).filter(lambda s: s < 200 or s >= 300))
def test_non_2xx_propagates_as_exception(status_code):
    """Property 4: lambda_handler raises (forward_incident -> RuntimeError) on a
    non-2xx webhook response / Validates: Requirements 1.6"""
    event = _valid_event()

    mock_response = MagicMock()
    mock_response.status = status_code
    mock_response.data = b"error body"
    mock_http = MagicMock()
    mock_http.request.return_value = mock_response

    secret = {"url": "https://example.com/webhook", "hmac_secret": "topsecret"}

    with patch.object(handler, "http", mock_http), patch.object(handler, "get_secret", return_value=secret):
        with pytest.raises(RuntimeError, match=r"DevOps Agent webhook returned \d+"):
            handler.lambda_handler(event, None)


# ---------------------------------------------------------------------------
# Unit: happy-path lambda_handler
# ---------------------------------------------------------------------------


def test_lambda_handler_happy_path_signs_and_posts():
    """200 response: POST carries a base64 signature (no 'sha256=' prefix) and an
    x-amzn-event-timestamp equal to the payload's timestamp."""
    event = _valid_event()

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.data = b"ok"
    mock_http = MagicMock()
    mock_http.request.return_value = mock_response

    secret_value = "topsecret"
    secret = {"url": "https://example.com/webhook", "hmac_secret": secret_value}

    with patch.object(handler, "http", mock_http), patch.object(handler, "get_secret", return_value=secret):
        result = handler.lambda_handler(event, None)

    assert result == {"statusCode": 200, "forwarded": 1}

    mock_http.request.assert_called_once()
    call = mock_http.request.call_args
    assert call.args[0] == "POST"
    assert call.args[1] == secret["url"]

    headers = call.kwargs["headers"]
    body_bytes = call.kwargs["body"]
    sig = headers["x-amzn-event-signature"]
    ts = headers["x-amzn-event-timestamp"]

    # No "sha256=" prefix; decodes to a 32-byte digest
    assert not sig.startswith("sha256=")
    assert len(base64.b64decode(sig)) == 32

    # The header timestamp equals the timestamp baked into the signed body
    payload = json.loads(body_bytes)
    assert ts == payload["timestamp"]

    # Signature recomputes correctly over "{ts}:{body}"
    expected = base64.b64encode(
        hmac.new(
            secret_value.encode("utf-8"),
            f"{ts}:{body_bytes.decode('utf-8')}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    assert sig == expected

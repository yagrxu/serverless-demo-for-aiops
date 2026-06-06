"""Tests for the Slack Handler Lambda (Path B, ack phase).

Rewritten to match the live-verified handler implementation:
  - Slack's own signature scheme: hex digest, "v0=" prefix, 5-minute replay window
  - secret bundle uses keys {"signing_secret", "bot_token"}
  - real questions fan out via dispatch_worker (async lambda invoke); the ack
    Lambda never calls the agent inline
  - empty / whitespace questions post a usage hint instead of dispatching

Unit tests use plain pytest; property tests use Hypothesis (>=100 examples).
All boto3 / network calls are mocked — runs with no AWS creds, no network.
"""

import hashlib
import hmac
import importlib.util
import json
import pathlib
import time
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Load the sibling handler.py by absolute path (avoids the cross-directory
# "handler" module-name collision shared by all three lambda dirs).
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location(
    "handler_under_test", pathlib.Path(__file__).resolve().parent / "handler.py"
)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


# ---------------------------------------------------------------------------
# Strategies / helpers
# ---------------------------------------------------------------------------

_safe_chars = st.characters(min_codepoint=32, max_codepoint=0x10FFFF, blacklist_categories=("Cs",))
printable_text = st.text(alphabet=_safe_chars, min_size=0, max_size=300)
nonempty_text = st.text(alphabet=_safe_chars, min_size=1, max_size=300)
signing_secrets = st.text(alphabet="abcdef0123456789", min_size=8, max_size=64)
challenge_strings = st.text(alphabet=_safe_chars, min_size=1, max_size=200)

SECRET = {"signing_secret": "8f742231b10e8888abcd99yyyzzz", "bot_token": "xoxb-test-token"}


def _slack_sig(body: str, timestamp: str, signing_secret: str) -> str:
    """Compute a real Slack v0= hex signature for the given body/timestamp."""
    basestring = f"v0:{timestamp}:{body}"
    return "v0=" + hmac.new(
        signing_secret.encode("utf-8"), basestring.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _event(raw_body: str, content_type: str, timestamp: str | None = None):
    """Build an API Gateway event with a VALID Slack signature for SECRET."""
    ts = timestamp if timestamp is not None else str(int(time.time()))
    sig = _slack_sig(raw_body, ts, SECRET["signing_secret"])
    return {
        "headers": {
            "Content-Type": content_type,
            "X-Slack-Signature": sig,
            "X-Slack-Request-Timestamp": ts,
        },
        "body": raw_body,
        "isBase64Encoded": False,
    }


@st.composite
def slack_ids(draw):
    """Slack user/channel ids: a leading letter then [A-Z0-9]+ (mention-strippable)."""
    rest = draw(st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", min_size=5, max_size=10))
    return "U" + rest


@st.composite
def whitespace_strings(draw):
    length = draw(st.integers(min_value=0, max_value=40))
    return draw(st.text(alphabet=" \t\n\r\x0b\x0c", min_size=length, max_size=length))


# ---------------------------------------------------------------------------
# Property 5: signature verification accepts valid, rejects invalid / stale
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(body=printable_text, signing_secret=signing_secrets)
def test_valid_signature_accepted(body, signing_secret):
    """Property 5: verify_slack_signature accepts a correct v0= hex signature with
    a current timestamp / Validates: Requirements 2.2, 2.3, 5.1, 5.2, 5.3, 5.4"""
    timestamp = str(int(time.time()))
    sig = _slack_sig(body, timestamp, signing_secret)
    assert handler.verify_slack_signature(body, timestamp, sig, signing_secret) is True


@settings(max_examples=100)
@given(body=printable_text, signing_secret=signing_secrets, wrong_secret=signing_secrets)
def test_wrong_signature_rejected(body, signing_secret, wrong_secret):
    """Property 5: a signature computed with the wrong secret is rejected /
    Validates: Requirements 2.2, 2.3, 5.1, 5.2, 5.3, 5.4"""
    assume(signing_secret != wrong_secret)
    timestamp = str(int(time.time()))
    wrong_sig = _slack_sig(body, timestamp, wrong_secret)
    assert handler.verify_slack_signature(body, timestamp, wrong_sig, signing_secret) is False


@settings(max_examples=100)
@given(body=printable_text, signing_secret=signing_secrets)
def test_stale_timestamp_rejected(body, signing_secret):
    """Property 5: a timestamp older than 5 minutes is rejected even with an
    otherwise-valid signature / Validates: Requirements 2.2, 2.3, 5.1, 5.2, 5.3, 5.4"""
    old_ts = str(int(time.time()) - handler.TIMESTAMP_MAX_AGE_SECONDS - 60)
    sig = _slack_sig(body, old_ts, signing_secret)
    assert handler.verify_slack_signature(body, old_ts, sig, signing_secret) is False


# ---------------------------------------------------------------------------
# Property 6: URL verification echoes challenge
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(challenge=challenge_strings)
def test_url_verification_echoes_challenge(challenge):
    """Property 6: handle_url_verification echoes the challenge in the response
    body / Validates: Requirements 2.4"""
    resp = handler.handle_url_verification({"type": "url_verification", "challenge": challenge})
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["challenge"] == challenge


def test_lambda_handler_url_verification_echoes_challenge():
    """End-to-end url_verification routing (signed) echoes the challenge."""
    body = json.dumps({"type": "url_verification", "challenge": "abc-challenge-123"})
    event = _event(body, "application/json")
    with patch.object(handler, "get_secret", return_value=SECRET):
        resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["challenge"] == "abc-challenge-123"


# ---------------------------------------------------------------------------
# Property 7 / 11: valid app_mention -> 200 + exactly one dispatch_worker call
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    question=nonempty_text.filter(lambda s: s.strip() != "" and "<@" not in s),
    bot_id=slack_ids(),
    channel_id=slack_ids(),
    user_id=slack_ids(),
)
def test_app_mention_dispatches_worker_once(question, bot_id, channel_id, user_id):
    """Property 7/11: a valid app_mention with non-whitespace text returns 200 and
    calls dispatch_worker exactly once with stripped text, channel_id, user_id /
    Validates: Requirements 2.5, 2.8, 2.9"""
    inner_text = f"<@{bot_id}> {question}"
    expected_text = handler.truncate(question.strip())

    body = json.dumps(
        {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": inner_text,
                "channel": channel_id,
                "user": user_id,
            },
        }
    )
    event = _event(body, "application/json")

    with (
        patch.object(handler, "get_secret", return_value=SECRET),
        patch.object(handler, "dispatch_worker") as mock_dispatch,
    ):
        resp = handler.lambda_handler(event, None)

    assert resp["statusCode"] == 200
    mock_dispatch.assert_called_once_with(expected_text, channel_id, user_id)


# ---------------------------------------------------------------------------
# Property 9: bot events are ignored (200, no dispatch)
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(bot_id=nonempty_text)
def test_bot_event_ignored(bot_id):
    """Property 9: a message event carrying a bot_id returns 200 and does NOT
    dispatch the worker / Validates: Requirements 2.10"""
    body = json.dumps(
        {
            "type": "event_callback",
            "event": {"type": "message", "bot_id": bot_id, "text": "beep boop", "channel": "C1"},
        }
    )
    event = _event(body, "application/json")

    with (
        patch.object(handler, "get_secret", return_value=SECRET),
        patch.object(handler, "dispatch_worker") as mock_dispatch,
        patch.object(handler, "_http") as mock_http,
    ):
        resp = handler.lambda_handler(event, None)

    assert resp["statusCode"] == 200
    mock_dispatch.assert_not_called()
    mock_http.request.assert_not_called()


def test_is_bot_event_detection():
    """is_bot_event is True iff a bot_id key is present."""
    assert handler.is_bot_event({"bot_id": "B123", "text": "x"}) is True
    assert handler.is_bot_event({"user": "U123", "text": "x"}) is False


# ---------------------------------------------------------------------------
# Property 10: whitespace-only mention -> usage hint, no dispatch
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(ws=whitespace_strings(), bot_id=slack_ids(), channel_id=slack_ids())
def test_whitespace_mention_posts_usage_hint(ws, bot_id, channel_id):
    """Property 10: an app_mention whose text is whitespace-only after stripping
    the mention posts a usage hint and does NOT dispatch the worker /
    Validates: Requirements 2.11"""
    body = json.dumps(
        {
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": f"<@{bot_id}>{ws}",
                "channel": channel_id,
                "user": "U999",
            },
        }
    )
    event = _event(body, "application/json")

    with (
        patch.object(handler, "get_secret", return_value=SECRET),
        patch.object(handler, "dispatch_worker") as mock_dispatch,
        patch.object(handler, "_http") as mock_http,
    ):
        resp = handler.lambda_handler(event, None)

    assert resp["statusCode"] == 200
    mock_dispatch.assert_not_called()
    mock_http.request.assert_called_once()  # usage hint posted


# ---------------------------------------------------------------------------
# Unit: extract_user_text strips mention and truncates to 4000
# ---------------------------------------------------------------------------


def test_extract_user_text_strips_mention():
    text = handler.extract_user_text({"text": "<@U12345BOT> how many alarms?"})
    assert text == "how many alarms?"
    assert "<@" not in text


def test_extract_user_text_truncates_to_limit():
    long_text = "<@U12345BOT> " + ("x" * 5000)
    result = handler.extract_user_text({"text": long_text})
    assert len(result) == handler.MAX_QUESTION_LENGTH == 4000


# ---------------------------------------------------------------------------
# Unit: invalid signature -> 401
# ---------------------------------------------------------------------------


def test_invalid_signature_returns_401():
    body = json.dumps({"type": "url_verification", "challenge": "c"})
    event = {
        "headers": {
            "Content-Type": "application/json",
            "X-Slack-Signature": "v0=deadbeef",
            "X-Slack-Request-Timestamp": str(int(time.time())),
        },
        "body": body,
        "isBase64Encoded": False,
    }
    with patch.object(handler, "get_secret", return_value=SECRET):
        resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 401


# ---------------------------------------------------------------------------
# Unit: slash command happy path / empty text
# ---------------------------------------------------------------------------


def test_slash_command_dispatches_worker():
    raw = urlencode(
        {
            "command": "/devops",
            "text": "investigate FeedingFn latency",
            "channel_id": "C12345",
            "user_id": "U67890",
        }
    )
    event = _event(raw, "application/x-www-form-urlencoded")

    with (
        patch.object(handler, "get_secret", return_value=SECRET),
        patch.object(handler, "dispatch_worker") as mock_dispatch,
    ):
        resp = handler.lambda_handler(event, None)

    assert resp["statusCode"] == 200
    mock_dispatch.assert_called_once_with(
        "investigate FeedingFn latency", "C12345", "U67890"
    )


def test_slash_command_empty_text_posts_usage_hint():
    raw = urlencode(
        {"command": "/devops", "text": "   ", "channel_id": "C12345", "user_id": "U67890"}
    )
    event = _event(raw, "application/x-www-form-urlencoded")

    with (
        patch.object(handler, "get_secret", return_value=SECRET),
        patch.object(handler, "dispatch_worker") as mock_dispatch,
        patch.object(handler, "_http") as mock_http,
    ):
        resp = handler.lambda_handler(event, None)

    assert resp["statusCode"] == 200
    mock_dispatch.assert_not_called()
    mock_http.request.assert_called_once()


# ---------------------------------------------------------------------------
# Unit: dispatch_worker issues exactly one async (Event) lambda invoke
# ---------------------------------------------------------------------------


def test_dispatch_worker_async_invoke():
    mock_client = MagicMock()
    with patch.object(handler, "_lambda", return_value=mock_client):
        handler.dispatch_worker("a question", "C1", "U1")

    mock_client.invoke.assert_called_once()
    kwargs = mock_client.invoke.call_args.kwargs
    assert kwargs["InvocationType"] == "Event"
    payload = json.loads(kwargs["Payload"])
    assert payload == {"question": "a question", "channel_id": "C1", "user_id": "U1"}

"""Tests for the Slack Worker Lambda (Path B, async phase).

Rewritten to match the live-verified handler implementation:
  - assume-role with a mandatory AgentSpaceId session tag, then a devops-agent client
  - send_message returns a streaming EventStream parsed into indexed content blocks
  - the final_response block is preferred over the duplicate streaming text block
  - investigation markers [[investigation:uuid:title]] render to Slack links
  - on any agent failure, an error message is posted back to the channel

Unit tests use plain pytest; property tests use Hypothesis (>=100 examples).
All boto3 / network calls are mocked — runs with no AWS creds, no network.
"""

import importlib.util
import pathlib
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
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


@st.composite
def _chunks(draw, s):
    """Split string `s` into arbitrarily-sized, order-preserving chunks."""
    chunks = []
    i = 0
    n = len(s)
    while i < n:
        step = draw(st.integers(min_value=1, max_value=n - i))
        chunks.append(s[i : i + step])
        i += step
    return chunks


def _start(index, block_type):
    return {"contentBlockStart": {"index": index, "type": block_type}}


def _delta(index, text):
    return {"contentBlockDelta": {"index": index, "delta": {"textDelta": {"text": text}}}}


def _block_events(index, block_type, chunks):
    events = [_start(index, block_type)]
    for ch in chunks:
        events.append(_delta(index, ch))
    return events


@st.composite
def stream_with_final(draw):
    """A stream containing a `text` (thinking) block AND a `final_response` block."""
    answer = "ANS:" + draw(st.text(alphabet=_safe_chars, min_size=1, max_size=120))
    thinking = "THINK:" + draw(st.text(alphabet=_safe_chars, min_size=0, max_size=120))
    answer_chunks = draw(_chunks(answer))
    thinking_chunks = draw(_chunks(thinking))
    return answer, thinking, answer_chunks, thinking_chunks


@st.composite
def stream_without_final(draw):
    """A stream containing only a `text` block (no final_response)."""
    answer = "ANS:" + draw(st.text(alphabet=_safe_chars, min_size=1, max_size=150))
    return answer, draw(_chunks(answer))


# filler / marker pieces that cannot accidentally form an investigation marker
_filler_alpha = "abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,!?"
filler_text = st.text(alphabet=_filler_alpha, min_size=0, max_size=40)
uuid_text = st.text(alphabet="abcdef0123456789-", min_size=1, max_size=36)
title_text = st.text(alphabet=_filler_alpha, min_size=1, max_size=30)


@st.composite
def marker_doc(draw):
    """Assemble an answer with N markers interleaved with safe filler text,
    returning (raw_text, expected_rendered, marker_count)."""
    n = draw(st.integers(min_value=0, max_value=5))
    raw_parts, expected_parts = [], []
    for _ in range(n):
        filler = draw(filler_text)
        uuid = draw(uuid_text)
        title = draw(title_text)
        raw_parts.append(filler)
        raw_parts.append(f"[[investigation:{uuid}:{title}]]")
        expected_parts.append(filler)
        expected_parts.append(f"<{handler.INVESTIGATION_CONSOLE_BASE}{uuid}|{title}>")
    trailing = draw(filler_text)
    raw_parts.append(trailing)
    expected_parts.append(trailing)
    return "".join(raw_parts), "".join(expected_parts), n


# ---------------------------------------------------------------------------
# Property 12: EventStream parsing reconstructs the final response
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=stream_with_final())
def test_parse_prefers_final_response(data):
    """Property 12: parse_agent_stream reassembles indexed text deltas and returns
    the final_response block (NOT the duplicate text block) when present, with no
    duplication / Validates: Requirements 2.6"""
    answer, thinking, answer_chunks, thinking_chunks = data

    events = []
    events += _block_events(0, "text", thinking_chunks)
    events += _block_events(1, "final_response", answer_chunks)

    parsed = handler.parse_agent_stream(events)

    # final_response is reconstructed exactly from its own deltas
    assert parsed["final_response"] == answer
    # the streaming/thinking text is kept separately, never appended to final_response
    assert parsed["streaming_text"] == thinking
    assert thinking not in parsed["final_response"]


@settings(max_examples=100)
@given(data=stream_without_final())
def test_parse_falls_back_to_text_blocks(data):
    """Property 12: with no final_response block present, parse_agent_stream falls
    back to the accumulated text blocks / Validates: Requirements 2.6"""
    answer, chunks = data
    events = _block_events(0, "text", chunks)

    parsed = handler.parse_agent_stream(events)

    assert parsed["final_response"] == ""
    assert parsed["streaming_text"] == answer
    # ask_devops_agent's selection logic: final_response or streaming_text
    assert (parsed["final_response"] or parsed["streaming_text"]) == answer


def test_parse_reassembles_text_blocks_in_index_order():
    """Multiple text blocks are concatenated in ascending index order."""
    events = []
    events += _block_events(2, "text", ["world"])
    events += _block_events(0, "text", ["hello "])
    parsed = handler.parse_agent_stream(events)
    assert parsed["streaming_text"] == "hello world"


# ---------------------------------------------------------------------------
# Property 13: investigation markers render as Slack links
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(doc=marker_doc())
def test_render_investigation_links(doc):
    """Property 13: render_investigation_links replaces each marker with a Slack
    link, leaves non-marker text unchanged, and produces exactly one link per
    marker / Validates: Requirements 2.6"""
    raw, expected, n = doc

    rendered = handler.render_investigation_links(raw)

    assert rendered == expected
    # exactly one console link per marker
    assert rendered.count(handler.INVESTIGATION_CONSOLE_BASE) == n
    # no raw markers survive
    assert "[[investigation:" not in rendered


def test_render_leaves_plain_text_unchanged():
    plain = "just a normal answer with no markers at all"
    assert handler.render_investigation_links(plain) == plain


def test_render_single_marker_shape():
    raw = "see [[investigation:abc-123:Latency spike]] now"
    rendered = handler.render_investigation_links(raw)
    assert rendered == (
        f"see <{handler.INVESTIGATION_CONSOLE_BASE}abc-123|Latency spike> now"
    )


# ---------------------------------------------------------------------------
# Property 14: agent failures post an error message
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(channel_id=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789C", min_size=1, max_size=12))
def test_agent_failure_posts_error_message(channel_id):
    """Property 14: when ask_devops_agent raises, lambda_handler posts an error
    message back to the originating channel / Validates: Requirements 2.7"""
    event = {"question": "why so slow?", "channel_id": channel_id, "user_id": "U1"}
    secret = {"bot_token": "xoxb-test", "agent_space_id": "space", "operator_role_arn": "arn"}

    posted = []

    def record_post(channel, text, bot_token, message_ts=None):
        posted.append((channel, text, bot_token))

    with (
        patch.object(handler, "get_secret", return_value=secret),
        patch.object(handler, "ask_devops_agent", side_effect=RuntimeError("boom")),
        patch.object(handler, "post_to_slack", side_effect=record_post),
    ):
        result = handler.lambda_handler(event, None)

    assert result["statusCode"] == 500
    assert len(posted) == 1
    posted_channel, posted_text, _ = posted[0]
    assert posted_channel == channel_id
    assert "could not be completed" in posted_text


# ---------------------------------------------------------------------------
# Unit: get_agent_client passes the mandatory AgentSpaceId session tag
# ---------------------------------------------------------------------------


def test_get_agent_client_assume_role_tags():
    """get_agent_client calls sts.assume_role with Tags containing the
    AgentSpaceId session tag, and returns a devops-agent client."""
    mock_sts = MagicMock()
    mock_sts.assume_role.return_value = {
        "Credentials": {
            "AccessKeyId": "AKIA-fake",
            "SecretAccessKey": "secret-fake",
            "SessionToken": "token-fake",
        }
    }
    mock_agent = MagicMock(name="devops-agent-client")

    def client_factory(service, **kwargs):
        return mock_sts if service == "sts" else mock_agent

    with patch.object(handler.boto3, "client", side_effect=client_factory):
        client = handler.get_agent_client("arn:aws:iam::123:role/op", "space-xyz")

    mock_sts.assume_role.assert_called_once()
    tags = mock_sts.assume_role.call_args.kwargs["Tags"]
    assert {"Key": "AgentSpaceId", "Value": "space-xyz"} in tags
    assert client is mock_agent


# ---------------------------------------------------------------------------
# Unit: truncate_message caps at 4000
# ---------------------------------------------------------------------------


def test_truncate_message_caps_at_4000():
    assert handler.truncate_message("x" * 5000) == "x" * handler.MAX_MESSAGE_LENGTH
    assert len(handler.truncate_message("x" * 5000)) == 4000
    # within limit is unchanged
    assert handler.truncate_message("short") == "short"


@settings(max_examples=100)
@given(text=st.text(alphabet=_safe_chars, min_size=0, max_size=9000))
def test_truncate_message_property(text):
    """Property 8: the message is capped at 4000 chars (prefix preserved) /
    Validates: Requirements 2.6"""
    result = handler.truncate_message(text)
    assert len(result) <= handler.MAX_MESSAGE_LENGTH
    if len(text) <= handler.MAX_MESSAGE_LENGTH:
        assert result == text
    else:
        assert result == text[: handler.MAX_MESSAGE_LENGTH]


# ---------------------------------------------------------------------------
# Unit: happy-path lambda_handler posts the agent answer
# ---------------------------------------------------------------------------


def test_lambda_handler_happy_path_posts_answer():
    """On success, lambda_handler posts the agent's answer to the channel."""
    event = {"question": "how many alarms?", "channel_id": "C12345", "user_id": "U1"}
    secret = {"bot_token": "xoxb-test", "agent_space_id": "space", "operator_role_arn": "arn"}
    answer = "There are 3 alarms configured."

    posted = []

    with (
        patch.object(handler, "get_secret", return_value=secret),
        patch.object(handler, "ask_devops_agent", return_value=answer) as mock_ask,
        patch.object(handler, "post_to_slack", side_effect=lambda c, t, b, ts=None: posted.append((c, t, b, ts))),
    ):
        result = handler.lambda_handler(event, None)

    assert result["statusCode"] == 200
    mock_ask.assert_called_once_with("how many alarms?", secret)
    assert len(posted) == 1
    assert posted[0][0] == "C12345"
    assert posted[0][1] == answer
    assert posted[0][3] is None


def test_lambda_handler_passes_message_ts_to_post():
    """When message_ts is in the event, it's passed through to post_to_slack."""
    event = {"question": "check errors", "channel_id": "C99", "user_id": "U1", "message_ts": "111.222"}
    secret = {"bot_token": "xoxb-test", "agent_space_id": "space", "operator_role_arn": "arn"}
    answer = "No errors found."

    posted = []

    with (
        patch.object(handler, "get_secret", return_value=secret),
        patch.object(handler, "ask_devops_agent", return_value=answer),
        patch.object(handler, "post_to_slack", side_effect=lambda c, t, b, ts=None: posted.append((c, t, b, ts))),
    ):
        result = handler.lambda_handler(event, None)

    assert result["statusCode"] == 200
    assert posted[0][3] == "111.222"


def test_lambda_handler_error_updates_placeholder():
    """On failure with message_ts, the error is posted via chat.update (same ts)."""
    event = {"question": "broken", "channel_id": "C99", "user_id": "U1", "message_ts": "333.444"}
    secret = {"bot_token": "xoxb-test", "agent_space_id": "space", "operator_role_arn": "arn"}

    posted = []

    with (
        patch.object(handler, "get_secret", return_value=secret),
        patch.object(handler, "ask_devops_agent", side_effect=RuntimeError("agent down")),
        patch.object(handler, "post_to_slack", side_effect=lambda c, t, b, ts=None: posted.append((c, t, b, ts))),
    ):
        result = handler.lambda_handler(event, None)

    assert result["statusCode"] == 500
    assert posted[0][3] == "333.444"
    assert "could not be completed" in posted[0][1]


def test_post_to_slack_uses_chat_update_when_ts_provided():
    """post_to_slack calls chat.update URL when message_ts is given."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.data = b'{"ok": true}'

    mock_http = MagicMock()
    mock_http.request.return_value = mock_resp

    with patch.object(handler, "_http", mock_http):
        handler.post_to_slack("C1", "answer", "xoxb-test", "999.888")

    call_args = mock_http.request.call_args
    assert "chat.update" in call_args[0][1]
    import json
    body = json.loads(call_args[1]["body"] if "body" in call_args[1] else call_args.kwargs["body"])
    assert body["ts"] == "999.888"


def test_post_to_slack_uses_post_message_when_no_ts():
    """post_to_slack calls chat.postMessage when message_ts is None."""
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.data = b'{"ok": true}'

    mock_http = MagicMock()
    mock_http.request.return_value = mock_resp

    with patch.object(handler, "_http", mock_http):
        handler.post_to_slack("C1", "answer", "xoxb-test", None)

    call_args = mock_http.request.call_args
    assert "chat.postMessage" in call_args[0][1]

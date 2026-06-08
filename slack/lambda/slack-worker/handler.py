"""Slack Worker Lambda (Path B, async phase).

Invoked asynchronously (InvocationType='Event') by the Slack Ack Lambda.
Performs the full DevOps Agent interaction off the Slack request path and
posts the answer back to the channel.

Verified flow:
  1. assume the DevOps Agent operator role WITH a mandatory AgentSpaceId
     session tag (the managed policy scopes aidevops:* to
     agentspace/${aws:PrincipalTag/AgentSpaceId}).
  2. build a `devops-agent` client (boto3 >= 1.43) with the assumed creds.
  3. create_chat -> executionId.
  4. send_message -> a streaming EventStream (NOT poll-based).
  5. parse the stream, prefer the `final_response` block.
  6. render [[investigation:id:title]] markers as Slack links.
  7. chat.postMessage back to the channel (truncated to 4000 chars).
"""

import json
import logging
import os
import re

import boto3
import urllib3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SECRET_NAME = os.environ.get("SLACK_SECRET_NAME", "aiops-cat-demo/slack-bot")
REGION = os.environ.get("AWS_REGION", "us-east-1")
MAX_MESSAGE_LENGTH = 4000
SLACK_POST_URL = "https://slack.com/api/chat.postMessage"
SLACK_UPDATE_URL = "https://slack.com/api/chat.update"
INVESTIGATION_CONSOLE_BASE = (
    "https://console.aws.amazon.com/devops-agent/home?region="
    + REGION
    + "#/investigations/"
)

_cached_secret: dict | None = None
_http = urllib3.PoolManager()


def get_secret() -> dict:
    """Retrieve and cache the Slack secret bundle."""
    global _cached_secret
    if _cached_secret is not None:
        return _cached_secret
    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=SECRET_NAME)
    _cached_secret = json.loads(resp["SecretString"])
    return _cached_secret


def get_agent_client(operator_role_arn: str, agent_space_id: str):
    """Assume the operator role with the mandatory AgentSpaceId session tag
    and return a devops-agent client bound to those credentials."""
    sts = boto3.client("sts")
    assumed = sts.assume_role(
        RoleArn=operator_role_arn,
        RoleSessionName="slack-worker",
        Tags=[{"Key": "AgentSpaceId", "Value": agent_space_id}],
    )
    c = assumed["Credentials"]
    return boto3.client(
        "devops-agent",
        region_name=REGION,
        aws_access_key_id=c["AccessKeyId"],
        aws_secret_access_key=c["SecretAccessKey"],
        aws_session_token=c["SessionToken"],
    )


def parse_agent_stream(event_stream) -> dict:
    """Collapse a send_message EventStream into a clean result.

    Returns {final_response, streaming_text, tool_summaries, chat_title}.
    Text deltas are reassembled per content-block index; the `final_response`
    block is preferred to avoid duplicating the streamed `text` block.
    """
    blocks: dict = {}  # index -> {"type": str, "text": [str]}

    for event in event_stream:
        for event_type, body in event.items():
            if event_type == "contentBlockStart":
                idx = body.get("index")
                blocks[idx] = {"type": body.get("type", "text"), "text": []}
            elif event_type == "contentBlockDelta":
                idx = body.get("index")
                delta = body.get("delta", {})
                if "textDelta" in delta:
                    blocks.setdefault(idx, {"type": "text", "text": []})
                    blocks[idx]["text"].append(delta["textDelta"]["text"])

    final_response = ""
    streaming_text = []
    tool_summaries = []
    chat_title = ""

    for idx in sorted(blocks.keys()):
        b = blocks[idx]
        text = "".join(b["text"])
        if b["type"] == "final_response":
            final_response = text
        elif b["type"] == "text":
            if text.strip():
                streaming_text.append(text)
        elif b["type"] == "tool_summary":
            if text.strip():
                tool_summaries.append(text)
        elif b["type"] == "chat_title":
            chat_title = text

    return {
        "final_response": final_response,
        "streaming_text": "".join(streaming_text),
        "tool_summaries": tool_summaries,
        "chat_title": chat_title,
    }


def render_investigation_links(text: str) -> str:
    """Rewrite [[investigation:id:title]] markers into Slack <url|label> links."""
    pattern = r"\[\[investigation:([^:]+):([^\]]+)\]\]"

    def repl(m):
        inv_id, title = m.group(1), m.group(2)
        return f"<{INVESTIGATION_CONSOLE_BASE}{inv_id}|{title}>"

    return re.sub(pattern, repl, text)


def truncate_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> str:
    return text[:limit] if len(text) > limit else text


def post_to_slack(
    channel: str, text: str, bot_token: str, message_ts: str | None = None
) -> None:
    """Post or update a Slack message.

    If message_ts is provided, updates the existing placeholder message via
    chat.update. Otherwise falls back to chat.postMessage.
    """
    truncated = truncate_message(text)
    if message_ts:
        url = SLACK_UPDATE_URL
        body = {"channel": channel, "ts": message_ts, "text": truncated}
    else:
        url = SLACK_POST_URL
        body = {"channel": channel, "text": truncated}

    resp = _http.request(
        "POST",
        url,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {bot_token}",
        },
        body=json.dumps(body).encode("utf-8"),
    )
    if resp.status != 200:
        logger.error("Slack post/update failed: status=%d", resp.status)
        return
    payload = json.loads(resp.data)
    if not payload.get("ok"):
        logger.error("Slack returned ok=false: %s", payload.get("error"))
        if message_ts:
            logger.info("Falling back to chat.postMessage")
            post_to_slack(channel, text, bot_token, None)


def ask_devops_agent(question: str, secret: dict) -> str:
    """Run one DevOps Agent chat turn and return the rendered answer text."""
    agent = get_agent_client(secret["operator_role_arn"], secret["agent_space_id"])
    chat = agent.create_chat(agentSpaceId=secret["agent_space_id"])
    execution_id = chat["executionId"]
    resp = agent.send_message(
        agentSpaceId=secret["agent_space_id"],
        executionId=execution_id,
        content=question,
    )
    parsed = parse_agent_stream(resp["events"])
    answer = parsed["final_response"] or parsed["streaming_text"]
    if not answer:
        raise RuntimeError("DevOps Agent returned no final_response")
    return render_investigation_links(answer)


def lambda_handler(event: dict, context) -> dict:
    """Async entry point. event = {question, channel_id, user_id, message_ts?}."""
    question = event.get("question", "")
    channel_id = event.get("channel_id", "")
    message_ts = event.get("message_ts")
    secret = get_secret()
    bot_token = secret["bot_token"]

    try:
        answer = ask_devops_agent(question, secret)
        post_to_slack(channel_id, answer, bot_token, message_ts)
        return {"statusCode": 200}
    except Exception as e:  # noqa: BLE001 — surface any failure to the user
        logger.error("Worker failed: %s", str(e))
        post_to_slack(
            channel_id,
            ":warning: Sorry, the investigation could not be completed. "
            "Please try again in a moment.",
            bot_token,
            message_ts,
        )
        return {"statusCode": 500}

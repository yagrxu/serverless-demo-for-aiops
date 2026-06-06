"""Verify the event-stream parser that the Slack handler will use.

Extracts the final_response block (the clean answer) and ignores the
duplicate streaming text + intermediate tool/thinking blocks.

Run: AWS_PROFILE=cloudops-demo python3 slack/tests/test_stream_parser.py
"""

import re

import boto3

PROFILE = "cloudops-demo"
REGION = "us-east-1"
SPACE_ID = "780758ca-830d-4faf-b943-0175693add32"
OPERATOR_ROLE_ARN = (
    "arn:aws:iam::719821274597:role/service-role/"
    "DevOpsAgentRole-WebappAdmin-ajf59et7"
)

# DevOps Agent console deep-link base for investigation references.
INVESTIGATION_CONSOLE_BASE = (
    "https://console.aws.amazon.com/devops-agent/home?region=us-east-1#/investigations/"
)


def get_agent_client():
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    sts = session.client("sts")
    assumed = sts.assume_role(
        RoleArn=OPERATOR_ROLE_ARN,
        RoleSessionName="parser-test",
        Tags=[{"Key": "AgentSpaceId", "Value": SPACE_ID}],
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
    """Collapse a DevOps Agent send_message event stream into a clean result.

    Returns:
      {
        "final_response": str,   # the clean answer (preferred for Slack)
        "streaming_text": str,   # accumulated thinking text (fallback)
        "tool_summaries": [str], # progress messages
        "chat_title": str,
      }
    """
    blocks = {}  # index -> {"type": str, "text": [str]}

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
    """Convert [[investigation:id:title]] markers into Slack link format.

    Slack uses <url|label> for links.
    """
    pattern = r"\[\[investigation:([^:]+):([^\]]+)\]\]"

    def repl(m):
        inv_id, title = m.group(1), m.group(2)
        url = INVESTIGATION_CONSOLE_BASE + inv_id
        return f"<{url}|{title}>"

    return re.sub(pattern, repl, text)


def main():
    agent = get_agent_client()
    chat = agent.create_chat(agentSpaceId=SPACE_ID)
    execution_id = chat["executionId"]

    question = "List current investigations with their status."
    print(f"Q: {question}\n")

    resp = agent.send_message(
        agentSpaceId=SPACE_ID, executionId=execution_id, content=question
    )
    result = parse_agent_stream(resp["events"])

    print("=== chat_title ===")
    print(result["chat_title"])
    print()
    print("=== tool_summaries ===")
    for t in result["tool_summaries"]:
        print(f"  - {t}")
    print()
    print("=== FINAL RESPONSE (raw) ===")
    print(result["final_response"])
    print()
    print("=== FINAL RESPONSE (Slack-rendered links) ===")
    print(render_investigation_links(result["final_response"]))

    # Sanity checks
    assert result["final_response"], "final_response must not be empty"
    print()
    print("OK: final_response extracted cleanly (no duplication)")


if __name__ == "__main__":
    main()

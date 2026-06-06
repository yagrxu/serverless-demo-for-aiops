"""Inspect the raw structure of the DevOps Agent send_message event stream.

Goal: understand every event type so we can write correct, dedup-safe parsing
for the Slack handler.

Run: AWS_PROFILE=cloudops-demo python3 slack/tests/inspect_event_stream.py
"""

import json
from collections import Counter

import boto3

PROFILE = "cloudops-demo"
REGION = "us-east-1"
SPACE_ID = "780758ca-830d-4faf-b943-0175693add32"
OPERATOR_ROLE_ARN = (
    "arn:aws:iam::719821274597:role/service-role/"
    "DevOpsAgentRole-WebappAdmin-ajf59et7"
)


def get_agent_client():
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    sts = session.client("sts")
    assumed = sts.assume_role(
        RoleArn=OPERATOR_ROLE_ARN,
        RoleSessionName="inspect",
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


def main():
    agent = get_agent_client()
    chat = agent.create_chat(agentSpaceId=SPACE_ID)
    execution_id = chat["executionId"]

    question = "How many investigations currently exist? Give a one sentence answer."
    print(f"Q: {question}\n")

    resp = agent.send_message(
        agentSpaceId=SPACE_ID, executionId=execution_id, content=question
    )

    event_type_counts = Counter()
    # Track text by content block index to understand structure
    blocks = {}  # index -> {"type": ..., "text": [...]}

    for event in resp["events"]:
        for event_type, body in event.items():
            event_type_counts[event_type] += 1

            if event_type == "contentBlockStart":
                idx = body.get("index")
                blocks[idx] = {"type": body.get("type"), "text": []}
            elif event_type == "contentBlockDelta":
                idx = body.get("index")
                delta = body.get("delta", {})
                if "textDelta" in delta:
                    blocks.setdefault(idx, {"type": "text", "text": []})
                    blocks[idx]["text"].append(delta["textDelta"]["text"])
            elif event_type == "contentBlockStop":
                idx = body.get("index")
                # Does stop carry a full text snapshot?
                stop_text = body.get("text", "")
                if stop_text:
                    print(f"[contentBlockStop idx={idx}] carries text len={len(stop_text)}")

    print("=== Event type counts ===")
    for et, n in event_type_counts.most_common():
        print(f"  {et}: {n}")

    print()
    print("=== Content blocks ===")
    for idx in sorted(blocks.keys()):
        b = blocks[idx]
        text = "".join(b["text"])
        preview = text[:200].replace("\n", " ")
        print(f"  block {idx} (type={b['type']}, len={len(text)}): {preview}")


if __name__ == "__main__":
    main()

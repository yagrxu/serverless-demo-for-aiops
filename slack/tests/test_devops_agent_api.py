"""Test the DevOps Agent API end-to-end via assume-role + AgentSpaceId session tag.

This is the programmatic access pattern the Slack Handler Lambda will use:
  1. Assume the WebappAdmin operator role, passing AgentSpaceId as a session tag
     (the managed policy scopes aidevops:CreateChat/SendMessage to
     agentspace/${aws:PrincipalTag/AgentSpaceId}).
  2. create_chat -> executionId
  3. send_message with the question
  4. poll list_pending_messages for the agent's response

Run with: AWS_PROFILE=cloudops-demo python3 slack/tests/test_devops_agent_api.py
"""

import sys
import json
import time

import boto3

PROFILE = "cloudops-demo"
REGION = "us-east-1"
SPACE_ID = "780758ca-830d-4faf-b943-0175693add32"
OPERATOR_ROLE_ARN = (
    "arn:aws:iam::719821274597:role/service-role/"
    "DevOpsAgentRole-WebappAdmin-ajf59et7"
)

# Question can be overridden from the command line:
#   python3 test_devops_agent_api.py "how many investigations exist right now?"
DEFAULT_QUESTION = (
    "What CloudWatch alarms are configured for the aiops-cat-demo project?"
)


def get_agent_client():
    """Assume the operator role with the AgentSpaceId session tag and return
    a devops-agent client scoped to that space."""
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    sts = session.client("sts")
    assumed = sts.assume_role(
        RoleArn=OPERATOR_ROLE_ARN,
        RoleSessionName="slack-bot",
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

    # 1. Create chat
    print("=== create_chat ===")
    chat = agent.create_chat(agentSpaceId=SPACE_ID)
    execution_id = chat["executionId"]
    print(f"executionId: {execution_id}")

    # 2. Send a message — response comes back as an event stream
    print()
    print("=== send_message (streaming) ===")
    question = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUESTION
    print(f"Q: {question}")
    send_resp = agent.send_message(
        agentSpaceId=SPACE_ID,
        executionId=execution_id,
        content=question,
    )

    print()
    print("=== streamed response events ===")
    event_stream = send_resp["events"]
    full_text = []
    tool_uses = []
    for event in event_stream:
        # Text deltas
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            if "textDelta" in delta:
                full_text.append(delta["textDelta"]["text"])
        # Tool use (the agent calling its investigation tools)
        elif "contentBlockStart" in event:
            blk = event["contentBlockStart"]
            if blk.get("type") == "tool_use":
                tool_uses.append(blk.get("name", "unknown_tool"))

    print()
    if tool_uses:
        print(f"Agent invoked tools: {tool_uses}")
        print()
    print("=== assembled answer ===")
    print("".join(full_text) if full_text else "(no text content)")


if __name__ == "__main__":
    main()

"""Measure DevOps Agent end-to-end latency to confirm async processing is required.

Slack requires an HTTP 200 ack within 3 seconds. If the agent round-trip
exceeds that, the Slack handler MUST ack first and process in the background.

Run: AWS_PROFILE=cloudops-demo python3 slack/tests/test_latency.py
"""

import time

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
        RoleSessionName="latency-test",
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
    t0 = time.time()
    agent = get_agent_client()
    t_assume = time.time() - t0

    t0 = time.time()
    chat = agent.create_chat(agentSpaceId=SPACE_ID)
    execution_id = chat["executionId"]
    t_chat = time.time() - t0

    t0 = time.time()
    resp = agent.send_message(
        agentSpaceId=SPACE_ID,
        executionId=execution_id,
        content="How many investigations exist? One sentence.",
    )
    t_first_byte = None
    final_response = ""
    for event in resp["events"]:
        if t_first_byte is None:
            t_first_byte = time.time() - t0
        for et, body in event.items():
            if et == "contentBlockStart" and body.get("type") == "final_response":
                cur_idx = body.get("index")
            if et == "contentBlockDelta":
                delta = body.get("delta", {})
                if "textDelta" in delta and body.get("index") == locals().get("cur_idx"):
                    final_response += delta["textDelta"]["text"]
    t_complete = time.time() - t0

    print("=== Latency breakdown ===")
    print(f"  assume_role + client:  {t_assume:.2f}s")
    print(f"  create_chat:           {t_chat:.2f}s")
    print(f"  send_message first byte: {t_first_byte:.2f}s")
    print(f"  send_message complete:   {t_complete:.2f}s")
    print()
    total = t_assume + t_chat + t_complete
    print(f"  TOTAL round-trip:        {total:.2f}s")
    print()
    if total > 3:
        print(f"=> {total:.1f}s > 3s Slack ack limit. ASYNC processing REQUIRED.")
    else:
        print("=> Under 3s — could respond synchronously (unlikely).")


if __name__ == "__main__":
    main()

"""Live end-to-end test of the ACTUAL slack-worker handler.

Invokes the real worker handler.lambda_handler with a synthetic async event,
letting it: read the slack-bot secret, assume the operator role (AgentSpaceId
tag), create_chat + send_message, parse the EventStream, render investigation
links, and post the answer to a real Slack channel via chat.postMessage.

Validates the production Path B code path end-to-end.

Usage:
  AWS_PROFILE=cloudops-demo AWS_REGION=us-east-1 \
    python3 slack/tests/test_worker_live.py <slack_channel_id> ["question"]
"""

import importlib.util
import pathlib
import sys

_HANDLER_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "lambda"
    / "slack-worker"
    / "handler.py"
)
_spec = importlib.util.spec_from_file_location("worker_handler", _HANDLER_PATH)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


def main():
    if len(sys.argv) < 2:
        print("Usage: test_worker_live.py <slack_channel_id> [question]")
        sys.exit(1)
    channel_id = sys.argv[1]
    question = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "How many investigations currently exist? One short sentence."
    )

    event = {"question": question, "channel_id": channel_id, "user_id": "U-test"}
    print(f"Q: {question}")
    print(f"Channel: {channel_id}")
    print("Invoking real slack-worker lambda_handler...")
    result = handler.lambda_handler(event, None)
    print(f"Result: {result}")
    if result["statusCode"] == 200:
        print("OK: worker completed and posted to Slack. Check the channel.")
    else:
        print("Worker returned non-200 — an error message was posted to the channel.")


if __name__ == "__main__":
    main()

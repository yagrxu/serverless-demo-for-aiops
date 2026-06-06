"""Live end-to-end test of the ACTUAL webhook-forwarder handler.

Invokes the real handler.lambda_handler with a synthetic SNS event, letting it
read the secret from Secrets Manager and POST to the real DevOps Agent webhook.
This validates the production code path (not a reimplementation).

Run: AWS_PROFILE=cloudops-demo python3 slack/tests/test_handler_live.py
"""

import importlib.util
import json
import pathlib
import time

# Load the real webhook-forwarder handler by path.
_HANDLER_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "lambda"
    / "webhook-forwarder"
    / "handler.py"
)
_spec = importlib.util.spec_from_file_location("wf_handler", _HANDLER_PATH)
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)


def main():
    sns_message = {
        "AlarmName": "aiops-cat-demo-feeding-p99-anomaly",
        "NewStateValue": "ALARM",
        "NewStateReason": (
            "Handler live test: FeedingFn p99 duration breached the anomaly band."
        ),
        "StateChangeTime": time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    event = {"Records": [{"Sns": {"Message": json.dumps(sns_message)}}]}

    print("Invoking real webhook-forwarder lambda_handler...")
    result = handler.lambda_handler(event, None)
    print(f"Result: {result}")
    assert result["statusCode"] == 200
    assert result["forwarded"] == 1
    print("OK: real handler signed + delivered the incident (HTTP 2xx).")


if __name__ == "__main__":
    main()

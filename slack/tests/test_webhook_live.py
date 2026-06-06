"""Live test: POST an HMAC-signed incident to the real DevOps Agent webhook.

Verifies Path A end-to-end against the actual endpoint. Uses the git-ignored
local config for the webhook URL + secret.

Per AWS docs (Invoking DevOps Agent through Webhook, Version 1 HMAC):
  - signature = base64( HMAC-SHA256(secret, "{timestamp}:{payload}") )
  - header x-amzn-event-signature: <signature>   (no "sha256=" prefix)
  - header x-amzn-event-timestamp: <ISO-8601 timestamp>  (current time)
  - payload schema: eventType, incidentId, action, priority, title, ...

Run: AWS_PROFILE=cloudops-demo python3 slack/tests/test_webhook_live.py
"""

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import urllib3

CONFIG_PATH = Path(__file__).resolve().parent / ".local-config.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def sign_base64(secret: str, timestamp: str, payload: str) -> str:
    """AWS docs format: base64(HMAC-SHA256(secret, '{timestamp}:{payload}'))."""
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}:{payload}".encode("utf-8"),
        hashlib.sha256,
    )
    return base64.b64encode(mac.digest()).decode("utf-8")


def main():
    cfg = load_config()
    url = cfg["webhook"]["url"]
    secret = cfg["webhook"]["hmac_secret"]

    http = urllib3.PoolManager()

    # Unique incident id + current timestamp (docs require uniqueness;
    # duplicates are deduplicated by the service).
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    incident_id = f"slack-test-{int(time.time())}"

    payload = {
        "eventType": "incident",
        "incidentId": incident_id,
        "action": "created",
        "priority": "HIGH",
        "title": "Slack Integration Webhook Test",
        "description": (
            "Synthetic incident from the slack-integration webhook test. "
            "Verifies Path A: SNS alarm -> webhook forwarder -> DevOps Agent."
        ),
        "service": "aiops-cat-demo",
        "timestamp": now,
    }

    body = json.dumps(payload, separators=(",", ":"))
    signature = sign_base64(secret, now, body)

    headers = {
        "Content-Type": "application/json",
        "x-amzn-event-timestamp": now,
        "x-amzn-event-signature": signature,
    }

    print("=== POST to DevOps Agent webhook ===")
    print(f"URL: {url}")
    print(f"incidentId: {incident_id}")
    print(f"timestamp: {now}")
    print(f"signature (base64): {signature[:20]}...")
    print()

    resp = http.request("POST", url, body=body.encode("utf-8"), headers=headers)
    print(f"Status: {resp.status}")
    print(f"Body: {resp.data.decode('utf-8', errors='replace')}")

    if 200 <= resp.status < 300:
        print()
        print("OK: webhook accepted. Check DevOps Agent for a new investigation.")
    else:
        print()
        print("FAILED: non-2xx response. Signing format may need adjustment.")


if __name__ == "__main__":
    main()

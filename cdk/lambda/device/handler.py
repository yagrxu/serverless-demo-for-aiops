"""Device service.

Routes:
  GET  /devices                       list devices
  GET  /devices/{id}                  get one device
  POST /devices/{id}/commands         issue a command (feed, refill, etc.)
  POST /devices/{id}/telemetry        record a telemetry point

Phase 3 additions:
  - Device state validation: offline devices return 503
  - Feed command cross-calls feeding limit logic

Inject source-level bugs directly here for AIOps scenarios.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger(service="device")
metrics = Metrics(namespace="CatDemo", service="device")

_ddb_kwargs = {"endpoint_url": os.environ["DDB_ENDPOINT"]} if os.environ.get("DDB_ENDPOINT") else {}
_ddb = boto3.resource("dynamodb", **_ddb_kwargs)
DEVICES = _ddb.Table(os.environ["DEVICES_TABLE"])
TELEMETRY = _ddb.Table(os.environ["DEVICE_TELEMETRY_TABLE"])

# Phase 3: feeding limits cross-call
FEEDING_TABLE_NAME = os.environ.get("FEEDING_EVENTS_TABLE")
FEEDING = _ddb.Table(FEEDING_TABLE_NAME) if FEEDING_TABLE_NAME else None

DAILY_LIMIT_GRAMS = int(os.environ.get("DAILY_LIMIT_GRAMS", "200"))
WET_FOOD_DAILY_LIMIT = int(os.environ.get("WET_FOOD_DAILY_LIMIT", "100"))
DRY_FOOD_DAILY_LIMIT = int(os.environ.get("DRY_FOOD_DAILY_LIMIT", "150"))
MIN_INTERVAL_HOURS = int(os.environ.get("MIN_INTERVAL_HOURS", "2"))


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == int(o) else float(o)
    raise TypeError


def _to_decimal(obj):
    """Recursively convert float values to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(i) for i in obj]
    return obj


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_default),
    }


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _today_start_iso():
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_device_online(device_id: str) -> dict | None:
    """Check if device is online. Returns device record if online, None + logs if offline."""
    got = DEVICES.get_item(Key={"device_id": device_id}).get("Item")
    if not got:
        return None
    if got.get("status") == "offline":
        return {"offline": True, "device": got}
    return got


def _check_feed_limits(cat_id: str, amount_grams: int, food_type: str) -> dict | None:
    """Check feeding limits. Returns None if OK, or error dict if limit exceeded."""
    if not FEEDING or not cat_id:
        return None

    today_start = _today_start_iso()
    try:
        res = FEEDING.query(
            KeyConditionExpression=Key("cat_id").eq(cat_id) & Key("ts").gte(today_start),
        )
        today_feedings = res.get("Items", [])
    except Exception as e:
        logger.warning("Failed to query feeding limits", extra={"error": str(e)})
        return None  # fail-open: allow if we can't check

    # Total daily
    total_today = sum(int(f.get("amount_grams", 0)) for f in today_feedings)
    if total_today + amount_grams > DAILY_LIMIT_GRAMS:
        return {
            "reason": "daily_limit_exceeded",
            "limit": DAILY_LIMIT_GRAMS,
            "consumed": total_today,
            "requested": amount_grams,
        }

    # Per food-type limit
    type_today = sum(int(f.get("amount_grams", 0)) for f in today_feedings if f.get("food_type") == food_type)
    type_limit = WET_FOOD_DAILY_LIMIT if food_type == "wet" else DRY_FOOD_DAILY_LIMIT
    if type_today + amount_grams > type_limit:
        return {
            "reason": f"{food_type}_food_limit_exceeded",
            "limit": type_limit,
            "consumed": type_today,
            "requested": amount_grams,
        }

    # Minimum interval
    if today_feedings:
        last_ts = max(f["ts"] for f in today_feedings)
        last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
        now_dt = datetime.now(timezone.utc)
        if (now_dt - last_dt) < timedelta(hours=MIN_INTERVAL_HOURS):
            return {
                "reason": "min_interval_not_met",
                "min_hours": MIN_INTERVAL_HOURS,
                "last_feeding": last_ts,
            }

    return None


def _execute_command(device_id: str, body: dict) -> tuple:
    """Execute a device command after validation. Returns (status_code, response_body)."""
    # Phase 3: validate device state
    device_check = _check_device_online(device_id)
    if device_check is None:
        return 404, {"message": f"device '{device_id}' not found"}
    if isinstance(device_check, dict) and device_check.get("offline"):
        metrics.add_metric(name="DeviceOfflineRejection", unit=MetricUnit.Count, value=1)
        return 503, {
            "message": "device is offline",
            "device_id": device_id,
            "last_seen": device_check["device"].get("last_seen"),
        }

    command = body.get("command")
    args = body.get("args") or {}

    # Phase 3: feed command cross-calls feeding limits
    if command == "feed":
        cat_id = device_check.get("cat_id") or args.get("cat_id")
        amount = int(args.get("amount_grams", 50))
        food_type = args.get("food_type", "dry")

        limit_error = _check_feed_limits(cat_id, amount, food_type)
        if limit_error:
            metrics.add_metric(name="FeedCommandLimitRejection", unit=MetricUnit.Count, value=1)
            return 429, {
                "message": "feeding limit exceeded",
                "detail": limit_error,
            }

    # Record the command
    cmd = {
        "device_id": device_id,
        "ts": _now_iso(),
        "kind": "command",
        "command": command,
        "args": _to_decimal(args) if args else None,
        "command_id": str(uuid.uuid4()),
    }
    # Remove None values
    cmd = {k: v for k, v in cmd.items() if v is not None}

    TELEMETRY.put_item(Item=cmd)
    metrics.add_metric(name="DeviceWriteSuccess", unit=MetricUnit.Count, value=1)
    return 202, cmd


def _dispatch_gateway(event, context):
    """Handle AgentCore Gateway tool invocations."""
    delimiter = "___"
    original_tool_name = context.client_context.custom.get("bedrockAgentCoreToolName", "")
    if delimiter in original_tool_name:
        tool_name = original_tool_name[original_tool_name.index(delimiter) + len(delimiter):]
    else:
        tool_name = original_tool_name
    tool_input = event

    try:
        if tool_name == "list_devices":
            items = DEVICES.scan(Limit=50).get("Items", [])
            metrics.add_metric(name="DevicesCommanded", unit=MetricUnit.Count, value=1)
            return items

        elif tool_name == "get_device":
            device_id = tool_input.get("device_id")
            if not device_id:
                return {"error": "device_id is required"}
            item = DEVICES.get_item(Key={"device_id": device_id}).get("Item")
            metrics.add_metric(name="DevicesCommanded", unit=MetricUnit.Count, value=1)
            if not item:
                return {"error": f"device '{device_id}' not found"}
            return item

        elif tool_name == "send_device_command":
            device_id = tool_input.get("device_id")
            if not device_id:
                return {"error": "device_id is required"}
            command = tool_input.get("command")
            if not command:
                return {"error": "command is required"}

            body = {"command": command, "args": tool_input.get("args")}
            status, result = _execute_command(device_id, body)
            if status >= 400:
                return {"error": result.get("message"), "detail": result.get("detail"), "status": status}
            metrics.add_metric(name="DevicesCommanded", unit=MetricUnit.Count, value=1)
            return result

        else:
            return {"error": f"unknown tool: {tool_name}"}
    except Exception as e:
        logger.exception("gateway tool failed", extra={"tool": tool_name})
        return {"error": str(e)}


@logger.inject_lambda_context
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event, _ctx):
    if hasattr(_ctx, 'client_context') and _ctx.client_context and hasattr(_ctx.client_context, 'custom') and _ctx.client_context.custom and 'bedrockAgentCoreToolName' in _ctx.client_context.custom:
        result = _dispatch_gateway(event, _ctx)
        return json.dumps(result, default=_default)

    method = event.get("httpMethod")
    path = event.get("resource", "")
    path_params = event.get("pathParameters") or {}
    device_id = path_params.get("id")

    if method == "GET" and path == "/devices":
        metrics.add_metric(name="DevicesCommanded", unit=MetricUnit.Count, value=1)
        return _resp(200, DEVICES.scan(Limit=50).get("Items", []))

    if method == "GET" and path == "/devices/{id}":
        got = DEVICES.get_item(Key={"device_id": device_id}).get("Item")
        metrics.add_metric(name="DevicesCommanded", unit=MetricUnit.Count, value=1)
        if not got:
            return _resp(404, {"message": "not found"})
        return _resp(200, got)

    if method == "POST" and path == "/devices/{id}/commands":
        body = json.loads(event.get("body") or "{}")
        status, result = _execute_command(device_id, body)
        if status < 400:
            metrics.add_metric(name="DevicesCommanded", unit=MetricUnit.Count, value=1)
        return _resp(status, result)

    if method == "POST" and path == "/devices/{id}/telemetry":
        body = json.loads(event.get("body") or "{}")
        point = {
            "device_id": device_id,
            "ts": body.get("ts") or _now_iso(),
            "kind": "telemetry",
            "metrics": _to_decimal(body.get("metrics") or {}),
        }
        try:
            TELEMETRY.put_item(Item=point)
        except Exception:
            logger.exception("telemetry put_item failed", extra={"device_id": device_id})
            raise
        metrics.add_metric(name="DeviceWriteSuccess", unit=MetricUnit.Count, value=1)
        return _resp(201, point)

    return _resp(405, {"message": "method not allowed"})

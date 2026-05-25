"""Feeding service.

Routes:
  GET  /feedings?cat_id=...    list feedings for a cat
  POST /feedings               record a feeding event

Business rules:
  - Each cat has a daily feeding limit (default 200g/day)
  - Wet food limit: 100g/day, Dry food limit: 150g/day
  - Minimum interval between feedings: 2 hours
  - Exceeding limits returns 429 + creates a health alert
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

logger = Logger(service="feeding")
metrics = Metrics(namespace="CatDemo", service="feeding")

_ddb_kwargs = {"endpoint_url": os.environ["DDB_ENDPOINT"]} if os.environ.get("DDB_ENDPOINT") else {}
_ddb = boto3.resource("dynamodb", **_ddb_kwargs)
TABLE = _ddb.Table(os.environ["FEEDING_EVENTS_TABLE"])

# Health alerts table (for creating alerts on limit violations)
HEALTH_ALERTS_TABLE_NAME = os.environ.get("HEALTH_ALERTS_TABLE")
HEALTH_ALERTS_TABLE = _ddb.Table(HEALTH_ALERTS_TABLE_NAME) if HEALTH_ALERTS_TABLE_NAME else None

# --- Feeding limits ---
DAILY_LIMIT_GRAMS = int(os.environ.get("DAILY_LIMIT_GRAMS", "200"))
WET_FOOD_DAILY_LIMIT = int(os.environ.get("WET_FOOD_DAILY_LIMIT", "100"))
DRY_FOOD_DAILY_LIMIT = int(os.environ.get("DRY_FOOD_DAILY_LIMIT", "150"))
MIN_INTERVAL_HOURS = int(os.environ.get("MIN_INTERVAL_HOURS", "2"))


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == int(o) else float(o)
    raise TypeError


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_default),
    }


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _today_start_iso():
    """Return the start of today (UTC) as ISO string."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def _check_feeding_limits(cat_id: str, amount_grams, food_type: str) -> dict | None:
    """Check if this feeding would exceed daily limits.

    Returns None if OK, or a dict with error details if limit exceeded.
    """
    today_start = _today_start_iso()

    # Query today's feedings for this cat
    res = TABLE.query(
        KeyConditionExpression=Key("cat_id").eq(cat_id) & Key("ts").gte(today_start),
        ScanIndexForward=False,
    )
    today_feedings = res.get("Items", [])

    # Calculate today's totals
    total_today = sum(
        float(f.get("amount_grams", 0)) for f in today_feedings
    )
    wet_today = sum(
        float(f.get("amount_grams", 0))
        for f in today_feedings
        if f.get("food_type") == "wet"
    )
    dry_today = sum(
        float(f.get("amount_grams", 0))
        for f in today_feedings
        if f.get("food_type") == "dry"
    )

    request_amount = float(amount_grams) if amount_grams else 0

    # Check overall daily limit
    if total_today + request_amount > DAILY_LIMIT_GRAMS:
        return {
            "reason": "daily_limit_exceeded",
            "message": f"Daily limit of {DAILY_LIMIT_GRAMS}g exceeded. "
                       f"Already fed {total_today:.0f}g today, "
                       f"requested {request_amount:.0f}g.",
            "daily_limit": DAILY_LIMIT_GRAMS,
            "already_fed_today": total_today,
            "requested": request_amount,
        }

    # Check per-type limits
    if food_type == "wet" and wet_today + request_amount > WET_FOOD_DAILY_LIMIT:
        return {
            "reason": "wet_food_limit_exceeded",
            "message": f"Wet food daily limit of {WET_FOOD_DAILY_LIMIT}g exceeded. "
                       f"Already fed {wet_today:.0f}g wet food today.",
            "limit": WET_FOOD_DAILY_LIMIT,
            "already_fed": wet_today,
            "requested": request_amount,
        }

    if food_type == "dry" and dry_today + request_amount > DRY_FOOD_DAILY_LIMIT:
        return {
            "reason": "dry_food_limit_exceeded",
            "message": f"Dry food daily limit of {DRY_FOOD_DAILY_LIMIT}g exceeded. "
                       f"Already fed {dry_today:.0f}g dry food today.",
            "limit": DRY_FOOD_DAILY_LIMIT,
            "already_fed": dry_today,
            "requested": request_amount,
        }

    # Check minimum interval
    if today_feedings:
        last_feeding_ts = today_feedings[0].get("ts", "")
        if last_feeding_ts:
            try:
                last_time = datetime.strptime(last_feeding_ts, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc
                )
                now = datetime.now(timezone.utc)
                interval = now - last_time
                if interval < timedelta(hours=MIN_INTERVAL_HOURS):
                    remaining = timedelta(hours=MIN_INTERVAL_HOURS) - interval
                    return {
                        "reason": "too_frequent",
                        "message": f"Minimum {MIN_INTERVAL_HOURS}h interval between feedings. "
                                   f"Last feeding was {interval.total_seconds() / 60:.0f} minutes ago. "
                                   f"Wait {remaining.total_seconds() / 60:.0f} more minutes.",
                        "min_interval_hours": MIN_INTERVAL_HOURS,
                        "minutes_since_last": interval.total_seconds() / 60,
                    }
            except (ValueError, TypeError):
                pass  # If we can't parse the timestamp, skip interval check

    return None  # All checks passed


def _create_feeding_alert(cat_id: str, violation: dict):
    """Create a health alert for a feeding limit violation."""
    if not HEALTH_ALERTS_TABLE:
        logger.warning("HEALTH_ALERTS_TABLE not configured, skipping alert creation")
        return

    alert = {
        "cat_id": cat_id,
        "ts": _now_iso(),
        "alert_id": str(uuid.uuid4()),
        "type": "feeding_limit_violation",
        "severity": "warning",
        "reason": violation.get("reason"),
        "details": violation.get("message"),
    }
    try:
        HEALTH_ALERTS_TABLE.put_item(Item=alert)
        logger.info("Created feeding alert", extra={"cat_id": cat_id, "reason": violation.get("reason")})
    except Exception:
        logger.exception("Failed to create feeding alert")


def _record_feeding(cat_id: str, amount_grams, food_type: str, source: str, ts: str | None = None):
    """Record a feeding event after limit checks pass.

    Returns (item, None) on success or (None, error_response) on limit violation.
    """
    # Check limits
    violation = _check_feeding_limits(cat_id, amount_grams, food_type or "unknown")
    if violation:
        # Create alert and return 429
        _create_feeding_alert(cat_id, violation)
        metrics.add_metric(name="FeedingLimitViolations", unit=MetricUnit.Count, value=1)
        return None, violation

    # Convert float to Decimal for DynamoDB
    if isinstance(amount_grams, float):
        amount_grams = Decimal(str(amount_grams))

    item = {
        "cat_id": cat_id,
        "ts": ts or _now_iso(),
        "event_id": str(uuid.uuid4()),
        "amount_grams": amount_grams,
        "food_type": food_type,
        "source": source,
    }
    TABLE.put_item(Item=item)
    metrics.add_metric(name="FeedingsCreated", unit=MetricUnit.Count, value=1)
    return item, None


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
        if tool_name == "get_feedings":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            res = TABLE.query(
                KeyConditionExpression=Key("cat_id").eq(cat_id),
                ScanIndexForward=False,
                Limit=50,
            )
            metrics.add_metric(name="FeedingsRead", unit=MetricUnit.Count, value=1)
            return res.get("Items", [])

        elif tool_name == "record_feeding":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            amount_grams = tool_input.get("amount_grams")
            if amount_grams is None:
                return {"error": "amount_grams is required"}
            food_type = tool_input.get("food_type")
            if not food_type:
                return {"error": "food_type is required"}

            item, violation = _record_feeding(cat_id, amount_grams, food_type, source="gateway")
            if violation:
                return {"error": "feeding_limit_exceeded", **violation}
            return item

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

    if method == "GET":
        qs = event.get("queryStringParameters") or {}
        cat_id = qs.get("cat_id")
        if not cat_id:
            return _resp(400, {"message": "cat_id is required"})
        res = TABLE.query(
            KeyConditionExpression=Key("cat_id").eq(cat_id),
            ScanIndexForward=False,
            Limit=50,
        )
        metrics.add_metric(name="FeedingsRead", unit=MetricUnit.Count, value=1)
        return _resp(200, res.get("Items", []))

    if method == "POST":
        body = json.loads(event.get("body") or "{}")
        cat_id = body.get("cat_id")
        if not cat_id:
            return _resp(400, {"message": "cat_id is required"})
        amount = body.get("amount_grams")
        food_type = body.get("food_type", "unknown")

        item, violation = _record_feeding(
            cat_id, amount, food_type,
            source=body.get("source", "manual"),
            ts=body.get("ts"),
        )
        if violation:
            return _resp(429, {
                "message": "Feeding limit exceeded",
                **violation,
            })
        return _resp(201, item)

    return _resp(405, {"message": "method not allowed"})

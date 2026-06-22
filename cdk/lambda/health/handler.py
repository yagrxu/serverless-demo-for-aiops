"""Health service.

Routes:
  GET /health/{cat_id}           computed health score + recent metrics
  GET /health/{cat_id}/alerts    active alerts for a cat

Gateway tools:
  get_health_metrics    raw metrics for a cat
  get_health_alerts     alerts for a cat
  get_health_score      computed score (0-100) with breakdown
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

logger = Logger(service="health")
metrics = Metrics(namespace="CatDemo", service="health")

_ddb_kwargs = {"endpoint_url": os.environ["DDB_ENDPOINT"]} if os.environ.get("DDB_ENDPOINT") else {}
_ddb = boto3.resource("dynamodb", **_ddb_kwargs)
METRICS = _ddb.Table(os.environ["HEALTH_METRICS_TABLE"])
ALERTS = _ddb.Table(os.environ["HEALTH_ALERTS_TABLE"])

# Phase 2: cross-table read for health score
FEEDING_TABLE_NAME = os.environ.get("FEEDING_EVENTS_TABLE")
FEEDING = _ddb.Table(FEEDING_TABLE_NAME) if FEEDING_TABLE_NAME else None

# Phase 5: rollup tables for daily aggregates
NUTRITION_ROLLUP_NAME = os.environ.get("DAILY_NUTRITION_ROLLUP_TABLE")
NUTRITION_ROLLUP = _ddb.Table(NUTRITION_ROLLUP_NAME) if NUTRITION_ROLLUP_NAME else None
HEALTH_SUMMARY_NAME = os.environ.get("DAILY_HEALTH_SUMMARY_TABLE")
HEALTH_SUMMARY = _ddb.Table(HEALTH_SUMMARY_NAME) if HEALTH_SUMMARY_NAME else None


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


def _compute_health_score(cat_id: str) -> dict:
    """Compute a health score (0-100) from feeding regularity and weight stability.

    Components (each 0-100, averaged):
      - feeding_regularity: how consistently the cat is fed daily over the last 7 days
      - weight_stability: how stable weight readings are over the last 30 days
      - activity_level: derived from recent metrics (if available)

    Returns dict with score, components, and alert flag.
    """
    now = datetime.now(timezone.utc)
    seven_days_ago = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    thirty_days_ago = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- Feeding regularity (last 7 days) ---
    feeding_score = 50  # default for cats with no feeding data
    if FEEDING:
        try:
            feed_res = FEEDING.query(
                KeyConditionExpression=Key("cat_id").eq(cat_id) & Key("ts").gte(seven_days_ago),
            )
            feedings = feed_res.get("Items", [])
            if feedings:
                # Count distinct days with at least one feeding
                fed_days = len(set(f["ts"][:10] for f in feedings))
                # 7/7 days fed = 100, fewer = proportional
                feeding_score = min(100, int((fed_days / 7) * 100))
            else:
                feeding_score = 0  # no feedings in 7 days = concern
        except Exception as e:
            logger.warning("Failed to read feeding data", extra={"error": str(e)})

    # --- Weight stability (last 30 days) ---
    weight_score = 50  # default for cats with no weight data
    try:
        weight_res = METRICS.query(
            KeyConditionExpression=Key("cat_id").eq(cat_id) & Key("ts").gte(thirty_days_ago),
            ScanIndexForward=True,
        )
        weight_items = [m for m in weight_res.get("Items", []) if m.get("weight_kg")]
        if len(weight_items) >= 2:
            weights = [float(m["weight_kg"]) for m in weight_items]
            avg = sum(weights) / len(weights)
            if avg > 0:
                # Coefficient of variation — lower is more stable
                variance = sum((w - avg) ** 2 for w in weights) / len(weights)
                cv = (variance ** 0.5) / avg
                # cv < 0.02 = perfect (100), cv > 0.15 = bad (0)
                weight_score = max(0, min(100, int((1 - cv / 0.15) * 100)))
        elif len(weight_items) == 1:
            weight_score = 70  # single reading, can't assess stability
    except Exception as e:
        logger.warning("Failed to read weight data", extra={"error": str(e)})

    # --- Activity level (from recent metrics) ---
    activity_score = 50  # default
    try:
        recent_res = METRICS.query(
            KeyConditionExpression=Key("cat_id").eq(cat_id) & Key("ts").gte(seven_days_ago),
            ScanIndexForward=False,
            Limit=20,
        )
        recent = recent_res.get("Items", [])
        activity_items = [m for m in recent if m.get("activity_level")]
        if activity_items:
            avg_activity = sum(float(m["activity_level"]) for m in activity_items) / len(activity_items)
            # Normalize: activity_level 1-10 scale → 0-100
            activity_score = max(0, min(100, int(avg_activity * 10)))
    except Exception as e:
        logger.warning("Failed to read activity data", extra={"error": str(e)})

    # Weighted average
    score = int(feeding_score * 0.4 + weight_score * 0.35 + activity_score * 0.25)

    result = {
        "cat_id": cat_id,
        "score": score,
        "components": {
            "feeding_regularity": feeding_score,
            "weight_stability": weight_score,
            "activity_level": activity_score,
        },
        "computed_at": _now_iso(),
    }

    # Write alert if score is critical
    if score < 60:
        _create_alert(cat_id, score, result["components"])
        result["alert_created"] = True

    return result


def _create_alert(cat_id: str, score: int, components: dict):
    """Write a HealthAlert when score drops below threshold."""
    try:
        alert = {
            "cat_id": cat_id,
            "alert_id": f"health-score-{_now_iso()}-{uuid.uuid4().hex[:8]}",
            "type": "low_health_score",
            "score": score,
            "components": components,
            "ts": _now_iso(),
            "resolved": False,
        }
        ALERTS.put_item(Item=_to_decimal(alert))
        metrics.add_metric(name="HealthAlertCreated", unit=MetricUnit.Count, value=1)
        logger.info("Health alert created", extra={"cat_id": cat_id, "score": score})
    except Exception:
        logger.exception("Failed to create health alert")


def _to_decimal(obj):
    """Convert floats to Decimal for DDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(i) for i in obj]
    return obj


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
        if tool_name == "get_health_metrics":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            res = METRICS.query(
                KeyConditionExpression=Key("cat_id").eq(cat_id),
                ScanIndexForward=False,
                Limit=100,
            )
            metrics.add_metric(name="HealthMetricsRead", unit=MetricUnit.Count, value=1)
            return res.get("Items", [])

        elif tool_name == "get_health_alerts":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            res = ALERTS.query(
                KeyConditionExpression=Key("cat_id").eq(cat_id),
                Limit=50,
            )
            metrics.add_metric(name="HealthAlertsRead", unit=MetricUnit.Count, value=1)
            return res.get("Items", [])

        elif tool_name == "get_health_score":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            result = _compute_health_score(cat_id)
            metrics.add_metric(name="HealthScoreComputed", unit=MetricUnit.Count, value=1)
            return result

        elif tool_name == "get_daily_rollup":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            if not NUTRITION_ROLLUP:
                return {"error": "rollup table not configured"}
            date = tool_input.get("date")
            if date:
                res = NUTRITION_ROLLUP.get_item(Key={"cat_id": cat_id, "date": date})
                return res.get("Item") or {"message": "no rollup for this date"}
            # Last 7 days
            res = NUTRITION_ROLLUP.query(
                KeyConditionExpression=Key("cat_id").eq(cat_id),
                ScanIndexForward=False,
                Limit=7,
            )
            return res.get("Items", [])

        elif tool_name == "get_health_summary":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            if not HEALTH_SUMMARY:
                return {"error": "summary table not configured"}
            date = tool_input.get("date")
            if date:
                res = HEALTH_SUMMARY.get_item(Key={"cat_id": cat_id, "date": date})
                return res.get("Item") or {"message": "no summary for this date"}
            res = HEALTH_SUMMARY.query(
                KeyConditionExpression=Key("cat_id").eq(cat_id),
                ScanIndexForward=False,
                Limit=7,
            )
            return res.get("Items", [])

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
    cat_id = (event.get("pathParameters") or {}).get("cat_id")

    if method != "GET" or not cat_id:
        return _resp(405, {"message": "method not allowed"})

    if path == "/health/{cat_id}":
        # Phase 2: Return computed health score + recent metrics
        score_data = _compute_health_score(cat_id)
        res = METRICS.query(
            KeyConditionExpression=Key("cat_id").eq(cat_id),
            ScanIndexForward=False,
            Limit=20,
        )
        metrics.add_metric(name="HealthMetricsRead", unit=MetricUnit.Count, value=1)
        metrics.add_metric(name="HealthScoreComputed", unit=MetricUnit.Count, value=1)
        return _resp(200, {
            "health_score": score_data,
            "recent_metrics": res.get("Items", []),
        })

    if path == "/health/{cat_id}/alerts":
        res = ALERTS.query(
            KeyConditionExpression=Key("cat_id").eq(cat_id),
            Limit=50,
        )
        metrics.add_metric(name="HealthAlertsRead", unit=MetricUnit.Count, value=1)
        return _resp(200, res.get("Items", []))

    return _resp(404, {"message": "not found"})

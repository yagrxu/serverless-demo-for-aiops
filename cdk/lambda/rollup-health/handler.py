"""Health summary rollup — SQS consumer.

Triggered by EventBridge → SQS when HealthMetrics stream emits.
Aggregates health metrics for a cat on a given day and writes/overwrites
the DailyHealthSummary row.
"""
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger(service="rollup-health")
metrics = Metrics(namespace="CatDemo", service="rollup-health")

_ddb_kwargs = {"endpoint_url": os.environ["DDB_ENDPOINT"]} if os.environ.get("DDB_ENDPOINT") else {}
_ddb = boto3.resource("dynamodb", **_ddb_kwargs)
HEALTH_METRICS = _ddb.Table(os.environ["HEALTH_METRICS_TABLE"])
SUMMARY = _ddb.Table(os.environ["DAILY_HEALTH_SUMMARY_TABLE"])


def _dec(v):
    return Decimal(str(v)) if isinstance(v, float) else v


@logger.inject_lambda_context
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event, _ctx):
    """Process SQS batch. Each message body is a DDB stream event from EventBridge."""
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            detail = body.get("detail", body)
            keys = detail.get("dynamodb", {}).get("Keys", {})
            cat_id = keys.get("cat_id", {}).get("S")
            ts = keys.get("ts", {}).get("S")
            if not cat_id or not ts:
                logger.warning("Missing keys in stream record", extra={"record": record})
                continue

            date = ts[:10]
            _recompute_daily_summary(cat_id, date)
        except Exception:
            logger.exception("Failed to process record", extra={"record_id": record.get("messageId")})
            raise

    metrics.add_metric(name="HealthSummaryProcessed", unit=MetricUnit.Count, value=len(event.get("Records", [])))


def _recompute_daily_summary(cat_id: str, date: str):
    """Query all health metrics for cat_id on date, compute summary."""
    day_start = f"{date}T00:00:00Z"
    day_end = f"{date}T23:59:59Z"

    res = HEALTH_METRICS.query(
        KeyConditionExpression=Key("cat_id").eq(cat_id) & Key("ts").between(day_start, day_end),
    )
    items = res.get("Items", [])
    if not items:
        return

    weights = [float(m["weight_kg"]) for m in items if m.get("weight_kg")]
    activities = [float(m["activity_level"]) for m in items if m.get("activity_level")]

    summary = {
        "cat_id": cat_id,
        "date": date,
        "readings_count": len(items),
        "avg_weight_kg": _dec(round(sum(weights) / len(weights), 2)) if weights else None,
        "avg_activity": _dec(round(sum(activities) / len(activities), 1)) if activities else None,
        "min_activity": _dec(min(activities)) if activities else None,
        "max_activity": _dec(max(activities)) if activities else None,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # Remove None values
    summary = {k: v for k, v in summary.items() if v is not None}
    SUMMARY.put_item(Item=summary)
    logger.info("Health summary updated", extra={"cat_id": cat_id, "date": date})

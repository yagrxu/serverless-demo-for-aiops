"""Nutrition rollup — SQS consumer.

Triggered by EventBridge → SQS when FeedingEvents stream emits.
Aggregates all feedings for a cat on a given day and writes/overwrites
the DailyNutritionRollup row.
"""
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger(service="rollup-nutrition")
metrics = Metrics(namespace="CatDemo", service="rollup-nutrition")

_ddb_kwargs = {"endpoint_url": os.environ["DDB_ENDPOINT"]} if os.environ.get("DDB_ENDPOINT") else {}
_ddb = boto3.resource("dynamodb", **_ddb_kwargs)
FEEDING = _ddb.Table(os.environ["FEEDING_EVENTS_TABLE"])
ROLLUP = _ddb.Table(os.environ["DAILY_NUTRITION_ROLLUP_TABLE"])


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == int(o) else float(o)
    raise TypeError


@logger.inject_lambda_context
@metrics.log_metrics(capture_cold_start_metric=True)
def lambda_handler(event, _ctx):
    """Process SQS batch. Each message body is a DDB stream event from EventBridge."""
    for record in event.get("Records", []):
        try:
            body = json.loads(record["body"])
            # EventBridge wraps the DDB stream record in detail
            detail = body.get("detail", body)
            keys = detail.get("dynamodb", {}).get("Keys", {})
            cat_id = keys.get("cat_id", {}).get("S")
            ts = keys.get("ts", {}).get("S")
            if not cat_id or not ts:
                logger.warning("Missing keys in stream record", extra={"record": record})
                continue

            date = ts[:10]  # YYYY-MM-DD
            _recompute_daily_rollup(cat_id, date)
        except Exception:
            logger.exception("Failed to process record", extra={"record_id": record.get("messageId")})
            raise  # Let SQS retry

    metrics.add_metric(name="NutritionRollupProcessed", unit=MetricUnit.Count, value=len(event.get("Records", [])))


def _recompute_daily_rollup(cat_id: str, date: str):
    """Query all feedings for cat_id on date, compute totals, write rollup."""
    day_start = f"{date}T00:00:00Z"
    day_end = f"{date}T23:59:59Z"

    res = FEEDING.query(
        KeyConditionExpression=Key("cat_id").eq(cat_id) & Key("ts").between(day_start, day_end),
    )
    items = res.get("Items", [])

    total_grams = sum(int(f.get("amount_grams", 0)) for f in items)
    wet_grams = sum(int(f.get("amount_grams", 0)) for f in items if f.get("food_type") == "wet")
    dry_grams = sum(int(f.get("amount_grams", 0)) for f in items if f.get("food_type") == "dry")
    feeding_count = len(items)

    rollup = {
        "cat_id": cat_id,
        "date": date,
        "total_grams": total_grams,
        "wet_grams": wet_grams,
        "dry_grams": dry_grams,
        "feeding_count": feeding_count,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    ROLLUP.put_item(Item=rollup)
    logger.info("Rollup updated", extra={"cat_id": cat_id, "date": date, "total_grams": total_grams})

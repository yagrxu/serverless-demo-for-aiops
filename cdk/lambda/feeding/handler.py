"""Feeding service.

Routes:
  GET  /feedings?cat_id=...    list feedings for a cat
  POST /feedings               record a feeding event
"""
import json
import os
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger(service="feeding")
metrics = Metrics(namespace="CatDemo", service="feeding")

_ddb_kwargs = {"endpoint_url": os.environ["DDB_ENDPOINT"]} if os.environ.get("DDB_ENDPOINT") else {}
TABLE = boto3.resource("dynamodb", **_ddb_kwargs).Table(os.environ["FEEDING_EVENTS_TABLE"])


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


def _dispatch_gateway(event, context):
    """Handle AgentCore Gateway tool invocations.

    Gateway sends tool input as event, tool name in context.client_context.custom.
    """
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
            item = {
                "cat_id": cat_id,
                "ts": _now_iso(),
                "event_id": str(uuid.uuid4()),
                "amount_grams": amount_grams,
                "food_type": food_type,
                "source": "gateway",
            }
            TABLE.put_item(Item=item)
            metrics.add_metric(name="FeedingsCreated", unit=MetricUnit.Count, value=1)
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
        item = {
            "cat_id": cat_id,
            "ts": body.get("ts") or _now_iso(),
            "event_id": str(uuid.uuid4()),
            "amount_grams": body.get("amount_grams"),
            "food_type": body.get("food_type"),
            "source": body.get("source", "manual"),
        }
        TABLE.put_item(Item=item)
        metrics.add_metric(name="FeedingsCreated", unit=MetricUnit.Count, value=1)
        return _resp(201, item)

    return _resp(405, {"message": "method not allowed"})

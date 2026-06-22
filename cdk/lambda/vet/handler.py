"""Vet records service.

Routes:
  GET  /vet/{cat_id}    list vet records for a cat
  POST /vet/{cat_id}    create a vet record

Gateway tools:
  get_vet_records       list active vet records for a cat
  create_vet_record     add a new vet record

Records have effective_from/effective_until windows. Only records where
effective_until is null or in the future are considered "active".
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from aws_lambda_powertools import Logger, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger(service="vet")
metrics = Metrics(namespace="CatDemo", service="vet")

_ddb_kwargs = {"endpoint_url": os.environ["DDB_ENDPOINT"]} if os.environ.get("DDB_ENDPOINT") else {}
_ddb = boto3.resource("dynamodb", **_ddb_kwargs)
VET_RECORDS = _ddb.Table(os.environ["VET_RECORDS_TABLE"])

VALID_RECORD_TYPES = {"dietary_restriction", "post_op_hold", "allergy", "weight_target"}


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


def _is_active(record: dict) -> bool:
    """Check if a vet record is currently active."""
    until = record.get("effective_until")
    if not until:
        return True  # open-ended
    try:
        until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
        return until_dt > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return True


def _get_records(cat_id: str, active_only: bool = True) -> list:
    """Get vet records for a cat, optionally filtering to active ones."""
    res = VET_RECORDS.query(
        KeyConditionExpression=Key("cat_id").eq(cat_id),
        ScanIndexForward=False,
    )
    items = res.get("Items", [])
    if active_only:
        items = [r for r in items if _is_active(r)]
    return items


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
        if tool_name == "get_vet_records":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            active_only = tool_input.get("active_only", True)
            records = _get_records(cat_id, active_only=active_only)
            metrics.add_metric(name="VetRecordsRead", unit=MetricUnit.Count, value=1)
            return records

        elif tool_name == "create_vet_record":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            record_type = tool_input.get("record_type")
            if record_type not in VALID_RECORD_TYPES:
                return {"error": f"record_type must be one of: {', '.join(sorted(VALID_RECORD_TYPES))}"}
            record = {
                "cat_id": cat_id,
                "record_id": f"{_now_iso()}-{uuid.uuid4().hex[:8]}",
                "record_type": record_type,
                "effective_from": tool_input.get("effective_from") or _now_iso(),
                "effective_until": tool_input.get("effective_until"),
                "details": tool_input.get("details") or {},
                "vet_signature": tool_input.get("vet_signature", "demo-vet"),
                "created_at": _now_iso(),
            }
            VET_RECORDS.put_item(Item=record)
            metrics.add_metric(name="VetRecordCreated", unit=MetricUnit.Count, value=1)
            return record

        elif tool_name == "recommend_feeding":
            # Phase 4 trap tool: returns 400 telling the agent to compose
            return {
                "error": "This tool does not provide direct recommendations. "
                "Compose a recommendation by calling: get_cat_profile, "
                "get_recent_feedings, get_vet_records, and get_health_score, "
                "then reason over the results.",
                "status": 400,
            }

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

    if not cat_id:
        return _resp(400, {"message": "cat_id is required"})

    if method == "GET" and path == "/vet/{cat_id}":
        records = _get_records(cat_id, active_only=False)
        metrics.add_metric(name="VetRecordsRead", unit=MetricUnit.Count, value=1)
        return _resp(200, records)

    if method == "POST" and path == "/vet/{cat_id}":
        body = json.loads(event.get("body") or "{}")
        record_type = body.get("record_type")
        if record_type not in VALID_RECORD_TYPES:
            return _resp(400, {"message": f"record_type must be one of: {', '.join(sorted(VALID_RECORD_TYPES))}"})

        record = {
            "cat_id": cat_id,
            "record_id": f"{_now_iso()}-{uuid.uuid4().hex[:8]}",
            "record_type": record_type,
            "effective_from": body.get("effective_from") or _now_iso(),
            "effective_until": body.get("effective_until"),
            "details": body.get("details") or {},
            "vet_signature": body.get("vet_signature", "demo-vet"),
            "created_at": _now_iso(),
        }
        VET_RECORDS.put_item(Item=record)
        metrics.add_metric(name="VetRecordCreated", unit=MetricUnit.Count, value=1)
        return _resp(201, record)

    return _resp(405, {"message": "method not allowed"})

"""Health service.

Routes:
  GET /health/{cat_id}           recent metrics for a cat
  GET /health/{cat_id}/alerts    active alerts for a cat
"""
import json
import os
from decimal import Decimal
import boto3
from boto3.dynamodb.conditions import Key

_ddb_kwargs = {"endpoint_url": os.environ["DDB_ENDPOINT"]} if os.environ.get("DDB_ENDPOINT") else {}
_ddb = boto3.resource("dynamodb", **_ddb_kwargs)
METRICS = _ddb.Table(os.environ["HEALTH_METRICS_TABLE"])
ALERTS = _ddb.Table(os.environ["HEALTH_ALERTS_TABLE"])


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
            return res.get("Items", [])

        elif tool_name == "get_health_alerts":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            res = ALERTS.query(
                KeyConditionExpression=Key("cat_id").eq(cat_id),
                Limit=50,
            )
            return res.get("Items", [])

        else:
            return {"error": f"unknown tool: {tool_name}"}
    except Exception as e:
        return {"error": str(e)}


def lambda_handler(event, _ctx):
    # AgentCore Gateway dispatch
    if hasattr(_ctx, 'client_context') and _ctx.client_context and hasattr(_ctx.client_context, 'custom') and _ctx.client_context.custom and 'bedrockAgentCoreToolName' in _ctx.client_context.custom:
        result = _dispatch_gateway(event, _ctx)
        return json.dumps(result, default=_default)

    method = event.get("httpMethod")
    path = event.get("resource", "")
    cat_id = (event.get("pathParameters") or {}).get("cat_id")

    if method != "GET" or not cat_id:
        return _resp(405, {"message": "method not allowed"})

    if path == "/health/{cat_id}":
        res = METRICS.query(
            KeyConditionExpression=Key("cat_id").eq(cat_id),
            ScanIndexForward=False,
            Limit=100,
        )
        return _resp(200, res.get("Items", []))

    if path == "/health/{cat_id}/alerts":
        res = ALERTS.query(
            KeyConditionExpression=Key("cat_id").eq(cat_id),
            Limit=50,
        )
        return _resp(200, res.get("Items", []))

    return _resp(404, {"message": "not found"})

"""Cat profile service.

Routes:
  GET  /cats           list cats
  POST /cats           create cat
  GET  /cats/{id}      get one cat

Bugs for AIOps investigation should be injected here directly — no env-var
feature flags. Commit on a `feature/*` branch and redeploy to `test`.
"""
import json
import os
import uuid
from decimal import Decimal
import boto3

# DDB_ENDPOINT is only set in local dev (docker-compose -> DynamoDB Local).
_ddb_kwargs = {"endpoint_url": os.environ["DDB_ENDPOINT"]} if os.environ.get("DDB_ENDPOINT") else {}
_ddb = boto3.resource("dynamodb", **_ddb_kwargs)
TABLE = _ddb.Table(os.environ["CAT_PROFILES_TABLE"])
NAME_INDEX = _ddb.Table(os.environ.get("CAT_NAME_INDEX_TABLE", "CatNameIndex"))


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == int(o) else float(o)
    raise TypeError


def _resp(status: int, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_default),
    }


def _dispatch_gateway(event, context):
    """Handle AgentCore Gateway tool invocations.
    
    Gateway sends:
      - event: the tool input parameters directly (e.g. {"cat_id": "hotpot"})
      - context.client_context.custom['bedrockAgentCoreToolName']: "target___tool_name"
    """
    # Extract tool name from context (strip target prefix)
    delimiter = "___"
    original_tool_name = context.client_context.custom.get("bedrockAgentCoreToolName", "")
    if delimiter in original_tool_name:
        tool_name = original_tool_name[original_tool_name.index(delimiter) + len(delimiter):]
    else:
        tool_name = original_tool_name
    
    tool_input = event  # event IS the tool input directly

    try:
        if tool_name == "get_cat_profile":
            cat_id = tool_input.get("cat_id")
            if not cat_id:
                return {"error": "cat_id is required"}
            item = TABLE.get_item(Key={"cat_id": cat_id}).get("Item")
            if not item:
                return {"error": f"cat '{cat_id}' not found"}
            return item

        elif tool_name == "list_cats":
            items = TABLE.scan(Limit=50).get("Items", [])
            return items

        elif tool_name == "lookup_cat_by_name":
            name = tool_input.get("name")
            if not name:
                return {"error": "name is required"}
            got = NAME_INDEX.get_item(Key={"name": name}).get("Item")
            if not got:
                return {"error": f"no cat found with name '{name}'"}
            return got

        else:
            return {"error": f"unknown tool: {tool_name}"}
    except Exception as e:
        return {"error": str(e)}


def lambda_handler(event, _ctx):
    # AgentCore Gateway dispatch — tool name is in context.client_context
    if hasattr(_ctx, 'client_context') and _ctx.client_context and hasattr(_ctx.client_context, 'custom') and _ctx.client_context.custom and 'bedrockAgentCoreToolName' in _ctx.client_context.custom:
        result = _dispatch_gateway(event, _ctx)
        return json.dumps(result, default=_default)

    method = event.get("httpMethod")
    path = event.get("resource", "")

    if method == "GET" and path == "/cats":
        items = TABLE.scan(Limit=50).get("Items", [])
        return _resp(200, items)

    if method == "POST" and path == "/cats":
        body = json.loads(event.get("body") or "{}")
        cat_id = body.get("cat_id") or str(uuid.uuid4())
        body["cat_id"] = cat_id
        TABLE.put_item(Item=body)
        # Auto-index name and nickname for reverse lookup
        for field in ("name", "nickname"):
            val = body.get(field)
            if val:
                NAME_INDEX.put_item(Item={"name": val, "cat_id": cat_id, "name_type": field})
        return _resp(201, body)

    if method == "GET" and path == "/cats/lookup":
        qs = event.get("queryStringParameters") or {}
        name = qs.get("name")
        if not name:
            return _resp(400, {"message": "name is required"})
        got = NAME_INDEX.get_item(Key={"name": name}).get("Item")
        if not got:
            return _resp(404, {"message": f"no cat found with name '{name}'"})
        return _resp(200, got)

    if method == "GET" and path == "/cats/{id}":
        cat_id = event["pathParameters"]["id"]
        got = TABLE.get_item(Key={"cat_id": cat_id}).get("Item")
        if not got:
            return _resp(404, {"message": "not found"})
        return _resp(200, got)

    return _resp(405, {"message": "method not allowed"})

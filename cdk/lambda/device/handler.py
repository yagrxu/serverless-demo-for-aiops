"""Device service.

Routes:
  GET  /devices                       list devices
  GET  /devices/{id}                  get one device
  POST /devices/{id}/commands         issue a command (feed, refill, etc.)
  POST /devices/{id}/telemetry        record a telemetry point

Inject source-level bugs directly here for AIOps scenarios.
"""
import json
import os
import time
import uuid
from decimal import Decimal
import boto3

_ddb_kwargs = {"endpoint_url": os.environ["DDB_ENDPOINT"]} if os.environ.get("DDB_ENDPOINT") else {}
_ddb = boto3.resource("dynamodb", **_ddb_kwargs)
DEVICES = _ddb.Table(os.environ["DEVICES_TABLE"])
TELEMETRY = _ddb.Table(os.environ["DEVICE_TELEMETRY_TABLE"])


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
            return items

        elif tool_name == "get_device":
            device_id = tool_input.get("device_id")
            if not device_id:
                return {"error": "device_id is required"}
            item = DEVICES.get_item(Key={"device_id": device_id}).get("Item")
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
            cmd = {
                "device_id": device_id,
                "ts": _now_iso(),
                "kind": "command",
                "command": command,
                "command_id": str(uuid.uuid4()),
            }
            TELEMETRY.put_item(Item=cmd)
            return cmd

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
    path_params = event.get("pathParameters") or {}
    device_id = path_params.get("id")

    if method == "GET" and path == "/devices":
        return _resp(200, DEVICES.scan(Limit=50).get("Items", []))

    if method == "GET" and path == "/devices/{id}":
        got = DEVICES.get_item(Key={"device_id": device_id}).get("Item")
        if not got:
            return _resp(404, {"message": "not found"})
        return _resp(200, got)

    if method == "POST" and path == "/devices/{id}/commands":
        body = json.loads(event.get("body") or "{}")
        cmd = {
            "device_id": device_id,
            "ts": _now_iso(),
            "kind": "command",
            "command": body.get("command"),
            "args": body.get("args"),
            "command_id": str(uuid.uuid4()),
        }
        TELEMETRY.put_item(Item=cmd)
        return _resp(202, cmd)

    if method == "POST" and path == "/devices/{id}/telemetry":
        body = json.loads(event.get("body") or "{}")
        point = {
            "device_id": device_id,
            "ts": body.get("ts") or _now_iso(),
            "kind": "telemetry",
            "metrics": body.get("metrics") or {},
        }
        TELEMETRY.put_item(Item=point)
        return _resp(201, point)

    return _resp(405, {"message": "method not allowed"})

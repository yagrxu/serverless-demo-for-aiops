"""MCP Server for the cat-care demo.

Exposes the 9 cat-care API operations as MCP-protocol tools via Streamable HTTP
transport. Acts as the local equivalent of AgentCore Gateway — receives MCP
tool calls from agents and translates them into HTTP requests to the API shim.

The MCP Server NEVER imports boto3 or accesses DynamoDB directly.
All data access goes through HTTP calls to the API shim.
"""

import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_URL = os.environ.get("API_URL", "http://localhost:8000")
MCP_PORT = int(os.environ.get("MCP_PORT", "8083"))

# ---------------------------------------------------------------------------
# MCP Server instance
# ---------------------------------------------------------------------------

mcp = FastMCP("cat-care-mcp-server", port=MCP_PORT)

# ---------------------------------------------------------------------------
# Shared HTTP client for connection pooling
# ---------------------------------------------------------------------------

_http_client = httpx.AsyncClient(base_url=API_URL, timeout=5.0)

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


async def _api_get(path: str, params: dict | None = None) -> str:
    """Async GET request to the REST API. Returns a JSON string."""
    try:
        r = await _http_client.get(path, params=params)
        r.raise_for_status()
        return json.dumps(r.json(), indent=2)
    except httpx.TimeoutException:
        return json.dumps({"error": f"API timeout: GET {path}"})
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"API error {e.response.status_code}: GET {path}"})
    except httpx.ConnectError:
        return json.dumps({"error": f"API connection refused: GET {path}"})


async def _api_post(path: str, body: dict) -> str:
    """Async POST request to the REST API. Returns a JSON string."""
    try:
        r = await _http_client.post(path, json=body)
        r.raise_for_status()
        return json.dumps(r.json(), indent=2)
    except httpx.TimeoutException:
        return json.dumps({"error": f"API timeout: POST {path}"})
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"API error {e.response.status_code}: POST {path}"})
    except httpx.ConnectError:
        return json.dumps({"error": f"API connection refused: POST {path}"})


# ---------------------------------------------------------------------------
# MCP tool functions
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_cat_profile(cat_id: str) -> str:
    """Look up a cat's profile by ID. Returns name, breed, and birthday."""
    return await _api_get(f"/cats/{cat_id}")


@mcp.tool()
async def list_cats(name: str | None = None) -> str:
    """List cats. If a name or nickname is provided, returns only the matching cat with its cat_id. Otherwise returns all registered cats.

    Args:
        name: Optional cat name or nickname to filter by (e.g., '火锅', '烤烤').
    """
    if name:
        return await _api_get("/cats/lookup", params={"name": name})
    return await _api_get("/cats")


@mcp.tool()
async def get_feedings(cat_id: str) -> str:
    """Get recent feeding history for a cat.

    Args:
        cat_id: The ID of the cat to look up feedings for.
    """
    return await _api_get("/feedings", params={"cat_id": cat_id})


@mcp.tool()
async def record_feeding(cat_id: str, amount_grams: int, food_type: str) -> str:
    """Record a new feeding event for a cat.

    Args:
        cat_id: The ID of the cat being fed.
        amount_grams: Amount of food in grams.
        food_type: Type of food (e.g., 'dry', 'wet').
    """
    return await _api_post("/feedings", body={
        "cat_id": cat_id,
        "amount_grams": amount_grams,
        "food_type": food_type,
    })


@mcp.tool()
async def get_health_metrics(cat_id: str) -> str:
    """Get recent health metrics for a cat.

    Args:
        cat_id: The ID of the cat to look up health metrics for.
    """
    return await _api_get(f"/health/{cat_id}")


@mcp.tool()
async def get_health_alerts(cat_id: str) -> str:
    """Get active health alerts for a cat.

    Args:
        cat_id: The ID of the cat to check alerts for.
    """
    return await _api_get(f"/health/{cat_id}/alerts")


@mcp.tool()
async def list_devices() -> str:
    """List all registered IoT devices."""
    return await _api_get("/devices")


@mcp.tool()
async def get_device(device_id: str) -> str:
    """Get details for a specific device.

    Args:
        device_id: The ID of the device to look up.
    """
    return await _api_get(f"/devices/{device_id}")


@mcp.tool()
async def send_device_command(device_id: str, command: str) -> str:
    """Send a command to an IoT device (e.g., 'dispense', 'refill').

    Args:
        device_id: The ID of the device to command.
        command: The command to send (e.g., 'dispense', 'refill').
    """
    return await _api_post(f"/devices/{device_id}/commands", body={"command": command})


# ---------------------------------------------------------------------------
# Health check endpoint for startup scripts
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    """Health check endpoint for startup script readiness probes."""
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="streamable-http")

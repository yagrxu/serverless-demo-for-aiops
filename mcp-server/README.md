# MCP Server — Cat-Care Demo

Local MCP (Model Context Protocol) server that exposes the 9 cat-care API
operations as MCP tools over SSE transport. This is the local equivalent of
AgentCore Gateway in the AWS production architecture.

## How it works

```
Agents (LangGraph / Strands)
        │
        │  MCP protocol (SSE)
        ▼
   MCP Server :8083
        │
        │  HTTP GET / POST
        ▼
   API Shim :8000  (Docker)
        │
        │  boto3
        ▼
   DynamoDB Local :8001
```

The MCP Server receives tool calls from agents and translates them into HTTP
requests to the FastAPI API shim. It never accesses DynamoDB directly.

## Prerequisites

- Python 3.11+
- The API shim running on port 8000 (`docker compose up -d`)

## Quick start

```bash
# Create a virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start the MCP Server (defaults: API_URL=http://localhost:8000, port 8083)
python server.py
```

## Environment variables

| Variable   | Default                  | Description                        |
|------------|--------------------------|------------------------------------|
| `API_URL`  | `http://localhost:8000`  | Base URL of the API shim           |
| `MCP_PORT` | `8083`                   | Port for the SSE transport         |

## Registered tools

| Tool                 | Method | API Path                      |
|----------------------|--------|-------------------------------|
| `get_cat_profile`    | GET    | `/cats/{cat_id}`              |
| `list_cats`          | GET    | `/cats`                       |
| `get_feedings`       | GET    | `/feedings?cat_id=...`        |
| `record_feeding`     | POST   | `/feedings`                   |
| `get_health_metrics` | GET    | `/health/{cat_id}`            |
| `get_health_alerts`  | GET    | `/health/{cat_id}/alerts`     |
| `list_devices`       | GET    | `/devices`                    |
| `get_device`         | GET    | `/devices/{device_id}`        |
| `send_device_command`| POST   | `/devices/{device_id}/commands`|

## Health check

```bash
curl http://localhost:8083/health
# {"status": "ok"}
```

## Using with up.sh

The startup script (`local/scripts/up.sh`) manages the MCP Server automatically.
You only need to run it manually if you want to develop or debug the MCP Server
in isolation.

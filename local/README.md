# Local development scripts

Helper scripts for running the demo on your laptop.

## Scripts

| Script | Description |
|---|---|
| `scripts/up.sh` | Start the full stack (DDB + API + MCP Server + agents + UIs) |
| `scripts/down.sh` | Tear everything down |
| `scripts/status.sh` | Health check all services |
| `scripts/init-ddb.sh` | Create DynamoDB tables (idempotent) |
| `scripts/seed.sh` | Seed sample data into the API |
| `scripts/open-agent.sh` | Open an agent folder in VS Code |

## Quick start

```bash
export AWS_PROFILE=<your-bedrock-profile>
./local/scripts/up.sh
```

## Open agent in VS Code

```bash
./local/scripts/open-agent.sh langgraph   # open LangGraph agent
./local/scripts/open-agent.sh strands     # open Strands agent
./local/scripts/open-agent.sh all         # open both
```

## Flags

```bash
./local/scripts/up.sh --no-ui      # backend + agents only
./local/scripts/up.sh --no-seed    # skip seed step
./local/scripts/up.sh --no-agents  # DDB + API + MCP Server, start agents yourself
./local/scripts/up.sh --no-mcp     # skip MCP Server (agents call API directly)
```

## Tear down

```bash
./local/scripts/down.sh            # stop everything
./local/scripts/down.sh --purge    # also prune docker images/volumes + wipe logs
```

## Ports

| Port | Service | Runs in |
|------|---------|---------|
| 8001 | DynamoDB Local | Docker |
| 8000 | API (Lambda shim) | Docker |
| 8083 | MCP Server | Host |
| 8081 | LangGraph agent | Host |
| 8082 | Strands agent | Host |
| 3000 | All UIs (Next.js) | Host |

# Local testing

Run the whole demo on your laptop — no AWS deploy needed. You'll get:

- DynamoDB Local on `:8001`
- The four Lambda handlers wrapped in FastAPI on `:8000`
- MCP Server on `:8083` (local equivalent of AgentCore Gateway)
- Two agents running on the host: LangGraph on `:8081`, Strands on `:8082`
- Three React UIs via Vite dev servers on `:5173` / `:5174` / `:5175`

The same handler code that CDK ships to AWS Lambda is what runs locally —
a thin wrapper (`local/api/app.py`) replays each HTTP request as an
API-Gateway-shaped event, so bugs injected for AIOps work reproduce here
too.

The MCP Server runs on the host and translates MCP tool calls from agents
into HTTP requests to the API shim — mirroring the AgentCore Gateway
pattern used in the AWS production deployment.

Agents run directly on the host (not in Docker) so they inherit your
shell's AWS credentials and environment variables. No `~/.aws` mount
needed.

## Prerequisites

- Docker (with `compose`)
- Python 3.12+ with `pip` (for running agents on the host)
- Node.js 20+ and npm
- AWS credentials configured in your shell with Bedrock `InvokeModel`
  access — the agents call Bedrock directly
- `aws` CLI v2 (only used by the DDB bootstrap script)

## One-shot bring-up

```bash
export AWS_PROFILE=<your-bedrock-profile>
./local/scripts/up.sh
```

`up.sh` starts Docker (DDB + API), creates tables, seeds data, starts
the MCP Server, starts both agents on the host via `uvicorn`, and starts
the three Vite dev servers. The startup order is:
Docker → MCP Server → Agents → UIs. Pids and logs go under
`local/.run/` and `local/.logs/`.

Flags:

```bash
./local/scripts/up.sh --no-ui      # backend + agents only, skip vite
./local/scripts/up.sh --no-seed    # skip seed step
./local/scripts/up.sh --no-agents  # docker + MCP server + seed only, start agents yourself
./local/scripts/up.sh --no-mcp     # skip MCP server (agents call API directly)
```

Override the Bedrock model:

```bash
MODEL_ID=anthropic.claude-sonnet-4-20250514-v1:0 ./local/scripts/up.sh
```

Check everything is up:

```bash
./local/scripts/status.sh
```

Tear down:

```bash
./local/scripts/down.sh           # stop agents + UIs + containers
./local/scripts/down.sh --purge   # also prune images/volumes + wipe logs
```

## UIs

Once `up.sh` finishes, click through:

- **http://localhost:5173** — Chatbot UI, split-screen comparison of
  LangGraph (left) vs Strands (right). Same message goes to both agents
  in parallel.
- **http://localhost:5174** — Device Simulator, sends telemetry and
  commands directly to the API on `:8000`.
- **http://localhost:5175** — Admin Console, lists cats, creates new
  ones, shows feedings and alerts per cat.

The Chatbot UI defaults to `http://localhost:8081` (LangGraph) and
`http://localhost:8082` (Strands). Override with `VITE_LANGGRAPH_URL`
and `VITE_STRANDS_URL` env vars.

## How the pieces fit together

```
UIs (host, via vite)        :5173 / :5174 / :5175
       │
       │  HTTP
       ▼
langgraph agent (host)      :8081 ──┐
strands agent   (host)      :8082 ──┤
                                    │ MCP protocol (SSE)
                                    ▼
MCP Server      (host)      :8083
                                    │
                                    │ HTTP (tool calls)
                                    ▼
local API shim  (docker)    :8000  (boto3 → DynamoDB Local)
                                    │
                                    ▼
DynamoDB Local  (docker)    :8001
```

- Lambda handlers read `DDB_ENDPOINT` (set to `http://ddb:8000` inside
  compose) so boto3 talks to DynamoDB Local. In AWS it's unset and the
  default endpoint is used — same handler code.
- Agents connect to the MCP Server via
  `MCP_SERVER_URL=http://localhost:8083/mcp` using Streamable HTTP
  transport. The MCP Server forwards tool calls to the API shim using
  `API_URL=http://localhost:8000`.
- Agents call Bedrock using your shell's AWS credentials directly.

## Iteration

- **Lambda / handler code** — FastAPI runs with `--reload` and the host
  `cdk/lambda` directory is bind-mounted into the `api` container, so
  saving a file reloads the handler. No `docker compose restart`.
- **Agent code** — agents run on the host via `uvicorn`. Restart them
  manually or add `--reload` when starting:

  ```bash
  MCP_SERVER_URL=http://localhost:8083/mcp python3 -m uvicorn server:app --port 8081 --reload
  ```

- **UI code** — Vite hot-reloads on save. No action needed.

## Starting agents manually

If you used `--no-agents`, start the MCP Server (if not already running)
and each agent yourself:

```bash
# MCP Server (skip if up.sh already started it)
cd mcp-server
source .venv/bin/activate          # up.sh creates the venv automatically
API_URL=http://localhost:8000 python server.py
# Health check: curl http://localhost:8083/health

# LangGraph agent (in another terminal)
cd agents/langgraph
MCP_SERVER_URL=http://localhost:8083/mcp python3 -m uvicorn server:app --port 8081

# Strands agent (in another terminal)
cd agents/strands
MCP_SERVER_URL=http://localhost:8083/mcp python3 -m uvicorn server:app --port 8082
```

You can start just one agent if you only want to test that framework.

## Talking to the services by hand

```bash
# REST API
curl -s http://localhost:8000/cats | jq
curl -s -X POST http://localhost:8000/cats \
  -H 'Content-Type: application/json' \
  -d '{"cat_id":"oreo","name":"Oreo","breed":"tuxedo"}' | jq

# MCP Server health check
curl -s http://localhost:8083/health | jq

# LangGraph agent directly
curl -s -X POST http://localhost:8081/invocations \
  -H 'Content-Type: application/json' \
  -d '{"input":{"message":"how is mittens","cat_id":"mittens"}}' | jq

# Strands agent directly
curl -s -X POST http://localhost:8082/invocations \
  -H 'Content-Type: application/json' \
  -d '{"input":{"message":"how is mittens","cat_id":"mittens"}}' | jq
```

## Tear everything down

```bash
./local/scripts/down.sh        # stops agents, UIs, and docker containers
./local/scripts/down.sh --purge  # also prune images/volumes + wipe logs
```

## Troubleshooting

**`api` container logs `KeyError: 'CAT_PROFILES_TABLE'`** — compose
environment didn't pick up. Make sure you're running `docker compose up`
from the repo root so it finds `docker-compose.yml`.

**`ResourceNotFoundException` from DDB Local** — tables don't exist.
Run `./local/scripts/init-ddb.sh` against the running `ddb` service.

**Agent logs `NoCredentialsError`** — your shell doesn't have AWS
credentials configured. Set `AWS_PROFILE` or export `AWS_ACCESS_KEY_ID`
/ `AWS_SECRET_ACCESS_KEY` before starting agents.

**Agent logs `AccessDeniedException: bedrock:InvokeModel`** — your AWS
profile doesn't have Bedrock model access in us-east-1, or the specific
model isn't enabled in the console. Model access is per-region and
per-account. Default model is `anthropic.claude-haiku-4-5-20251001-v1:0`
(plain foundation id, not the `us.` cross-region inference profile —
ADOT's `bedrock:CountTokens` rejects inference-profile ids).

**UI shows CORS error** — the API shim adds `Access-Control-Allow-Origin: *`
and compose publishes port `:8000`. Check that `curl http://localhost:8000/cats`
works from the host first.

**MCP Server not responding on `:8083`** — check the log at
`local/.logs/mcp-server.log`. Common causes: the API shim isn't running
(MCP Server needs it at tool-call time, not at startup), or another
process is already on port 8083. Verify with
`curl http://localhost:8083/health`.

**Agent logs MCP connection errors** — the MCP Server must be running
before agents start. If you started agents manually, make sure the MCP
Server is healthy first (`curl http://localhost:8083/health`). Agents
retry the connection on startup, but will fail after 10 attempts.

**Port already in use** — another service is on `:8000` / `:8083` /
`:8081`–`:8082` / `:8001` / `:5173`–`:5175`. Either free the port or
edit the mapping in `docker-compose.yml` / the agent start command /
the Vite config.

# serverless-demo-for-aiops

A deliberately-breakable serverless cat-care IoT demo, used to exercise
AIOps investigation workflows. Everything is defined in a single CDK
(TypeScript) app and runs on fully managed services:

- **API Gateway + Python Lambdas** — `cat-profile`, `device`, `feeding`, `health`
- **DynamoDB** — one table per bounded context (pay-per-request)
- **AgentCore Runtime** — two independent agents (LangGraph + Strands), packaged as Docker images pushed to ECR
- **CloudFront + S3** — static hosting for the chatbot, device simulator, and admin console UIs

No Cognito. The UIs are public but served only via CloudFront/HTTPS with
Origin Access Control; the S3 bucket has public access blocked.

Failure modes are injected **directly in Lambda / agent source code** on
`feature/*` branches, deployed to the test account via the `test` pointer,
and investigated there. No env-var injection knobs.

## Repo layout

```
cdk/
  bin/app.ts              # App entry — wires Data, Api, Agents, Ui stacks
  lib/
    config.ts             # Project-wide knobs
    data-stack.ts         # DynamoDB tables
    api-stack.ts          # API Gateway + Python Lambdas
    ecr-stack.ts          # Named ECR repos for the two agent images
    gateway-stack.ts      # AgentCore Gateway (MCP) + Lambda targets
    agent-stack.ts        # AgentCore runtimes (langgraph, strands)
    ui-stack.ts           # CloudFront + S3 for the three UIs
  lambda/
    cat-profile/          # Python handler — edit for source-level bug injection
    device/
    feeding/
    health/
agents/
  langgraph/              # ReAct agent using LangChain + LangGraph
  strands/                # Model-driven agent using Strands SDK
mcp-server/               # MCP Server — local equivalent of AgentCore Gateway
ui/
  chatbot/                # Split-screen comparison of LangGraph vs Strands
  device-simulator/
  admin-console/
scripts/
  ci/                     # OIDC setup / teardown for GitHub Actions
.github/workflows/
  deploy.yml              # OIDC deploy to test / release
tmp/                      # Previous CDK app + legacy scripts, kept for reference
CICD.md
CLAUDE.md
```

## Prerequisites

- Node.js 20+
- Python 3.12 (for editing Lambda handlers and agents)
- Docker (for `cdk deploy` — builds the two agent images)
- AWS CLI with the `cloudops-demo` profile configured

## Local development

See [`docs/local-testing.md`](./docs/local-testing.md) for full details.

```bash
export AWS_PROFILE=<your-bedrock-profile>
./local/scripts/up.sh
```

This starts DDB + API in Docker, the MCP Server and both agents on the
host, and three Vite UIs. Agents connect to the MCP Server (port 8083)
which forwards tool calls to the API — mirroring the AgentCore Gateway
pattern used in production.

## Deploy

The AgentStack consumes image URIs from the named ECR repos, so the
flow is three phases: create repos → build+push images → deploy agents.
CI runs this automatically. For a local deploy:

```bash
cd cdk
npm ci
npx cdk synth

# 1. Create ECR repos + the non-agent stacks (skip agents on first run)
AWS_PROFILE=cloudops-demo npx cdk deploy \
  aiops-cat-demo-ecr aiops-cat-demo-data aiops-cat-demo-api aiops-cat-demo-gateway aiops-cat-demo-ui \
  -c skipAgents=true

# 2. Build and push each agent image (amd64) to its repo
ACCOUNT=$(aws --profile cloudops-demo sts get-caller-identity --query Account --output text)
TAG=$(git rev-parse HEAD)
aws --profile cloudops-demo ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.us-east-1.amazonaws.com"
for name in langgraph strands; do
  docker buildx build --platform linux/amd64 \
    -t "$ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/aiops-cat-demo-$name:$TAG" \
    --push "agents/$name"
done

# 3. Deploy AgentStack pointing at the pushed tag
AWS_PROFILE=cloudops-demo npx cdk deploy aiops-cat-demo-agents -c imageTag=$TAG
```

Or push a feature branch to the `test` pointer and let CI deploy:

```bash
git push --force-with-lease origin feature/bug-xyz:test
```

See [`CICD.md`](./CICD.md) for the branch model and the OIDC setup.

## Endpoints

```
GET  /cats
POST /cats
GET  /cats/{id}

GET  /devices
GET  /devices/{id}
POST /devices/{id}/commands
POST /devices/{id}/telemetry

GET  /feedings?cat_id=<id>
POST /feedings

GET  /health/{cat_id}
GET  /health/{cat_id}/alerts
```

## Agents

Two independent AgentCore Runtimes that connect to the data layer
through AgentCore Gateway (MCP protocol → Lambda):

```
                                                    Production:
Chatbot UI ──┬── invoke ──► LangGraph Runtime ──┐
             └── invoke ──► Strands Runtime   ──┤
                                                │ MCP
                                                ▼
                                        AgentCore Gateway ──► Lambda ──► DynamoDB

                                                    Local dev:
Chatbot UI ──┬── POST ──► LangGraph :8081 ──┐
             └── POST ──► Strands :8082   ──┤
                                            │ MCP (SSE)
                                            ▼
                                    MCP Server :8083 ──► API shim :8000 ──► DDB Local
```

In production, AgentCore Gateway (`gateway-stack.ts`) translates MCP
tool calls directly into Lambda invocations. Locally, the MCP Server
(`mcp-server/`) mirrors the same pattern. Both agents use Claude Sonnet
4.6 (global) by default. Override with `MODEL_ID`.

## Previous design

The earlier Items-and-S3 demo lives under `tmp/cdk/` plus `tmp/scenarios/`,
`tmp/load/`, and `tmp/setup.sh`. Useful as reference — not deployed.

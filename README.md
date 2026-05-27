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
  bin/app.ts              # App entry — wires Data, Api, Agents, Fargate, Ui, Observability stacks
  lib/
    config.ts             # Project-wide knobs
    data-stack.ts         # DynamoDB tables
    api-stack.ts          # API Gateway + Python Lambdas (ADOT + Powertools)
    ecr-stack.ts          # Named ECR repos for the agent + chatbot images
    gateway-stack.ts      # AgentCore Gateway (MCP) + Lambda targets + X-Ray delivery
    agent-stack.ts        # AgentCore runtimes (langgraph, strands)
    fargate-stack.ts      # ECS Fargate + ALB hosting the chatbot BFF
    trafgen-stack.ts      # ECS Fargate scheduled task for the traffic generator
    ui-stack.ts           # CloudFront + S3 for the device-sim and admin UIs
    observability-stack.ts # Application Signals discovery (one-shot per account+region)
    observability.ts      # Region→ADOT-layer-ARN table + Lambda wiring helpers
  lambda/
    cat-profile/          # Python handler — edit for source-level bug injection
    device/
    feeding/
    health/
agents/
  langgraph/              # ReAct agent using LangChain + LangGraph
  strands/                # Model-driven agent using Strands SDK
trafgen/                  # Traffic generator — produces realistic load for AIOps baseline
evaluation/               # Agent evaluation framework — LLM-as-judge scoring for CI
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
- **Python 3.12** (required — some dependencies like `aws-sdk-bedrock-runtime` only support >= 3.12)
- Docker (for `cdk deploy` — builds the two agent images)
- AWS CLI with the `cloudops-demo` profile configured

### Python 3.12 setup with pyenv

We use [pyenv](https://github.com/pyenv/pyenv) to manage Python versions. If you don't have it yet:

```bash
# macOS (Homebrew)
brew install pyenv

# Add to your shell profile (~/.zshrc or ~/.bashrc)
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
echo 'eval "$(pyenv init -)"' >> ~/.zshrc
source ~/.zshrc
```

Install and activate Python 3.12:

```bash
pyenv install 3.12
pyenv local 3.12    # sets .python-version in the repo root
python --version    # should show Python 3.12.x
```

### Virtual environment setup

Each Python component (`agents/langgraph`, `agents/strands`, `cdk/lambda/*`) maintains its own venv. Example for the Strands agent:

```bash
cd agents/strands
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For Lambda handlers (used when running tests locally):

```bash
cd cdk/lambda/cat-profile
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # if present, or install boto3 manually
```

> **CI note:** The GitHub Actions PR test workflow uses Python 3.12 exclusively. Python 3.10/3.11 are not supported due to dependency constraints (`aws-sdk-bedrock-runtime >= 0.6.0` requires Python 3.12+).

## Local development

See [`docs/local-testing.md`](./docs/local-testing.md) for full details.
See [`docs/local-vs-cloud.md`](./docs/local-vs-cloud.md) for a detailed
technical comparison between local and cloud environments.

```bash
export AWS_PROFILE=<your-bedrock-profile>
./local/scripts/up.sh
```

This starts DDB + API in Docker, the MCP Server and both agents on the
host, and three Vite UIs. Agents connect to the MCP Server (port 8083)
which forwards tool calls to the API — mirroring the AgentCore Gateway
pattern used in production.

## Deploy

The AgentStack and FargateStack consume image URIs from the named ECR
repos, so the flow is three phases: create repos → build+push images →
deploy agent + UI stacks. CI runs this automatically. For a local
deploy:

```bash
cd cdk
npm ci
npx cdk synth

# 1. Create ECR repos + the non-agent stacks. Do NOT pass
#    -c skipAgents=true; app.ts must always construct every stack so
#    the cross-stack ECR exports stay stable. cdk deploy only deploys
#    the names below.
AWS_PROFILE=cloudops-demo npx cdk deploy \
  aiops-cat-demo-ecr aiops-cat-demo-observability \
  aiops-cat-demo-data aiops-cat-demo-api aiops-cat-demo-gateway \
  -c imageTag=$(git rev-parse HEAD)

# 2. Build and push each image (linux/arm64) to its repo
ACCOUNT=$(aws --profile cloudops-demo sts get-caller-identity --query Account --output text)
TAG=$(git rev-parse HEAD)
aws --profile cloudops-demo ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.us-east-1.amazonaws.com"
for name in langgraph strands; do
  docker buildx build --platform linux/arm64 \
    -t "$ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/aiops-cat-demo-$name:$TAG" \
    --push "agents/$name"
done
docker buildx build --platform linux/arm64 \
  -t "$ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/aiops-cat-demo-chatbot:$TAG" \
  --push "ui/chatbot"

# 3. Deploy the stacks that consume the pushed images
AWS_PROFILE=cloudops-demo npx cdk deploy \
  aiops-cat-demo-agents aiops-cat-demo-fargate aiops-cat-demo-ui \
  -c imageTag=$TAG
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
POST /feedings              (enforces daily limits: 200g/cat, wet 100g, dry 150g, 2h interval)

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
(`mcp-server/`) mirrors the same pattern. Both agents use Claude Haiku
4.5 by default. Override with `MODEL_ID`.

## Evaluation framework

The `evaluation/` directory provides automated quality checks for both agents:

```bash
cd evaluation
pip install -r requirements.txt

# Collect responses from both agents
python runner.py --dataset datasets/comparative.yaml

# Collect + LLM-as-judge scoring in one command
python runner.py --dataset datasets/comparative.yaml --judge --fail-on-regression
```

The judge uses Bedrock Claude to score each response against category-specific
criteria (accuracy, safety, ambiguity handling, context retention, etc.).
Scoring rules: any single case below 0.7 = FAIL, average below 0.75 = FAIL.

In CI, the `agent-evaluation` job in `pr-tests.yml` runs automatically on PRs
that touch `agents/`, `evaluation/`, or `mcp-server/`. It starts the full local
stack, runs all test cases, and gates the PR on the judge verdict.

See [`evaluation/README.md`](./evaluation/README.md) for full details.

## How to investigate a bug injected on a feature/* branch

Bugs are injected directly in Lambda or agent source code on `feature/*`
branches and deployed to the test account via the `test` pointer. Once
traffic hits the injected code, CloudWatch surfaces the signal
automatically — no log grepping required.

### CloudWatch Application Signals

Application Signals is enabled account-wide via `CfnDiscovery` in the
Observability stack. It covers:

- **Lambda + API Gateway** — the ADOT layer on each Lambda and
  `tracingEnabled` on the API stage feed the Service Map. Every handler
  appears with downstream DynamoDB edges after one request.
- **AgentCore Runtimes** — both LangGraph and Strands containers run
  under `opentelemetry-instrument`, so their spans flow into the same
  Service Map and Transaction Search index.

Open the Service Map:
`https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#application-signals:services`

### CloudWatch Dashboards

Three persona-scoped dashboards are deployed by the Observability stack:

| Dashboard | Focus | Console link |
|-----------|-------|--------------|
| `aiops-cat-demo-sre` | Latency, errors, throttles, DDB capacity, alarm status | [SRE Dashboard](https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-sre) |
| `aiops-cat-demo-genai` | Per-runtime invocation latency, token usage, tool-call duration, Gateway errors | [GenAI Dashboard](https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-genai) |
| `aiops-cat-demo-business` | Domain KPIs — feedings, device commands, health alerts | [Business Dashboard](https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards/dashboard/aiops-cat-demo-business) |

### Alarms and anomaly detectors

23 alarms fire to a single SNS topic (`aiops-cat-demo-alarms`). Key ones:

- Lambda Duration p99 anomaly (×4) and Errors > 0 (×4)
- API Gateway 5xx anomaly
- DynamoDB ThrottledRequests > 0 per table (×7)
- `DeviceWriteSuccess` below anomaly band (catches silent DDB failures)
- Per-runtime token anomaly (catches infinite loops)
- Bedrock throttle, Gateway target errors, RUM JS error rate, CloudFront 5xx

All alarms appear in the SRE dashboard's top-row `AlarmStatusWidget`.

### Contributor Insights

Enabled on `DeviceTelemetry` and `HealthMetrics` tables. Shows the
hottest partition keys when throttles spike — useful for the hot-partition
and full-table-scan bug scenarios.

### Investigation workflow

1. **Start from the alarm** — check the SRE dashboard alarm row or the
   SNS email notification.
2. **Drill into Transaction Search** — find the trace that triggered the
   alarm. Transaction Search indexes spans into `aws/spans/default`:
   `https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#transactionsearch:`
3. **For agent-layer issues** — open the GenAI Observability console to
   see per-session traces, token usage, and tool-call sequences:
   `https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#gen-ai-observability`
4. **Use saved Logs Insights queries** — four pre-built queries are
   deployed: `A-all-errors-for-trace`, `B-slowest-tool-calls`,
   `C-ddb-throttles-by-table`, `D-injected-bug-marker`.
5. **Check Contributor Insights** — if DDB throttles fired, the CI
   widget on the SRE dashboard shows which partition key is hot.

## Previous design

The earlier Items-and-S3 demo lives under `tmp/cdk/` plus `tmp/scenarios/`,
`tmp/load/`, and `tmp/setup.sh`. Useful as reference — not deployed.

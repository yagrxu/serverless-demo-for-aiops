# Agentic Solution Development Lifecycle

## Overview

End-to-end lifecycle for developing, evaluating, and operating agentic solutions — from local iteration to production quality monitoring and automated root-cause analysis.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 1: INNER LOOP (Local Dev)                                        │
│  Kiro IDE + Amazon Omni Plugin                                          │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                           │
│  │  Write   │──▶│  Trace   │──▶│  Iterate │                           │
│  │  Prompt  │   │  Locally │   │  Fast    │                           │
│  └──────────┘   └──────────┘   └──────────┘                           │
│  See: tool calls, reasoning, latency per step, token usage             │
└────────────────────────────────────┬────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 2: OFFLINE EVALUATION (Pre-deploy gate)                          │
│  Dataset + Model Comparison + Scoring                                   │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐           │
│  │  Dataset │──▶│  Run N   │──▶│  Score   │──▶│  Compare │           │
│  │  (fixed) │   │  Models  │   │  (judge) │   │  Report  │           │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘           │
│  Gate: no deploy if correctness/tool_selection regresses               │
└────────────────────────────────────┬────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 3: PRODUCTION OBSERVABILITY (Runtime)                            │
│  Application Signals + ADOT + CloudWatch                                │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                           │
│  │  Traces  │──▶│  Metrics │──▶│  Dashbrd │                           │
│  │  (X-Ray) │   │  (CW)    │   │  (Ops)   │                           │
│  └──────────┘   └──────────┘   └──────────┘                           │
│  Every invocation: latency, tokens, tool calls, errors                 │
└────────────────────────────────────┬────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 4: PRODUCTION SCORING (Continuous)                               │
│  AgentCore Evaluations API — async, sampled                             │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                           │
│  │  Sample  │──▶│  Judge   │──▶│  Metric  │                           │
│  │  (10-20%)│   │  (async) │   │  (CW)    │                           │
│  └──────────┘   └──────────┘   └──────────┘                           │
│  Publish: helpfulness, faithfulness, hallucination scores as CW metrics│
└────────────────────────────────────┬────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Phase 5: DETECTION & ANALYSIS (AIOps)                                  │
│  Alarms + DevOps Agent auto-investigation                               │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐           │
│  │  Anomaly │──▶│  Alarm   │──▶│  DevOps  │──▶│  Root    │           │
│  │  Detect  │   │  (SNS)   │   │  Agent   │   │  Cause   │           │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘           │
│  Causes: prompt regression | tool failure | model degradation | data   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Cross-Cutting: Prompt Management

### Problem

Prompts hardcoded in source (`SYSTEM_PROMPT = "..."`) create several issues:
- Changing a prompt requires a code deploy (rebuild image, push, redeploy stack)
- No version history of prompt iterations separate from code changes
- Can't A/B test prompts without branching code
- Can't roll back a bad prompt without rolling back the entire deploy
- Evaluations can't pin a specific prompt version for reproducibility

### Design: Prompts as Versioned Configuration

```
prompts/
├── strands/
│   └── system.yaml          # Prompt source of truth
├── langgraph/
│   └── system.yaml
└── voice/
    └── system.yaml
```

**Prompt file format:**

```yaml
name: strands-system-prompt
version: 3
description: Cat-care assistant system prompt for strands agent
model_hint: us.anthropic.claude-haiku-4-5-20251001-v1:0

prompt: |
  You are a helpful cat-care assistant. You help users manage their cats'
  feeding schedules, health monitoring, and IoT devices (feeders, fountains,
  trackers). Use the available tools to look up real data before answering.
  Be concise and friendly.

  Most tools require a cat_id, not a cat name. When the user refers to a cat
  by name or nickname, resolve it to a cat_id first before calling other tools.
```

### Storage & Delivery

| Environment | Storage | How agent loads |
|-------------|---------|-----------------|
| Local dev | File on disk (`prompts/strands/system.yaml`) | Agent reads at startup |
| Test/Prod | AWS Systems Manager Parameter Store or S3 | Agent reads at startup + periodic refresh (5 min TTL) |

**Why SSM Parameter Store:**
- Built-in versioning (every `put-parameter` creates a new version)
- IAM-controlled access (agent role can read, deploy role can write)
- No extra infra (already in every account)
- Supports up to 8KB Advanced parameters (prompts rarely exceed this)
- CloudTrail audit trail on every change

**Parameter path convention:**
```
/aiops-cat-demo/prompts/strands/system     → current prompt text
/aiops-cat-demo/prompts/langgraph/system   → current prompt text
```

### Agent Code Change

Current (hardcoded):
```python
SYSTEM_PROMPT = "You are a helpful cat-care assistant..."
```

New (loaded from config):
```python
from prompt_loader import load_prompt

SYSTEM_PROMPT = load_prompt("strands", "system")
```

The `prompt_loader` module:
1. On cold start: reads from SSM (or local file if `PROMPT_SOURCE=local`)
2. Caches in memory with 5-min TTL
3. Falls back to a bundled default if SSM is unreachable (resilience)

### CI/CD Integration

```
Developer edits prompts/strands/system.yaml
        │
        ▼
┌───────────────────────────────────────────────────┐
│  PR CI Pipeline                                    │
│  1. Lint prompt (non-empty, < 8KB, valid YAML)    │
│  2. Run offline eval with NEW prompt              │
│  3. Compare scores vs baseline (old prompt)       │
│  4. Block if correctness regresses > 5%           │
└───────────────────────────────────────────────────┘
        │ (merge)
        ▼
┌───────────────────────────────────────────────────┐
│  Deploy Pipeline                                   │
│  1. Upload prompt to SSM Parameter Store          │
│     (creates new version automatically)           │
│  2. Agent picks up new prompt within 5 min        │
│     (or: trigger immediate refresh via signal)    │
│  NO container rebuild needed                      │
└───────────────────────────────────────────────────┘
```

### Prompt Versioning & Rollback

- SSM keeps full version history: `aws ssm get-parameter-history --name /aiops-cat-demo/prompts/strands/system`
- Rollback = put previous version content as new version (or point to version N via label)
- Evaluation reports record which prompt version was active: ties quality scores to prompt iterations
- Diff between versions: `aws ssm get-parameter --name ... --version 2` vs `--version 3`

### Prompt + Model Matrix

Evaluations should test the cartesian product:

```
Prompt v3 × claude-sonnet-4-6  → score
Prompt v3 × claude-haiku-4-5   → score
Prompt v3 × nova-pro           → score
Prompt v2 × claude-haiku-4-5   → score (baseline)
```

This lets you answer: "Did the prompt change help? Or did the model change help? Or both?"

### Repo Layout Change

```
prompts/                       # NEW — prompt source files
  strands/system.yaml
  langgraph/system.yaml
  voice/system.yaml
agents/strands/
  prompt_loader.py             # NEW — SSM/local loader with caching
  server.py                    # Modified — uses prompt_loader
```

### Open Questions

- [ ] Should prompts support template variables (e.g., `{{cat_names}}` injected at load time)?
- [ ] Should we support A/B testing (two prompt versions active, traffic split)?
- [ ] Should prompt refresh be push-based (SNS notification on SSM change) or pull-based (TTL)?
- [ ] Should evaluation results embed the full prompt text or just the version number?

---

## Phase 1: Inner Loop — Kiro + Omni Plugin

### What

Developer iterates on agent prompts and tool configurations locally with real-time observability in the IDE.

### How

- Kiro IDE with Amazon Omni plugin provides inline trace visualization
- Run strands/langgraph agent locally against local or remote MCP server
- See each LLM call, tool invocation, retry, token count, and latency inline
- Iterate on system prompt until tool selection and reasoning are correct

### Why it matters

Agent bugs are reasoning bugs — you can't unit-test "the agent chose the wrong tool." You need to watch it think. Omni makes that a 2-second feedback loop instead of deploy-and-grep-logs.

### For this demo

Developer opens Kiro → runs strands agent locally → asks "查看火锅的健康数据" → sees the trace inline showing tool calls to `get_health_metrics` and `get_health_alerts` → tweaks prompt → re-runs.

---

## Phase 2: Offline Evaluation — Dataset + Model Comparison

### What

A fixed evaluation dataset with ground truth, run against multiple models, scored by AgentCore Evaluations API, producing comparison reports that gate deployments.

### Test Case Categories

| Category | Count | What it validates |
|----------|-------|-------------------|
| Greeting | 2+ | Agent doesn't call tools for chitchat |
| Single-tool lookup | 3+ | Correct tool + correct params |
| Multi-tool lookup | 2+ | Agent chains tools in right order |
| Name-to-ID resolution | 2+ | Agent resolves "火锅" → cat_id before querying |
| Write operation | 2+ | Agent confirms before mutating state |

### Scoring Dimensions

| Dimension | What it measures | Source |
|-----------|-----------------|--------|
| Correctness | Does the answer match ground truth? | AgentCore Evaluations |
| Tool Selection | Did it call the right tools with right args? | Trace analysis |
| Efficiency | Token cost, latency, unnecessary tool calls | Instrumentation |

### Model Comparison Output

```
Model               Correctness  Tool Select  Latency(p50)  Cost/req
─────────────────────────────────────────────────────────────────────
claude-sonnet-4-6   92%          95%          2.1s          $0.003
claude-haiku-4-5    78%          85%          0.8s          $0.0004
nova-pro            81%          80%          1.5s          $0.001
```

### CI Gate Rule

PR CI runs eval suite against deployed test agent. If correctness drops >5% vs last main baseline, block merge.

### Tooling

```
evaluations/
├── dataset.json               # Fixed test cases with ground truth
├── run_evaluation.py          # CLI: run dataset against agent(s)
├── agent_client.py            # HTTP/SigV4 agent invocation client
├── evaluator_client.py        # AgentCore Evaluations SDK wrapper
├── report.py                  # Compare models, detect regressions
evaluation-results/            # Timestamped JSON reports (git-ignored)
```

---

## Phase 3: Production Observability — Traces + Metrics

### What

Every production invocation emits structured traces and agent-specific metrics via OTel/ADOT to X-Ray and CloudWatch.

### Already in place

- Application Signals discovery
- X-Ray traces (agent → MCP → API Gateway → Lambda → DynamoDB)
- ADOT sidecar on Fargate tasks
- CloudWatch dashboards (3 persona views)

### Gap: Agent-specific metrics to add

| Metric | Type | Why |
|--------|------|-----|
| `agent.tool_calls_per_request` | Histogram | Detect unnecessary tool call spam |
| `agent.reasoning_steps` | Count | Detect infinite loops or overthinking |
| `agent.token_usage.input` | Sum | Cost monitoring |
| `agent.token_usage.output` | Sum | Cost monitoring |
| `agent.tool_errors` | Count (per tool) | Early warning of downstream failures |

These come from OTel spans the agent already emits. Add a CloudWatch dashboard panel for them.

---

## Phase 4: Production Scoring — Async, Sampled

### What

Score a sample (10-20%) of production responses for quality using AgentCore Evaluations API. Publish scores as CloudWatch custom metrics for anomaly detection.

### Why not score 100%?

LLM-as-judge costs tokens and adds latency. 10-20% sampling is statistically sufficient to detect drift within minutes.

### Architecture

```
Agent invocation completes
        │
        ▼ (async, no user-facing latency impact)
┌───────────────┐     ┌──────────────────┐     ┌─────────────┐
│ Scoring Queue │────▶│ Evaluator Lambda │────▶│ CW Metrics  │
│ (SQS / CW Log)│     │ (samples 10-20%) │     │ (custom)    │
└───────────────┘     └──────────────────┘     └─────────────┘
                              │
                              ▼
                    AgentCore Evaluations API
                    (helpfulness, faithfulness,
                     hallucination)
```

### Key Design Decisions

- **Async:** Zero impact on user-facing latency. User already got their answer. Scoring happens 30-60s later.
- **Sampled:** Cost-effective. Statistical anomaly detection works fine with 10-20% coverage.
- **AgentCore Evaluations API:** Built-in evaluators (helpfulness, faithfulness, hallucination) — no custom judge prompts needed.
- **CloudWatch custom metrics:** `AgentQuality/Helpfulness`, `AgentQuality/Faithfulness`, `AgentQuality/Hallucination` — published per-evaluation, 1-minute resolution.
- **Anomaly detection alarm:** On 1-hour rolling average. Fires when quality drops below 2 standard deviations of learned baseline.

### Open Questions

- [ ] Should we score by category (greeting vs tool-use) or aggregate only?
- [ ] What's the minimum sample size per hour to be statistically meaningful?
- [ ] Should the evaluator Lambda also capture tool-selection accuracy (requires trace correlation)?
- [ ] Where does the "ground truth" come from in production? (No ground truth → helpfulness/faithfulness only, no correctness)

---

## Phase 5: Detection & Analysis — AIOps

### What

When a quality metric drops, automated detection triggers the DevOps Agent to investigate root cause and report to Slack.

### Detection Chain

1. **CloudWatch Anomaly Detection** fires alarm on quality metric
2. **SNS → Slack** (already wired via SlackStack)
3. **DevOps Agent** auto-investigates:
   - Pull recent low-scoring samples from evaluation results
   - Compare against baseline (what changed? new deploy? prompt change? tool failure?)
   - Check if a specific tool is erroring (MCP server down?)
   - Check if a specific category regressed (prompt issue vs data issue)
   - Correlate with recent deployments (git log + CloudFormation events)
4. Agent posts root-cause summary to Slack thread

### Root Cause Taxonomy

| Signal | Likely Cause |
|--------|-------------|
| All categories drop simultaneously | Model API issue or prompt deleted |
| One category drops | Tool broke or data changed |
| Latency spike + quality drop | Timeout causing truncated responses |
| Tool errors spike | MCP server / downstream API failure |
| Gradual drift over days | Training data shift or model update |
| Drop correlates with deploy timestamp | Code change introduced regression |

### Demo Story

> You shipped a bad prompt change. How long until you know? Who tells you? What do they tell you?

- **Without this:** You find out when customers complain (hours/days)
- **With this:** Anomaly detection fires in minutes, DevOps agent tells you exactly which category regressed and correlates with the deploy

---

## Implementation Plan

### Phase A — Prompt Management + Offline Eval Framework (Build now)

- [ ] Create `prompts/` directory with versioned YAML prompt files
- [ ] Implement `prompt_loader.py` (SSM in prod, local file in dev, 5-min TTL cache)
- [ ] Refactor agents to load prompts via loader (remove hardcoded strings)
- [ ] CI step: upload prompt to SSM on deploy (new version auto-created)
- [ ] Evaluation dataset with 10+ test cases across 5 categories
- [ ] Dynamic model switching in strands/langgraph agents
- [ ] Evaluation runner CLI (accepts prompt version as parameter)
- [ ] AgentCore Evaluations scoring integration
- [ ] Model × Prompt comparison report generation
- [ ] CI gate: eval with new prompt, block if regression

### Phase B — Production Scoring Pipeline (Build next)

- [ ] Scoring queue (SQS or CloudWatch Logs)
- [ ] Evaluator Lambda (samples, scores, publishes metrics)
- [ ] Custom CloudWatch metrics namespace
- [ ] Dashboard panel for quality scores
- [ ] Anomaly detection alarm on quality metrics

### Phase C — Demo Story (Build last)

- [ ] Inject bug (e.g., break feeding tool MCP endpoint)
- [ ] Show quality metric drop on dashboard
- [ ] Show alarm → SNS → Slack notification
- [ ] Show DevOps agent investigation + root cause posted to Slack
- [ ] End-to-end narrative for audience

---

## Mapping to Existing Infrastructure

| Lifecycle Phase | Infra Component | Status |
|----------------|-----------------|--------|
| Phase 1 (Inner Loop) | Local agent + Kiro/Omni | Manual setup |
| Phase 2 (Offline Eval) | AgentCore Evaluations API | **To build** |
| Phase 3 (Prod Observability) | Application Signals, X-Ray, ADOT | Deployed |
| Phase 4 (Prod Scoring) | Evaluator Lambda + CW metrics | **To build** |
| Phase 5 (AIOps) | SlackStack + DevOps Agent | Partially deployed |

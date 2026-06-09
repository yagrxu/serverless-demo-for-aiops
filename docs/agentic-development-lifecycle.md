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

### Design: Manifest + Versioned Parameters

Two SSM parameters per agent — a **manifest** (routing) and a **prompt** (content):

```
/aiops-cat-demo/prompts/strands/manifest   → routing config (JSON)
/aiops-cat-demo/prompts/strands/system     → prompt text (versioned by SSM)
```

The manifest controls which prompt versions are active:

```json
{
  "stable": 2,
  "canary": {"version": 3, "weight": 20},
  "previous": 1
}
```

- **`stable`** — production default (serves 100% - canary_weight of traffic)
- **`canary`** — new version under test (serves canary_weight % of traffic)
- **`previous`** — last known-good for instant rollback

The prompt parameter stores content, with SSM providing automatic version history:

```
Version 1: "You are a helpful cat-care assistant..."
Version 2: "You are a helpful cat-care assistant... (improved tool instructions)"
Version 3: "You are a helpful cat-care assistant... (canary experiment)"
```

### How the Agent Loads Prompts

```python
def get_prompt(name: str, session_id: str = "") -> tuple[str, str]:
    """Returns (prompt_text, version_label) based on manifest routing."""
    manifest = _load_manifest(name)  # cached, 5-min TTL

    # Determine which version to serve
    canary = manifest.get("canary")
    if canary and _in_canary_cohort(session_id, canary["weight"]):
        version = canary["version"]
        label = f"v{version}-canary"
    else:
        version = manifest["stable"]
        label = f"v{version}-stable"

    prompt_text = _load_prompt_version(name, version)  # cached per version
    return prompt_text, label


def _in_canary_cohort(session_id: str, weight: int) -> bool:
    """Deterministic: same session always gets same version."""
    return (hash(session_id) % 100) < weight
```

Key properties:
- **Session-pinned**: same user/session always gets the same version (consistent UX)
- **Deterministic**: no randomness — hash-based routing is reproducible
- **Version in spans**: OTel traces tag `llm.prompt_template.version = "v3-canary"` for quality metric slicing

### Storage Tiers

| Environment | Manifest Source | Prompt Source |
|-------------|----------------|---------------|
| Local dev | `prompts.json` file (Omni-compatible) | `prompts.json` versions array |
| Test/Prod | SSM `/prompts/<agent>/manifest` | SSM `/prompts/<agent>/system` (by version number) |

The loader tries SSM first, falls back to local file:

```python
PROMPT_SOURCE = os.environ.get("PROMPT_SOURCE", "local")  # "local" or "ssm"
```

### Operational Workflows

**Deploy new canary (one SSM put):**
```bash
# 1. Create new prompt version
aws ssm put-parameter \
  --name /aiops-cat-demo/prompts/strands/system \
  --value "new prompt text..." --overwrite
# → auto-creates version 4

# 2. Update manifest to route 20% to it
aws ssm put-parameter \
  --name /aiops-cat-demo/prompts/strands/manifest \
  --value '{"stable": 3, "canary": {"version": 4, "weight": 20}, "previous": 2}' \
  --overwrite
```

**Promote canary to stable (one SSM put):**
```bash
aws ssm put-parameter \
  --name /aiops-cat-demo/prompts/strands/manifest \
  --value '{"stable": 4, "canary": null, "previous": 3}' \
  --overwrite
```

**Rollback (one SSM put):**
```bash
aws ssm put-parameter \
  --name /aiops-cat-demo/prompts/strands/manifest \
  --value '{"stable": 3, "canary": null, "previous": 2}' \
  --overwrite
```

**Emergency kill canary (one SSM put):**
```bash
aws ssm put-parameter \
  --name /aiops-cat-demo/prompts/strands/manifest \
  --value '{"stable": 3, "canary": null, "previous": 2}' \
  --overwrite
```

All operations are **single atomic writes** to the manifest. No label gymnastics. Agent picks up changes within 5-min TTL (or immediately on next cold start).

### Canary Quality Monitoring

Because OTel spans carry the version label, production scoring can slice by version:

```
CW Metric: AgentQuality/Correctness {prompt_version="v4-canary"}  → 72%
CW Metric: AgentQuality/Correctness {prompt_version="v3-stable"}  → 88%
```

If canary quality drops below stable by >10%, the DevOps agent can auto-kill the canary:
1. Detect quality divergence between versions
2. Update manifest to remove canary
3. Alert to Slack: "Canary v4 killed — correctness 72% vs stable 88%"

### CI/CD Integration

```
Developer edits prompts/strands/system.yaml in repo
        │
        ▼
┌───────────────────────────────────────────────────┐
│  PR CI Pipeline                                    │
│  1. Lint prompt (non-empty, < 8KB, valid YAML)    │
│  2. Run offline eval with NEW prompt              │
│  3. Compare scores vs baseline (current stable)   │
│  4. Block if correctness regresses > 5%           │
└───────────────────────────────────────────────────┘
        │ (merge)
        ▼
┌───────────────────────────────────────────────────┐
│  Deploy Pipeline                                   │
│  1. Upload prompt to SSM (creates new version)    │
│  2. Update manifest: new version as canary (20%)  │
│  3. Monitor quality metrics for 1 hour            │
│  4. Auto-promote to stable if quality holds       │
│  NO container rebuild needed                      │
└───────────────────────────────────────────────────┘
```

### Prompt + Model Matrix (Evaluation)

The eval runner can pin both prompt version and model:

```bash
python evaluation/runner.py \
  --models us.anthropic.claude-sonnet-4-6 us.anthropic.claude-haiku-4-5 \
  --prompt-version 3 --prompt-version 4
```

Produces a comparison matrix:

```
                    Prompt v3    Prompt v4
claude-sonnet-4-6   92%          94%
claude-haiku-4-5    78%          75%     ← v4 regressed on haiku!
```

This answers: "Does the new prompt work across all models, or only on the one I tested locally?"

### Explicit Version Override (Diagnostic)

Same pattern as `model_id` — request payload accepts `prompt_version`:

```json
{
  "prompt": "查看火锅的健康数据",
  "model_id": "us.anthropic.claude-sonnet-4-6-20250514-v1:0",
  "prompt_version": 2
}
```

Useful for:
- Eval runner testing specific versions
- DevOps agent replaying failed requests with previous prompt
- Developer debugging "did this prompt change cause the regression?"

### Local Development (Omni-compatible)

Locally, `prompts.json` stores versions inline:

```json
{
  "cat_care_assistant": {
    "active": {"stable": 1, "canary": {"version": 2, "weight": 20}},
    "versions": {
      "1": {
        "messages": [{"role": "system", "content": "v1 prompt..."}],
        "created": "2026-06-01T00:00:00Z"
      },
      "2": {
        "messages": [{"role": "system", "content": "v2 prompt..."}],
        "created": "2026-06-09T00:00:00Z"
      }
    },
    "history": [...]
  }
}
```

Omni plugin reads/writes this file directly. Changes are visible to the agent immediately (mtime-based reload).

### Repo Layout

```
prompts/                          # Source of truth for CI → SSM upload
  strands/system.yaml             # Prompt content (latest)
  langgraph/system.yaml
agents/strands/
  prompts.json                    # Local dev (Omni-compatible, versions inline)
  prompt_loader.py                # Two-tier loader (SSM or local)
  server.py                       # Uses prompt_loader
```

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

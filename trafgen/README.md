# trafgen — Traffic Generator for the Cat-Care AIOps Demo

Generates realistic, observable traffic against the cat-care demo's REST
API and agent stack. Produces reproducible load patterns that correlate
with bugs injected on `feature/*` branches, so AIOps investigators can
find generator activity in CloudWatch, Application Signals, and X-Ray.

The generator is **not** a benchmarking tool. Its job is to produce
traffic patterns at modest throughput (1–50 RPS) that are:

- **Reproducible** — seeded RNG, same seed = same scenario sequence
- **Trace-correlatable** — every call carries a W3C `traceparent` header
- **Self-describing** — a JSONL manifest records every dispatched call

## Install

```bash
# Using uv (recommended)
cd trafgen
uv sync

# Or using pip
cd trafgen
pip install -e .
```

## Usage

### `trafgen run` — generate traffic

```bash
# Local stack (API on :8000, agents on :8081/:8082, chatbot on :3000)
trafgen run --target local --profile profiles/baseline.yaml --rps 1 --duration 30s

# With a fixed seed for reproducibility
trafgen run --target local --profile profiles/baseline.yaml --rps 1 --duration 5m --seed 42

# Dry run — picks scenarios/personas without making HTTP calls
trafgen run --target local --profile profiles/baseline.yaml --dry-run --duration 10s

# Cloud stack (uses boto3 credential chain for SigV4)
AWS_PROFILE=cloudops-demo trafgen run --target cloud --profile profiles/baseline.yaml --rps 0.5 --duration 30m
```

### `trafgen validate` — check a profile

```bash
trafgen validate profiles/baseline.yaml
```

### `trafgen list_scenarios` — show scenario summary

```bash
trafgen list_scenarios profiles/baseline.yaml
```

## Profile Format

Profiles are YAML files that declare personas, scenarios, and defaults.
See `profiles/baseline.yaml` for a complete example.

```yaml
name: baseline
description: Steady realistic load — 70% reads, 25% writes, 5% chat
defaults:
  rps: 1.0
  duration: 30m

personas:
  - id: owner_alice
    cats: [hotpot]
    devices: [feeder-hotpot, fountain-1, litter-1]
    locale: zh-CN
  - id: owner_bob
    cats: [bbq]
    devices: [feeder-bbq, fountain-1, litter-1]
    locale: zh-CN

scenarios:
  - id: morning_feeding
    weight: 30
    surface: rest
    allowed_personas: [owner_alice, owner_bob]
    steps:
      - call: get_cat
        with: { cat_id: "${persona.cats[0]}" }
      - call: create_feeding
        with:
          cat_id: "${persona.cats[0]}"
          amount_grams: { sample: { dist: normal, mean: 35, stddev: 5, min: 20, max: 60 } }

  - id: chat_health_inquiry
    weight: 5
    surface: agent
    via: chatbot
    allowed_personas: [owner_alice]
    prompts:
      - "{cat_name}最近吃得怎么样?"
      - "{cat_name}今天有什么健康警报吗?"
```

Key rules:
- `personas[].id` must match `^[a-z][a-z0-9_]*$` and be unique
- `scenarios[].weight` ≥ 0; sum of all weights > 0
- `scenarios[].surface` is `rest` or `agent`
- `scenarios[].allowed_personas` must reference defined persona IDs
- For `surface: agent`, `via` must be `chatbot`, `langgraph_direct`, or `strands_direct`
- Sample directives support `uniform`, `normal`, and `choices` distributions

## Cloud Deployment (Fargate)

The traffic generator runs as a Fargate scheduled task in the test
account, triggered hourly by EventBridge. The CDK stack is gated behind
a context flag:

```bash
npx cdk deploy aiops-cat-demo-trafgen -c trafgenEnabled=true -c imageTag=<sha>
```

The Fargate task:
- Uses 256 CPU / 512 MB memory on ARM64
- Runs for 55 minutes per hour at 0.5 RPS
- Writes manifests to CloudWatch Logs and S3 (7-day lifecycle)
- Uses a task IAM role for credentials (no static keys)

Environment variables injected by the task definition:
- `TRAFGEN_API_URL` — API Gateway URL
- `TRAFGEN_CHATBOT_URL` — Chatbot ALB URL
- `TRAFGEN_LANGGRAPH_ARN` — LangGraph AgentCore Runtime ARN
- `TRAFGEN_STRANDS_ARN` — Strands AgentCore Runtime ARN
- `TRAFGEN_S3_BUCKET` — Manifest bucket name

## Feeding Behavior

The baseline profile simulates realistic cat-feeding patterns:

- **Normal feeding**: ~2–3 feedings per cat per day (morning + evening,
  occasional midday snack). Amount follows a normal distribution
  (mean 35g, stddev 5g, clamped to 20–60g).
- **Anomalous patterns**: ~1 anomalous event per day for AIOps detection.
  These include missed feedings, unusually large portions, or rapid
  consecutive feedings that trigger health alerts.

The generator's modest RPS (0.5 in cloud mode) means roughly 30 calls
per minute — enough to populate CloudWatch metrics and traces without
overwhelming the demo account.

## Run Manifest

Each run produces a JSONL file at `runs/<run_id>.jsonl` (local) or
`s3://<bucket>/<run_id>.jsonl` (cloud). Each line is a `RunEvent`:

```json
{
  "run_id": "4f1a2c...",
  "seq": 1,
  "ts": "2024-01-15T08:00:01Z",
  "scenario": "morning_feeding",
  "step": "create_feeding",
  "persona": "owner_alice",
  "session_id": "owner_alice:a1b2c3",
  "target": "local",
  "surface": "rest",
  "endpoint": "POST /feedings",
  "request_summary": {"cat_id": "hotpot", "amount_grams": 37},
  "status": 201,
  "latency_ms": 42.5,
  "error": null,
  "traceparent": "00-abcdef1234567890abcdef1234567890-1234567890abcdef-01"
}
```

## Correctness Properties

Six properties are verified via Hypothesis property-based tests:

| # | Property | What it checks |
|---|----------|----------------|
| P1 | Determinism under fixed seed | Same seed → same scenario/persona/endpoint sequence |
| P2 | Aggregate RPS bound | Observed rate ≤ 1.2 × configured RPS in any 5s window |
| P3 | Manifest schema invariant | Every row validates against RunEvent; seq is monotonic |
| P4 | Persona/cat consistency | REST calls only reference the dispatching persona's cats |
| P5 | Traceparent format | Every event matches `^00-[0-9a-f]{32}-[0-9a-f]{16}-01$` |
| P6 | Local/cloud parity | Same seed produces same dispatch shape regardless of target |

Run property tests:

```bash
make test-property
```

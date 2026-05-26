# Agent Evaluation Framework

Comparative evaluation tool for LangGraph vs Strands agents. Sends the same prompts to both agents, records responses, then uses an **LLM-as-judge** (Bedrock Claude) to score each response against defined criteria.

## Prerequisites

- Python 3.11+
- Both agents running (locally or in the cloud)
- AWS credentials configured (for the LLM judge via Bedrock)
- Install dependencies:

```bash
cd evaluation
pip install -r requirements.txt
```

### Local setup

Make sure the local stack is running with both agents:

| Service | URL |
|---------|-----|
| LangGraph agent | http://localhost:8081/invocations |
| Strands agent | http://localhost:8082/invocations |

### Cloud setup

Set environment variables to point at deployed agents:

```bash
export LANGGRAPH_URL=https://<your-langgraph-endpoint>/invocations
export STRANDS_URL=https://<your-strands-endpoint>/invocations
```

## Running evaluations

### Step 1: Collect responses

```bash
# Run with default dataset and local URLs
python runner.py --dataset datasets/comparative.yaml

# Specify custom agent URLs
python runner.py \
  --dataset datasets/comparative.yaml \
  --langgraph-url http://localhost:8081/invocations \
  --strands-url http://localhost:8082/invocations

# Specify output file
python runner.py --dataset datasets/comparative.yaml --output results/my-run.json
```

### Step 2: Run LLM-as-judge

```bash
# Judge with default settings (threshold=0.7, haiku model)
python judge.py results/my-run.json

# Custom threshold and model
python judge.py results/my-run.json --threshold 0.8 --model us.anthropic.claude-sonnet-4-20250514-v1:0

# Fail with exit code 1 if below threshold (for CI)
python judge.py results/my-run.json --fail-on-regression
```

### Step 3: View report (optional)

```bash
python report.py results/my-run.json --responses
```

## CI Integration

The evaluation runs automatically on every PR that touches `agents/**`. The GitHub Actions workflow:

1. Starts DynamoDB Local + API shim + MCP Server + both agents
2. Runs the evaluation dataset against both agents
3. Uses LLM-as-judge (Bedrock Claude Haiku) to score responses
4. Fails the PR if average score drops below 0.7

The CI job requires AWS OIDC credentials (same role as deploy) for Bedrock access.

### Running locally (same as CI)

```bash
./evaluation/ci-run.sh --threshold 0.7
```

## LLM-as-judge scoring

The judge evaluates each response against category-specific criteria:

| Category | Criteria |
|----------|----------|
| `efficiency` | Correct answer, minimal tool calls |
| `accuracy` | Contains numbers, comparisons, complete lists |
| `error_recovery` | No hallucination, graceful error handling |
| `ambiguity` | Asks clarifying questions instead of guessing |
| `context` | Maintains context across multi-turn conversations |
| `safety` | Clearly refuses dangerous/injection requests |

Scores are 0.0–1.0 per case. The threshold (default 0.7) applies to the average across all cases.

## Evaluation categories

| Category | What it tests |
|----------|---------------|
| `efficiency` | Tool call count — does the agent use the minimum number of calls? |
| `accuracy` | Response correctness — numbers, comparisons, completeness |
| `error_recovery` | Graceful handling of errors (404, 429, timeouts) |
| `ambiguity` | Asking for clarification instead of guessing |
| `context` | Multi-turn conversation — remembering prior context |
| `safety` | Refusing dangerous/injection prompts |

## Adding new test cases

Edit `datasets/comparative.yaml`. Each case needs:

```yaml
- id: unique_identifier        # Required
  prompt: "用户的问题"          # Required for single-turn
  category: efficiency         # Required
  # Optional metadata for validation:
  optimal_tool_count: 2
  must_contain_numbers: true
  must_refuse: true
  expected_behavior: "描述期望行为"
```

For multi-turn cases:

```yaml
- id: multi_turn_example
  category: context
  turns:
    - prompt: "第一轮问题"
    - prompt: "第二轮问题"
    - prompt: "第三轮问题"
```

## Output format

Results JSON structure:

```json
{
  "timestamp": "2025-01-01T12:00:00+00:00",
  "config": { "dataset": "...", "langgraph_url": "...", "strands_url": "..." },
  "summary": { "total_cases": 13, "langgraph_ok": 12, "strands_ok": 11 },
  "results": [
    {
      "id": "efficient_lookup",
      "category": "efficiency",
      "type": "single_turn",
      "prompt": "火锅今天吃了多少？",
      "langgraph": { "status": "ok", "response": "...", "latency_ms": 2340.5 },
      "strands": { "status": "ok", "response": "...", "latency_ms": 1890.2 }
    }
  ]
}
```

Judge output structure:

```json
{
  "source_results": "results/ci-run.json",
  "summary": {
    "threshold": 0.7,
    "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "total_cases": 14,
    "langgraph": { "avg_score": 0.85, "pass": true, "min_score": 0.6, "cases_below_threshold": 1 },
    "strands": { "avg_score": 0.82, "pass": true, "min_score": 0.5, "cases_below_threshold": 2 },
    "overall_pass": true
  },
  "judgments": [
    { "id": "efficient_lookup", "category": "efficiency", "langgraph": { "score": 0.9, "reasoning": "..." }, "strands": { "score": 0.85, "reasoning": "..." } }
  ]
}
```

## Architecture

```
evaluation/
├── README.md              # This file
├── requirements.txt       # httpx, pydantic, rich, pyyaml, boto3
├── ci-run.sh              # Full local stack + eval + judge (for CI or local)
├── datasets/
│   └── comparative.yaml   # Evaluation test cases with criteria
├── runner.py              # Sends prompts to both agents, records results
├── judge.py               # LLM-as-judge: scores responses via Bedrock
├── report.py              # Reads results JSON, prints comparison tables
└── results/               # Output directory (gitignored)
    ├── <timestamp>.json         # Raw responses
    └── <timestamp>-judged.json  # Judge scores
```

The framework is standalone — no imports from the main project. It only needs HTTP access to the agent endpoints and AWS credentials for the judge.

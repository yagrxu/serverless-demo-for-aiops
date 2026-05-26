# Agent Evaluation Framework

Comparative evaluation tool for LangGraph vs Strands agents. Sends the same prompts to both agents and records responses, latency, and tool usage for side-by-side comparison.

## Prerequisites

- Python 3.11+
- Both agents running (locally or in the cloud)
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

Results are saved to `results/<timestamp>.json` by default.

## Viewing results

```bash
# Full report
python report.py results/20250101-120000.json

# Filter by category
python report.py results/20250101-120000.json --category efficiency

# Include response previews
python report.py results/20250101-120000.json --responses
```

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

## Architecture

```
evaluation/
├── README.md              # This file
├── requirements.txt       # httpx, pydantic, rich, pyyaml
├── datasets/
│   └── comparative.yaml   # Evaluation test cases
├── runner.py              # Sends prompts to both agents, records results
├── report.py              # Reads results JSON, prints comparison tables
└── results/               # Output directory (gitignored)
    └── <timestamp>.json
```

The framework is standalone — no imports from the main project. It only needs HTTP access to the agent endpoints.

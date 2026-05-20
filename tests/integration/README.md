# Integration Tests — Observability Signal Verification

These tests verify that observability signals (CloudWatch metrics, alarms, logs) are emitted correctly when bug scenarios are triggered against a **deployed** stack. They are NOT intended for local development or PR pipelines.

## Prerequisites

- A fully deployed `aiops-cat-demo` stack (all phases through Phase 4+)
- AWS credentials with read access to CloudWatch Metrics, Logs, and Alarms
- Python 3.12+ with `pytest`, `boto3`, and `requests` installed

## Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `API_BASE_URL` | The deployed API Gateway invoke URL (with stage) | `https://abc123.execute-api.us-east-1.amazonaws.com/prod` |
| `AWS_PROFILE` | AWS CLI profile with access to the test account | `cloudops-demo` |

## How to Run

```bash
# Set required env vars
export API_BASE_URL="https://<api-id>.execute-api.us-east-1.amazonaws.com/prod"
export AWS_PROFILE=cloudops-demo

# Run all integration tests
pytest tests/integration/ -m integration --timeout=120

# Run a specific scenario
pytest tests/integration/test_signals.py -m integration --timeout=120 -v
```

## Test Structure

```
tests/integration/
├── conftest.py          # Shared fixtures (API client, CloudWatch helpers)
├── README.md            # This file
├── test_signals.py      # Basic signal emission verification
└── scenario_*.py        # Individual bug scenario tests (added in tasks 12.2–12.12)
```

## Notes

- Tests that poll CloudWatch metrics use a default 60-second timeout. Some scenarios (e.g., anomaly detection) may need longer — use `--timeout=120` or higher.
- Anomaly detector alarms require ~14 days of baseline data before they fire. Newly deployed stacks will not trigger anomaly-based alarms.
- Tests are auto-marked with `@pytest.mark.integration` via `conftest.py` so they can be excluded from PR test runs with `-m "not integration"`.

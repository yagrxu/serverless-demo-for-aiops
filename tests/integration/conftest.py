"""Shared fixtures for observability integration tests.

These tests require a deployed stack and real AWS credentials.
Run with: pytest tests/integration/ -m integration --timeout=120
"""

import os
import time
from datetime import datetime, timedelta, timezone

import boto3
import pytest
import requests

# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: requires a deployed AWS stack")
    config.addinivalue_line("markers", "slow: tests that poll CloudWatch (may take >30s)")


def pytest_collection_modifyitems(items):
    """Auto-mark all tests in this directory with 'integration'."""
    for item in items:
        item.add_marker(pytest.mark.integration)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def api_base_url() -> str:
    """API Gateway base URL from env or a sensible default."""
    url = os.environ.get("API_BASE_URL")
    if not url:
        pytest.skip("API_BASE_URL not set — skipping integration tests")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def cloudwatch_client():
    """Boto3 CloudWatch client for metric queries."""
    return boto3.client("cloudwatch", region_name="us-east-1")


@pytest.fixture(scope="session")
def logs_client():
    """Boto3 CloudWatch Logs client for Logs Insights queries."""
    return boto3.client("logs", region_name="us-east-1")


@pytest.fixture(scope="session")
def http_session() -> requests.Session:
    """Reusable HTTP session for API calls."""
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


# ---------------------------------------------------------------------------
# Helpers (importable by test modules)
# ---------------------------------------------------------------------------

def wait_for_metric(
    cloudwatch_client,
    namespace: str,
    metric_name: str,
    dimensions: list[dict] | None = None,
    stat: str = "Sum",
    timeout_seconds: int = 60,
    poll_interval: int = 10,
) -> float | None:
    """Poll CloudWatch until a metric datapoint appears or timeout expires.

    Returns the metric value if found, None if timed out.
    """
    dimensions = dimensions or []
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=5)

        response = cloudwatch_client.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start_time,
            EndTime=end_time,
            Period=60,
            Statistics=[stat],
        )

        datapoints = response.get("Datapoints", [])
        if datapoints:
            # Return the most recent datapoint value
            latest = max(datapoints, key=lambda dp: dp["Timestamp"])
            return latest[stat]

        time.sleep(poll_interval)

    return None


def query_logs_insights(
    logs_client,
    log_group_names: list[str],
    query_string: str,
    lookback_minutes: int = 15,
    timeout_seconds: int = 60,
) -> list[dict]:
    """Run a CloudWatch Logs Insights query and wait for results.

    Returns a list of result rows (each row is a list of field dicts).
    """
    end_time = int(datetime.now(timezone.utc).timestamp())
    start_time = end_time - (lookback_minutes * 60)

    response = logs_client.start_query(
        logGroupNames=log_group_names,
        startTime=start_time,
        endTime=end_time,
        queryString=query_string,
    )
    query_id = response["queryId"]

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = logs_client.get_query_results(queryId=query_id)
        status = result["status"]

        if status in ("Complete", "Failed", "Cancelled", "Timeout"):
            break

        time.sleep(2)

    if status != "Complete":
        return []

    return result.get("results", [])

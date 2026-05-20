"""Basic signal emission tests.

These verify that the deployed API responds and that CloudWatch metrics
appear after traffic is sent. They serve as a smoke test for the full
observability pipeline.
"""

import sys
from pathlib import Path

import pytest

# Make helpers importable from conftest (pytest auto-loads conftest fixtures
# but not plain functions unless we add the directory to sys.path).
sys.path.insert(0, str(Path(__file__).parent))
from conftest import wait_for_metric  # noqa: E402


class TestApiHealth:
    """Verify the deployed API is reachable."""

    def test_get_cats_returns_200(self, api_base_url, http_session):
        """Hit GET /cats and verify we get a successful JSON response."""
        response = http_session.get(f"{api_base_url}/cats")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body, list)


@pytest.mark.slow
class TestMetricEmission:
    """Verify that CloudWatch metrics appear after API traffic."""

    def test_cat_profiles_read_metric_emitted(
        self, api_base_url, http_session, cloudwatch_client
    ):
        """Call GET /cats and check that CatProfilesRead metric appears within 60s.

        This test may be slow as it polls CloudWatch for metric data.
        Mark with @pytest.mark.slow so it can be skipped in quick runs.
        """
        # Drive one request to ensure a metric is emitted
        response = http_session.get(f"{api_base_url}/cats")
        assert response.status_code == 200

        # Poll CloudWatch for the metric
        value = wait_for_metric(
            cloudwatch_client,
            namespace="CatDemo",
            metric_name="CatProfilesRead",
            dimensions=[{"Name": "service", "Value": "cat-profile"}],
            stat="Sum",
            timeout_seconds=60,
            poll_interval=10,
        )

        assert value is not None, (
            "CatProfilesRead metric did not appear in CloudWatch within 60s. "
            "Verify that the cat-profile Lambda has Powertools Metrics configured."
        )
        assert value >= 1

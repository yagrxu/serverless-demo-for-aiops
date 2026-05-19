"""Configuration constants and AWS region/credential resolution for the voice agent."""

from __future__ import annotations

import os
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Bedrock model identifier for Amazon Nova Sonic (Nova 2 Sonic v1).
MODEL_ID = "amazon.nova-2-sonic-v1:0"

# Audio format constants.
INPUT_SAMPLE_RATE_HZ = 16_000
OUTPUT_SAMPLE_RATE_HZ = 24_000
INPUT_FRAME_SAMPLES = 320  # 20 ms at 16 kHz

# Timing deadlines (seconds).
TOOL_DISPATCH_DEADLINE_S = 0.5
TOOL_RESULT_DEADLINE_S = 0.5
TOOL_TIMEOUT_S = 10.0
SESSION_OPEN_TIMEOUT_S = 10.0
SHUTDOWN_DEADLINE_S = 5.0

# AWS regions that currently support Nova Sonic v2 on Bedrock.
SUPPORTED_REGIONS = {"us-east-1", "us-east-2", "us-west-2", "ap-northeast-1"}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class MissingCredentialsError(Exception):
    """Raised when AWS credentials cannot be resolved from the SDK chain."""


class UnsupportedRegionError(Exception):
    """Raised when the resolved AWS region does not support Nova Sonic v2."""


class BedrockOpenError(Exception):
    """Raised when the Bedrock bidirectional stream cannot be opened."""

    def __init__(self, category: str, underlying: object) -> None:
        self.category = category
        self.underlying = underlying
        super().__init__(f"{category}: {underlying}")


# ---------------------------------------------------------------------------
# Region and credential resolution
# ---------------------------------------------------------------------------


def resolve_region() -> Optional[str]:
    """Return the AWS region to use, or None if not set.

    Precedence: AWS_REGION > AWS_DEFAULT_REGION > boto3 session.
    Defaults to us-east-1 for Nova Sonic.
    """
    env_region = os.environ.get("AWS_REGION")
    if env_region:
        return env_region

    default_region = os.environ.get("AWS_DEFAULT_REGION")
    if default_region:
        return default_region

    import boto3

    session_region = boto3.Session().region_name
    if session_region:
        return session_region

    return "us-east-1"


def validate_region(region: Optional[str]) -> None:
    """Raise UnsupportedRegionError if region is not supported."""
    if region is None or region not in SUPPORTED_REGIONS:
        display = region if region else "(none)"
        raise UnsupportedRegionError(
            f"Region {display} does not support Nova Sonic v2"
        )


def assert_credentials_resolvable() -> None:
    """Verify that AWS credentials can be resolved from the SDK chain."""
    import boto3

    try:
        credentials = boto3.Session().get_credentials()
    except Exception as exc:
        raise MissingCredentialsError(
            f"AWS credentials could not be resolved: {exc}"
        ) from exc

    if credentials is None:
        raise MissingCredentialsError(
            "AWS credentials could not be resolved from the SDK chain"
        )

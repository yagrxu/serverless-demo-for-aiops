"""Target endpoint resolution for trafgen."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


class EndpointResolutionError(Exception):
    """Raised when a required endpoint cannot be resolved."""


@dataclass(frozen=True)
class TargetEndpoints:
    """Resolved endpoints for a target environment."""
    api_base_url: str
    chatbot_url: str
    langgraph_url: str
    strands_url: str
    auth: Literal["none", "sigv4"]


def resolve_endpoints(target: Literal["local", "cloud"]) -> TargetEndpoints:
    """Resolve endpoints for the given target.

    Args:
        target: "local" for localhost dev stack, "cloud" for deployed AWS.

    Returns:
        TargetEndpoints with all URLs resolved.

    Raises:
        EndpointResolutionError: If a required endpoint cannot be resolved.
        ValueError: If target is not "local" or "cloud".
    """
    if target == "local":
        return _resolve_local()
    elif target == "cloud":
        return _resolve_cloud()
    else:
        raise ValueError(f"Unknown target: {target!r}. Must be 'local' or 'cloud'.")


def _resolve_local() -> TargetEndpoints:
    """Resolve local dev stack endpoints (with env var overrides)."""
    return TargetEndpoints(
        api_base_url=os.environ.get("TRAFGEN_API_URL", "http://localhost:8000"),
        chatbot_url=os.environ.get("TRAFGEN_CHATBOT_URL", "http://localhost:3000"),
        langgraph_url=os.environ.get("TRAFGEN_LANGGRAPH_URL", "http://localhost:8081"),
        strands_url=os.environ.get("TRAFGEN_STRANDS_URL", "http://localhost:8082"),
        auth="none",
    )


def _resolve_cloud() -> TargetEndpoints:
    """Resolve cloud endpoints from env vars or CloudFormation outputs.

    Resolution order: explicit env vars → CloudFormation outputs → error.
    Implemented in task 10.2.
    """
    api_url = os.environ.get("TRAFGEN_API_URL")
    chatbot_url = os.environ.get("TRAFGEN_CHATBOT_URL")
    langgraph_url = os.environ.get("TRAFGEN_LANGGRAPH_ARN")
    strands_url = os.environ.get("TRAFGEN_STRANDS_ARN")

    # Try CloudFormation outputs if env vars are not set
    if not all([api_url, chatbot_url, langgraph_url, strands_url]):
        try:
            cfn_endpoints = _resolve_from_cloudformation()
            api_url = api_url or cfn_endpoints.get("api_url")
            chatbot_url = chatbot_url or cfn_endpoints.get("chatbot_url")
            langgraph_url = langgraph_url or cfn_endpoints.get("langgraph_url")
            strands_url = strands_url or cfn_endpoints.get("strands_url")
        except Exception:
            pass

    # Validate all required endpoints are resolved
    missing = []
    if not api_url:
        missing.append("TRAFGEN_API_URL")
    if not chatbot_url:
        missing.append("TRAFGEN_CHATBOT_URL")
    if not langgraph_url:
        missing.append("TRAFGEN_LANGGRAPH_ARN")
    if not strands_url:
        missing.append("TRAFGEN_STRANDS_ARN")

    if missing:
        raise EndpointResolutionError(
            f"Cannot resolve cloud endpoints. Missing: {', '.join(missing)}. "
            "Set them as env vars or ensure the aiops-cat-demo-* stacks are deployed."
        )

    return TargetEndpoints(
        api_base_url=api_url,  # type: ignore[arg-type]
        chatbot_url=chatbot_url,  # type: ignore[arg-type]
        langgraph_url=langgraph_url,  # type: ignore[arg-type]
        strands_url=strands_url,  # type: ignore[arg-type]
        auth="sigv4",
    )


def _resolve_from_cloudformation() -> dict[str, str]:
    """Query CloudFormation stack outputs for endpoint URLs."""
    import boto3

    cfn = boto3.client("cloudformation", region_name="us-east-1")
    endpoints: dict[str, str] = {}

    # Map stack names to output keys
    stack_outputs = {
        "aiops-cat-demo-api": {"ApiUrl": "api_url"},
        "aiops-cat-demo-fargate": {"ChatbotUrl": "chatbot_url"},
        "aiops-cat-demo-agents": {
            "LangGraphRuntimeArn": "langgraph_url",
            "StrandsRuntimeArn": "strands_url",
        },
    }

    for stack_name, output_map in stack_outputs.items():
        try:
            response = cfn.describe_stacks(StackName=stack_name)
            outputs = response["Stacks"][0].get("Outputs", [])
            for output in outputs:
                key = output["OutputKey"]
                if key in output_map:
                    endpoints[output_map[key]] = output["OutputValue"]
        except Exception:
            continue

    return endpoints

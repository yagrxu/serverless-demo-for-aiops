"""Agent client for the chatbot BFF, LangGraph, and Strands surfaces.

Dispatches chat prompts via the chatbot BFF, or directly to LangGraph/Strands
AgentCore Runtimes. Direct runtime calls use the AWS AgentCore API endpoint
with SigV4 signing, matching the chatbot BFF's invocation pattern.

OTel context propagation is handled automatically by the
opentelemetry-instrument httpx auto-instrumentation — no manual traceparent
injection needed.
"""
from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import quote

import boto3
import httpx

from . import CallContext, Response
from .sigv4 import sign


def _arn_to_invoke_url(arn: str, region: str) -> str:
    """Convert an AgentCore Runtime ARN to the InvokeAgentRuntime API URL.

    ARN format: arn:aws:bedrock-agentcore:{region}:{account}:runtime/{id}
    API URL:    https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations
    """
    encoded = quote(arn, safe="")
    return f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded}/invocations"


class AgentClient:
    """Client for agent surfaces: chatbot BFF, LangGraph, Strands."""

    def __init__(
        self,
        chatbot_url: str | None = None,
        langgraph_url: str | None = None,
        strands_url: str | None = None,
    ) -> None:
        self._chatbot_url = chatbot_url.rstrip("/") if chatbot_url else None
        # langgraph_url / strands_url are actually ARNs in cloud mode
        self._langgraph_arn = langgraph_url if langgraph_url else None
        self._strands_arn = strands_url if strands_url else None
        self._http = httpx.AsyncClient(timeout=90.0)
        self._region = os.environ.get("AWS_REGION", "us-east-1")

    def _is_arn(self, value: str | None) -> bool:
        """Check if the value is an ARN (cloud mode) vs a URL (local mode)."""
        return value is not None and value.startswith("arn:")

    async def _post(
        self,
        url: str,
        ctx: CallContext,
        body: dict[str, Any],
        endpoint: str,
    ) -> Response:
        """Execute a POST request with 90s timeout (no SigV4).

        NOTE: No manual traceparent header is set here. The OTel httpx
        auto-instrumentation (via opentelemetry-instrument) injects the
        correct traceparent from the active span context automatically.
        """
        headers = {"Content-Type": "application/json"}
        t0 = time.perf_counter()
        try:
            resp = await self._http.post(url, headers=headers, json=body)
            latency_ms = (time.perf_counter() - t0) * 1000
            try:
                json_body = resp.json()
            except Exception:
                json_body = None
            return Response(
                status=resp.status_code,
                latency_ms=latency_ms,
                json=json_body,
                error=None,
                endpoint=endpoint,
                method="POST",
            )
        except httpx.ReadTimeout:
            latency_ms = (time.perf_counter() - t0) * 1000
            return Response(
                status=None,
                latency_ms=latency_ms,
                json=None,
                error="agent_timeout",
                endpoint=endpoint,
                method="POST",
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            latency_ms = (time.perf_counter() - t0) * 1000
            return Response(
                status=None,
                latency_ms=latency_ms,
                json=None,
                error="connection_refused",
                endpoint=endpoint,
                method="POST",
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            return Response(
                status=None,
                latency_ms=latency_ms,
                json=None,
                error=str(e),
                endpoint=endpoint,
                method="POST",
            )

    async def _invoke_runtime(
        self,
        arn: str,
        ctx: CallContext,
        body: dict[str, Any],
        endpoint: str,
    ) -> Response:
        """Invoke an AgentCore Runtime via the AWS API with SigV4 signing.

        Constructs the proper API URL from the ARN and signs the request,
        matching the chatbot BFF's invocation pattern. This ensures the
        AgentCore platform creates its segment and propagates trace context.
        """
        import json as json_mod
        import logging

        logger = logging.getLogger(__name__)

        url = _arn_to_invoke_url(arn, self._region)
        payload = json_mod.dumps(body).encode()

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": ctx.session_id,
        }

        t0 = time.perf_counter()
        try:
            # Build the request manually so we can sign it
            request = self._http.build_request("POST", url, headers=headers, content=payload)

            # Sign with SigV4
            session = boto3.Session()
            creds = session.get_credentials().get_frozen_credentials()
            sign(request, service="bedrock-agentcore", region=self._region, credentials=creds)

            # Send the signed request
            resp = await self._http.send(request)
            latency_ms = (time.perf_counter() - t0) * 1000

            if resp.status_code >= 400:
                err_body = resp.text
                logger.error(
                    "AgentCore invoke failed: status=%d body=%s url=%s",
                    resp.status_code, err_body[:500], url,
                )

            try:
                json_body = resp.json()
            except Exception:
                json_body = None
            return Response(
                status=resp.status_code,
                latency_ms=latency_ms,
                json=json_body,
                error=f"http_{resp.status_code}" if resp.status_code >= 400 else None,
                endpoint=endpoint,
                method="POST",
            )
        except httpx.ReadTimeout:
            latency_ms = (time.perf_counter() - t0) * 1000
            return Response(
                status=None,
                latency_ms=latency_ms,
                json=None,
                error="agent_timeout",
                endpoint=endpoint,
                method="POST",
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            latency_ms = (time.perf_counter() - t0) * 1000
            return Response(
                status=None,
                latency_ms=latency_ms,
                json=None,
                error="connection_refused",
                endpoint=endpoint,
                method="POST",
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            return Response(
                status=None,
                latency_ms=latency_ms,
                json=None,
                error=str(e),
                endpoint=endpoint,
                method="POST",
            )

    async def chat_via_bff(self, ctx: CallContext, prompt: str) -> Response:
        """POST to chatbot BFF /api/chat."""
        if not self._chatbot_url:
            return Response(error="chatbot_url not configured", endpoint="chatbot:/api/chat", method="POST")
        url = f"{self._chatbot_url}/api/chat"
        body = {"message": prompt, "sessionId": ctx.session_id}
        return await self._post(url, ctx, body, endpoint="chatbot:/api/chat")

    async def invoke_langgraph(self, ctx: CallContext, prompt: str) -> Response:
        """Invoke LangGraph agent — via AgentCore API (cloud) or direct HTTP (local)."""
        if not self._langgraph_arn:
            return Response(error="langgraph_url not configured", endpoint="langgraph:/invocations", method="POST")

        body = {"input": {"message": prompt}}

        if self._is_arn(self._langgraph_arn):
            # Cloud: call via AgentCore API with SigV4
            return await self._invoke_runtime(
                self._langgraph_arn, ctx, body, endpoint="agentcore:langgraph/invocations"
            )
        else:
            # Local: direct HTTP to the container
            url = f"{self._langgraph_arn}/invocations"
            return await self._post(url, ctx, body, endpoint="langgraph:/invocations")

    async def invoke_strands(self, ctx: CallContext, prompt: str) -> Response:
        """Invoke Strands agent — via AgentCore API (cloud) or direct HTTP (local)."""
        if not self._strands_arn:
            return Response(error="strands_url not configured", endpoint="strands:/invocations", method="POST")

        body = {"input": {"message": prompt}}

        if self._is_arn(self._strands_arn):
            # Cloud: call via AgentCore API with SigV4
            return await self._invoke_runtime(
                self._strands_arn, ctx, body, endpoint="agentcore:strands/invocations"
            )
        else:
            # Local: direct HTTP to the container
            url = f"{self._strands_arn}/invocations"
            return await self._post(url, ctx, body, endpoint="strands:/invocations")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

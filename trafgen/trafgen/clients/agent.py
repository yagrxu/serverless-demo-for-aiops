"""Agent client for the chatbot BFF, LangGraph, and Strands surfaces.

Dispatches chat prompts via the chatbot BFF, or directly to LangGraph/Strands
runtimes, with traceparent injection and optional SigV4 signing.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from . import CallContext, Response


class AgentClient:
    """Client for agent surfaces: chatbot BFF, LangGraph, Strands."""

    def __init__(
        self,
        chatbot_url: str | None = None,
        langgraph_url: str | None = None,
        strands_url: str | None = None,
    ) -> None:
        self._chatbot_url = chatbot_url.rstrip("/") if chatbot_url else None
        self._langgraph_url = langgraph_url.rstrip("/") if langgraph_url else None
        self._strands_url = strands_url.rstrip("/") if strands_url else None
        self._http = httpx.AsyncClient(timeout=90.0)

    def _headers(self, ctx: CallContext) -> dict[str, str]:
        """Build headers with traceparent injection."""
        return {"traceparent": ctx.traceparent, "Content-Type": "application/json"}

    async def _post(
        self,
        url: str,
        ctx: CallContext,
        body: dict[str, Any],
        endpoint: str,
    ) -> Response:
        """Execute a POST request with 90s timeout."""
        headers = self._headers(ctx)
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

    async def chat_via_bff(self, ctx: CallContext, prompt: str) -> Response:
        """POST to chatbot BFF /api/chat."""
        if not self._chatbot_url:
            return Response(error="chatbot_url not configured", endpoint="chatbot:/api/chat", method="POST")
        url = f"{self._chatbot_url}/api/chat"
        body = {"message": prompt, "sessionId": ctx.session_id}
        return await self._post(url, ctx, body, endpoint="chatbot:/api/chat")

    async def invoke_langgraph(self, ctx: CallContext, prompt: str) -> Response:
        """POST to LangGraph /invocations."""
        if not self._langgraph_url:
            return Response(error="langgraph_url not configured", endpoint="langgraph:/invocations", method="POST")
        url = f"{self._langgraph_url}/invocations"
        body = {"message": prompt, "sessionId": ctx.session_id}
        return await self._post(url, ctx, body, endpoint="langgraph:/invocations")

    async def invoke_strands(self, ctx: CallContext, prompt: str) -> Response:
        """POST to Strands /invocations."""
        if not self._strands_url:
            return Response(error="strands_url not configured", endpoint="strands:/invocations", method="POST")
        url = f"{self._strands_url}/invocations"
        body = {"message": prompt, "sessionId": ctx.session_id}
        return await self._post(url, ctx, body, endpoint="strands:/invocations")

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

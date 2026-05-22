"""REST client for the cat-care API surface.

Issues HTTP calls (get_cat, list_cats, create_cat, list_feedings, create_feeding,
get_health, get_alerts, post_telemetry, post_command) with traceparent injection
and optional SigV4 signing.
"""
from __future__ import annotations

import time
from typing import Any, Literal

import httpx

from . import CallContext, Response


class RestClient:
    """HTTP client for the cat-care REST API."""

    def __init__(
        self,
        base_url: str,
        auth: Literal["none", "sigv4"] = "none",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth = auth
        self._http = httpx.AsyncClient(timeout=30.0)

    def _headers(self, ctx: CallContext) -> dict[str, str]:
        """Build headers with traceparent injection."""
        return {"traceparent": ctx.traceparent}

    async def _request(
        self,
        method: str,
        path: str,
        ctx: CallContext,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Response:
        """Execute an HTTP request and return a normalized Response."""
        url = f"{self._base_url}{path}"
        headers = self._headers(ctx)
        endpoint = f"{method.upper()} {path}"

        t0 = time.perf_counter()
        try:
            resp = await self._http.request(
                method=method,
                url=url,
                headers=headers,
                json=json,
                params=params,
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            try:
                body = resp.json()
            except Exception:
                body = None
            return Response(
                status=resp.status_code,
                latency_ms=latency_ms,
                json=body,
                error=None,
                endpoint=endpoint,
                method=method.upper(),
            )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            latency_ms = (time.perf_counter() - t0) * 1000
            return Response(
                status=None,
                latency_ms=latency_ms,
                json=None,
                error="connection_refused",
                endpoint=endpoint,
                method=method.upper(),
            )
        except httpx.TimeoutException:
            latency_ms = (time.perf_counter() - t0) * 1000
            return Response(
                status=None,
                latency_ms=latency_ms,
                json=None,
                error="timeout",
                endpoint=endpoint,
                method=method.upper(),
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            return Response(
                status=None,
                latency_ms=latency_ms,
                json=None,
                error=str(e),
                endpoint=endpoint,
                method=method.upper(),
            )

    async def list_cats(self, ctx: CallContext, **kwargs: Any) -> Response:
        """GET /cats"""
        return await self._request("GET", "/cats", ctx)

    async def get_cat(self, ctx: CallContext, cat_id: str, **kwargs: Any) -> Response:
        """GET /cats/{cat_id}"""
        return await self._request("GET", f"/cats/{cat_id}", ctx)

    async def create_cat(self, ctx: CallContext, body: dict[str, Any], **kwargs: Any) -> Response:
        """POST /cats"""
        return await self._request("POST", "/cats", ctx, json=body)

    async def list_feedings(self, ctx: CallContext, cat_id: str, **kwargs: Any) -> Response:
        """GET /cats/{cat_id}/feedings"""
        return await self._request("GET", f"/cats/{cat_id}/feedings", ctx)

    async def create_feeding(self, ctx: CallContext, body: dict[str, Any], **kwargs: Any) -> Response:
        """POST /feedings"""
        return await self._request("POST", "/feedings", ctx, json=body)

    async def get_health(self, ctx: CallContext, cat_id: str, **kwargs: Any) -> Response:
        """GET /cats/{cat_id}/health"""
        return await self._request("GET", f"/cats/{cat_id}/health", ctx)

    async def get_alerts(self, ctx: CallContext, cat_id: str, **kwargs: Any) -> Response:
        """GET /cats/{cat_id}/alerts"""
        return await self._request("GET", f"/cats/{cat_id}/alerts", ctx)

    async def post_telemetry(
        self, ctx: CallContext, device_id: str, body: dict[str, Any], **kwargs: Any
    ) -> Response:
        """POST /devices/{device_id}/telemetry"""
        return await self._request("POST", f"/devices/{device_id}/telemetry", ctx, json=body)

    async def post_command(
        self, ctx: CallContext, device_id: str, body: dict[str, Any], **kwargs: Any
    ) -> Response:
        """POST /devices/{device_id}/commands"""
        return await self._request("POST", f"/devices/{device_id}/commands", ctx, json=body)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

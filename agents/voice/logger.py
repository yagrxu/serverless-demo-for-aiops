"""WebLogger — routes tool activity to a WebSocket instead of stdout."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from logging_utils import ConsoleLogger


_NON_SERIALIZABLE = "<non-serializable>"


def _safe_payload(value: Any) -> Any:
    """Return value if JSON-serializable, else the sentinel string."""
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except (TypeError, ValueError, RecursionError):
        return _NON_SERIALIZABLE


class WebLogger(ConsoleLogger):
    """Logger that emits tool events as dicts via an async send function."""

    def __init__(self, send_fn: Callable[[dict], Awaitable[None]]) -> None:
        super().__init__()
        self._send_fn = send_fn

    @staticmethod
    def _write(line: str) -> None:
        """No-op: suppress all stdout output."""

    def tool_call(self, name: str, arguments: Any) -> None:
        if not self._session_active:
            return
        payload = _safe_payload(arguments)
        import asyncio

        asyncio.ensure_future(
            self._send_fn({"type": "tool_call", "name": name, "arguments": payload})
        )

    def tool_result(self, name: str, result: Any) -> None:
        if not self._session_active:
            return
        payload = _safe_payload(result)
        import asyncio

        asyncio.ensure_future(
            self._send_fn({"type": "tool_result", "name": name, "result": payload})
        )

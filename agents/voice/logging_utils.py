"""Console logger with prefix grammar and session gating.

Renamed from logging.py to avoid conflict with Python's stdlib logging module.
"""

from __future__ import annotations

import json
import sys
from typing import Any


_NON_SERIALIZABLE = "<non-serializable>"


def _serialize_payload(value: Any) -> str:
    """Return value as single-line JSON or <non-serializable>."""
    try:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError, RecursionError):
        return _NON_SERIALIZABLE


class ConsoleLogger:
    """Stdout writer that enforces the demo's prefix grammar."""

    def __init__(self) -> None:
        self._session_active = False

    def mark_session_active(self) -> None:
        self._session_active = True

    def mark_session_closed(self) -> None:
        self._session_active = False

    @property
    def is_session_active(self) -> bool:
        return self._session_active

    def banner(self, model_id: str, region: str) -> None:
        self._write(f"Nova Sonic Demo: model={model_id} region={region}\n")

    def listening(self) -> None:
        self._write("LISTENING: ready for speech\n")

    def user(self, text: str) -> None:
        if not self._session_active:
            return
        self._write(f"USER: {text}\n")

    def assistant(self, text: str) -> None:
        if not self._session_active:
            return
        self._write(f"ASSISTANT: {text}\n")

    def tool_call(self, name: str, arguments: Any) -> None:
        if not self._session_active:
            return
        payload = _serialize_payload(arguments)
        self._write(f"TOOL_CALL: {name} {payload}\n")

    def tool_result(self, name: str, result: Any) -> None:
        if not self._session_active:
            return
        payload = _serialize_payload(result)
        self._write(f"TOOL_RESULT: {name} {payload}\n")

    @staticmethod
    def _write(line: str) -> None:
        stream = sys.stdout
        stream.write(line)
        try:
            stream.flush()
        except Exception:
            pass

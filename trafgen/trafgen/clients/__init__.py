"""Client types shared across REST and Agent clients."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallContext:
    """Context passed to every client call."""
    run_id: str
    scenario_id: str
    persona_id: str
    session_id: str
    traceparent: str


@dataclass
class Response:
    """Normalized response from any client call."""
    status: int | None = None
    latency_ms: float = 0.0
    json: Any = None
    error: str | None = None
    endpoint: str = ""
    method: str = ""
    headers: dict[str, str] = field(default_factory=dict)

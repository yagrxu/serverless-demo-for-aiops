"""Observability models and run manifest for trafgen."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime
from typing import Literal, TextIO

from pydantic import BaseModel


logger = logging.getLogger(__name__)


class RunEvent(BaseModel):
    """One event in the run manifest (JSONL)."""
    seq: int
    ts: datetime
    run_id: str
    scenario_id: str
    persona_id: str
    surface: Literal["rest", "agent"]
    endpoint: str
    method: str | None = None  # HTTP method for REST
    status: int | None = None  # HTTP status code
    latency_ms: float
    error: str | None = None
    traceparent: str
    session_id: str | None = None
    cat_id: str | None = None
    saturation_drop: bool = False


class ScenarioStats(BaseModel):
    """Per-scenario statistics in the run summary."""
    scenario_id: str
    count: int = 0
    errors: int = 0
    p50_ms: float = 0.0
    p95_ms: float = 0.0


class RunSummary(BaseModel):
    """Summary of a completed run."""
    run_id: str
    total_events: int = 0
    total_errors: int = 0
    saturation_drops: int = 0
    error_rate: float = 0.0
    scenarios: list[ScenarioStats] = []


def generate_traceparent() -> str:
    """Generate a W3C traceparent header value."""
    trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    return f"00-{trace_id}-{span_id}-01"


class RunManifest:
    """JSONL writer for run events with summary computation.

    Writes one JSON line per event to the provided TextIO sink,
    tracks events for summary computation.
    """

    def __init__(self, run_id: str, sink: TextIO) -> None:
        self._run_id = run_id
        self._sink = sink
        self._seq = 0
        self._events: list[RunEvent] = []
        self._closed = False

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def seq(self) -> int:
        """Current sequence number (next event will get this value)."""
        return self._seq

    def write_event(self, ev: RunEvent) -> None:
        """Validate, assign monotonic seq, write JSON line, flush."""
        if self._closed:
            raise RuntimeError("Manifest is closed")

        # Validate the event
        ev.model_validate(ev.model_dump())

        # Enforce monotonic seq
        if ev.seq != self._seq:
            raise ValueError(
                f"Expected seq={self._seq}, got seq={ev.seq}. "
                "Sequence numbers must be monotonically increasing."
            )
        self._seq += 1

        # Write JSON line
        line = ev.model_dump_json() + "\n"
        self._sink.write(line)
        self._sink.flush()

        # Track for summary
        self._events.append(ev)

    def summary(self) -> RunSummary:
        """Compute and return a RunSummary from all written events."""
        if not self._events:
            return RunSummary(run_id=self._run_id)

        total_events = len(self._events)
        total_errors = sum(1 for e in self._events if e.error is not None)
        saturation_drops = sum(1 for e in self._events if e.saturation_drop)
        error_rate = total_errors / total_events if total_events > 0 else 0.0

        # Per-scenario stats
        scenario_latencies: dict[str, list[float]] = {}
        scenario_errors: dict[str, int] = {}
        scenario_counts: dict[str, int] = {}

        for ev in self._events:
            sid = ev.scenario_id
            scenario_counts[sid] = scenario_counts.get(sid, 0) + 1
            if ev.error is not None:
                scenario_errors[sid] = scenario_errors.get(sid, 0) + 1
            if sid not in scenario_latencies:
                scenario_latencies[sid] = []
            scenario_latencies[sid].append(ev.latency_ms)

        scenarios: list[ScenarioStats] = []
        for sid in scenario_counts:
            lats = sorted(scenario_latencies[sid])
            p50 = _percentile(lats, 50) if lats else 0.0
            p95 = _percentile(lats, 95) if lats else 0.0
            scenarios.append(ScenarioStats(
                scenario_id=sid,
                count=scenario_counts[sid],
                errors=scenario_errors.get(sid, 0),
                p50_ms=p50,
                p95_ms=p95,
            ))

        return RunSummary(
            run_id=self._run_id,
            total_events=total_events,
            total_errors=total_errors,
            saturation_drops=saturation_drops,
            error_rate=error_rate,
            scenarios=scenarios,
        )

    def close(self) -> None:
        """Finalize the manifest."""
        self._closed = True

    def upload_to_s3(self, bucket: str, key: str) -> None:
        """Upload the manifest to S3.

        Reads the sink content and uploads via boto3.
        On failure, logs a warning and returns without raising.
        """
        try:
            import boto3

            # Try to get the file path from the sink
            if hasattr(self._sink, "name") and self._sink.name != "<stdout>":
                file_path = self._sink.name
                with open(file_path, "rb") as f:
                    data = f.read()
            else:
                # Reconstruct from events
                lines = [ev.model_dump_json() + "\n" for ev in self._events]
                data = "".join(lines).encode("utf-8")

            s3 = boto3.client("s3")
            s3.put_object(Bucket=bucket, Key=key, Body=data)
            logger.info(f"Uploaded manifest to s3://{bucket}/{key}")
        except Exception as e:
            logger.warning(f"Failed to upload manifest to s3://{bucket}/{key}: {e}")


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute a percentile from a sorted list of values."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (pct / 100.0) * (len(sorted_values) - 1)
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return sorted_values[-1]
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])

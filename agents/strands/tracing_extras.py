"""Local-friendly OTel extras for the Strands agent.

Adds a CodeMetadataSpanProcessor that tags every span with the Python
source file, line number, and function name that started it. Useful for
local debugging where you want to click a span in the console and find
the exact line that produced it.

Three startup modes are supported:

1. Cloud (AgentCore Runtime) — the runtime injects the full OTel env
   and the container CMD wraps the process with `opentelemetry-instrument`.
   A real SDK TracerProvider is set up before user code imports. We
   detect it (has `add_span_processor`) and just attach our processor.
   Strands discovers the tracer provider via `trace.get_tracer` and
   emits spans automatically because it was installed with [otel].

2. Local with `opentelemetry-instrument` — same as cloud.

3. Local without any wrapper (plain `uvicorn server:app`) — no SDK
   provider exists yet. We restore the old tracing.py setup:
   - Use Strands' own `StrandsTelemetry` helper to set up the provider +
     OTLP HTTP exporter (Omni's local collector is picked up via
     OTEL_EXPORTER_OTLP_ENDPOINT it injects).
   - Attach the CodeMetadataSpanProcessor.

The `add_span_processor` probe prevents the double-provider registration
that broke the previous setup: we only construct a provider in Mode 3,
where none exists.
"""

import inspect

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor


class CodeMetadataSpanProcessor(SpanProcessor):
    """Attaches code.filepath / code.lineno / code.function to every span."""

    _SKIP_PATTERNS = ("opentelemetry", "instrumentation", "tracing_extras")

    def on_start(self, span: ReadableSpan, parent_context: Context | None = None) -> None:
        frame = inspect.currentframe()
        try:
            for _ in range(100):
                frame = frame.f_back if frame else None
                if not frame:
                    break
                filename = frame.f_code.co_filename
                if any(pat in filename for pat in self._SKIP_PATTERNS):
                    continue
                span.set_attribute("code.filepath", filename)
                span.set_attribute("code.lineno", frame.f_lineno)
                span.set_attribute("code.function", frame.f_code.co_name)
                break
        finally:
            del frame

    def on_end(self, span: ReadableSpan) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


_provider = trace.get_tracer_provider()

if hasattr(_provider, "add_span_processor"):
    # Mode 1 or 2: opentelemetry-instrument has already set up the
    # provider. Strands (installed with [otel]) will discover it. Attach
    # only our metadata processor.
    _provider.add_span_processor(CodeMetadataSpanProcessor())
else:
    # Mode 3: plain `uvicorn server:app` with no wrapper. Use Strands'
    # built-in telemetry helper to set up the provider + exporter so
    # local Omni trace collection keeps working (mirrors old tracing.py).
    try:
        from strands.telemetry.config import StrandsTelemetry

        telemetry = StrandsTelemetry()
        telemetry.setup_otlp_exporter()
        telemetry.tracer_provider.add_span_processor(CodeMetadataSpanProcessor())
    except ImportError:
        # strands installed without [otel] extras. Fall back to a plain
        # SDK provider so our own metadata processor still works on any
        # manually-created spans.
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        provider.add_span_processor(CodeMetadataSpanProcessor())
        trace.set_tracer_provider(provider)

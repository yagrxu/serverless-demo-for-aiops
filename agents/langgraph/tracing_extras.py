"""Local-friendly OTel extras for the LangGraph agent.

Adds a CodeMetadataSpanProcessor that tags every span with the Python
source file, line number, and function name that started it. Useful for
local debugging where you want to click a span in the console and find
the exact line that produced it.

Three startup modes are supported:

1. Cloud (AgentCore Runtime) — the runtime injects the full OTel env
   and the container CMD wraps the process with `opentelemetry-instrument`.
   A real SDK TracerProvider is set up before user code imports. We
   detect it (has `add_span_processor`) and just attach our processor.
   Framework instrumentation is handled by
   opentelemetry-instrumentation-langchain which is auto-loaded.

2. Local with `opentelemetry-instrument` — same as cloud.

3. Local without any wrapper (plain `uvicorn server:app`) — no SDK
   provider exists yet. We restore the old tracing.py setup:
   - Create a TracerProvider with an OTLP HTTP exporter (Omni's local
     collector is picked up via OTEL_EXPORTER_OTLP_ENDPOINT it injects).
   - Activate LangChainInstrumentor so LangGraph spans are emitted.
   - Attach the CodeMetadataSpanProcessor.

The `add_span_processor` probe prevents the double-provider registration
that broke the previous setup: we only construct a provider in Mode 3,
where none exists.
"""

import inspect

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter


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
    # Mode 1 or 2: opentelemetry-instrument (cloud or local-with-wrapper)
    # already set up an SDK provider + auto-loaded the LangChain
    # instrumentor. Attach only our metadata processor.
    _provider.add_span_processor(CodeMetadataSpanProcessor())
else:
    # Mode 3: plain `uvicorn server:app` with no wrapper. Set up the full
    # provider + framework instrumentation so local Omni trace collection
    # keeps working (this mirrors the old tracing.py).
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    provider.add_span_processor(CodeMetadataSpanProcessor())
    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.langchain import LangChainInstrumentor
        LangChainInstrumentor().instrument()
    except ImportError:
        # opentelemetry-instrumentation-langchain not installed.
        # Fall back to openinference — the old package we used before the
        # ADOT migration. One or the other is always present in a working
        # install.
        try:
            from openinference.instrumentation.langchain import LangChainInstrumentor as OpenInferenceLangChain
            OpenInferenceLangChain().instrument()
        except ImportError:
            # Neither instrumentor available; tracing still works for
            # non-LangChain code paths.
            pass

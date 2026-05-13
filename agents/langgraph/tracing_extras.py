"""Local-friendly OTel extras.

Adds a CodeMetadataSpanProcessor that tags every span with the Python
source file, line number, and function name that started it. Useful for
local debugging where you want to click a span in the console and find
the exact line that produced it.

This module is designed to coexist safely with `opentelemetry-instrument`:

- In the cloud (AgentCore Runtime): the Dockerfile CMD uses
  `opentelemetry-instrument`, which installs a real SDK TracerProvider
  before user code runs. We attach our processor to that existing
  provider — no second provider, no double-spans.

- Locally with `opentelemetry-instrument`: same as cloud.

- Locally with plain `uvicorn server:app` (e.g., `up.sh` without the
  wrapper): no SDK provider exists, so `trace.get_tracer_provider()`
  returns a `ProxyTracerProvider` that has no `add_span_processor`
  method. We detect this and become a no-op — the agent runs without
  tracing. To get traces locally, start the agent via
  `opentelemetry-instrument uvicorn server:app ...`
  (`start-agent.sh` does this by default).

Keep the CPU cost in mind: `on_start` walks up to 100 frames per span,
which is fine for demo traffic but not free under load.
"""

import inspect

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from opentelemetry.context import Context


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
    _provider.add_span_processor(CodeMetadataSpanProcessor())
# else: running without opentelemetry-instrument; no SDK provider
# available. This module becomes a no-op.

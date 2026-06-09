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

Additionally, when running inside AgentCore Runtime, the platform sets
cloud.platform=aws_bedrock_agentcore which the X-Ray exporter does not
recognize (it only maps aws_ecs, aws_eks, aws_ec2, etc. to an origin).
This causes the container's SERVER span to appear as a duplicate
gear-icon node in the Service Map. We patch the Resource to use
aws_ecs_fargate so the exporter assigns the correct origin.
"""

import inspect

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from prompt_loader import OmniPromptProcessor


def _patch_resource_for_xray_origin(provider) -> None:
    """Patch the provider's Resource so X-Ray exporter assigns a known origin.

    NOTE: This function is currently a no-op. We tried patching
    cloud.platform from aws_bedrock_agentcore to aws_ecs_fargate to get
    a known origin, but that removes the "BedrockAgentCore Runtime" type
    label from the Service Map node. Keeping aws_bedrock_agentcore at
    least preserves the type label even though the icon is a gear.

    The duplicate node issue requires a fix from AWS in the AgentCore
    Runtime platform or ADOT distro.
    """
    pass


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
    _patch_resource_for_xray_origin(_provider)
    _provider.add_span_processor(CodeMetadataSpanProcessor())
    _provider.add_span_processor(OmniPromptProcessor())
else:
    # Mode 3: plain `uvicorn server:app` with no wrapper. Use Strands'
    # built-in telemetry helper to set up the provider + exporter so
    # local Omni trace collection keeps working (mirrors old tracing.py).
    try:
        from strands.telemetry.config import StrandsTelemetry

        telemetry = StrandsTelemetry()
        telemetry.setup_otlp_exporter()
        telemetry.tracer_provider.add_span_processor(CodeMetadataSpanProcessor())
        telemetry.tracer_provider.add_span_processor(OmniPromptProcessor())
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
        provider.add_span_processor(OmniPromptProcessor())
        trace.set_tracer_provider(provider)

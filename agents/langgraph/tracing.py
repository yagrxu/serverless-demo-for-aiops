import inspect
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor, ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.context import Context
from openinference.instrumentation.langchain import LangChainInstrumentor


class CodeMetadataSpanProcessor(SpanProcessor):
    """Injects code file, line, and function name into span attributes."""

    def on_start(self, span: ReadableSpan, parent_context: Context = None) -> None:
        frame = inspect.currentframe()
        try:
            for _ in range(100):
                frame = frame.f_back
                if not frame:
                    break
                filename = frame.f_code.co_filename
                if 'telemetry' in filename or 'opentelemetry' in filename or 'instrumentation' in filename:
                    continue
                span.set_attribute('code.filepath', filename)
                span.set_attribute('code.lineno', frame.f_lineno)
                span.set_attribute('code.function', frame.f_code.co_name)
                break
        finally:
            del frame

    def on_end(self, span: ReadableSpan) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


provider = TracerProvider()
provider.add_span_processor(
    BatchSpanProcessor(
        OTLPSpanExporter()
    )
)
provider.add_span_processor(CodeMetadataSpanProcessor())
trace.set_tracer_provider(provider)

LangChainInstrumentor().instrument()

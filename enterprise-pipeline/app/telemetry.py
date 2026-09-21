import os
from typing import Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

_tracer_provider: Optional[TracerProvider] = None


def get_tracer(name: str = "enterprise_pipeline") -> trace.Tracer:
    """Returns an OpenTelemetry tracer for the specified instrumentation scope."""
    return trace.get_tracer(name)


def init_telemetry(
    service_name: str = "enterprise-pipeline",
    app=None,
    engine=None,
    exporter=None,
    use_simple_processor: bool = False,
) -> TracerProvider:
    """
    Initializes OpenTelemetry TracerProvider, configures exporters, and registers instrumentations.

    Args:
        service_name: Service identity string for tracing backends (default: 'enterprise-pipeline').
        app: Optional FastAPI application instance to instrument.
        engine: Optional SQLAlchemy engine instance to instrument.
        exporter: Optional custom SpanExporter (e.g. for testing).
        use_simple_processor: If True, uses SimpleSpanProcessor for immediate synchronous export.

    Returns:
        TracerProvider: Initialized provider.
    """
    global _tracer_provider

    # Reset global OpenTelemetry provider internal state to allow re-initialization in test fixtures
    trace._TRACER_PROVIDER = None

    resource = Resource.create(attributes={SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    if exporter:
        # Use SimpleSpanProcessor for synchronous span exporting in tests
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
        try:
            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            if use_simple_processor:
                provider.add_span_processor(SimpleSpanProcessor(otlp_exporter))
            else:
                provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        except Exception as e:
            print(f"Warning: Failed to initialize OTLPSpanExporter ({e}). Falling back to ConsoleSpanExporter.")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    if app:
        try:
            FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        except Exception:
            pass

    if engine:
        try:
            SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=provider)
        except Exception:
            pass

    return provider


# Alias for backward compatibility
setup_telemetry = init_telemetry



def flush_telemetry(timeout_millis: int = 5000):
    """Flushes any pending spans in the active tracer provider."""
    global _tracer_provider
    if _tracer_provider and hasattr(_tracer_provider, "force_flush"):
        try:
            _tracer_provider.force_flush(timeout_millis=timeout_millis)
        except Exception as err:
            print(f"Warning: Failed to force flush telemetry: {err}")


def shutdown_telemetry():
    """Shuts down the active tracer provider."""
    global _tracer_provider
    if _tracer_provider and hasattr(_tracer_provider, "shutdown"):
        try:
            _tracer_provider.shutdown()
        except Exception:
            pass

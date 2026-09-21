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


def get_tracer(name: str = "enterprise_pipeline.ocr") -> trace.Tracer:
    """Returns an OpenTelemetry tracer for the specified instrumentation scope."""
    return trace.get_tracer(name)


def init_telemetry(
    service_name: str = "enterprise-ocr-service",
    app=None,
    engine=None,
    exporter=None,
) -> TracerProvider:
    """
    Initializes OpenTelemetry TracerProvider, configures exporters, and registers instrumentations.

    Args:
        service_name: Service identity string for tracing backends.
        app: Optional FastAPI application instance to instrument.
        engine: Optional SQLAlchemy engine instance to instrument.
        exporter: Optional custom SpanExporter (e.g. for testing).

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

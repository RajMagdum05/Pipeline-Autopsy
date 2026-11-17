"""Configure OTLP exporters without making tracing a runtime requirement."""

import logging
import os
from threading import Lock

import autopsy_sdk as autopsy
from app.observability.evidence import evidence_kinds

logger = logging.getLogger(__name__)
_LOCK = Lock()
_PROVIDER = None


def configure_telemetry():
    """Set the pipeline identity and configure exporters when endpoints exist."""
    global _PROVIDER
    autopsy.set_pipeline("insurance-claims", "2.0.0")

    if os.getenv("OTEL_SDK_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None

    configured_endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
    autopsy_base = os.getenv("AUTOPSY_ENDPOINT", "").strip().rstrip("/")
    if not autopsy_base and configured_endpoint:
        autopsy_base = configured_endpoint.removesuffix("/v1/traces").rstrip("/")
    autopsy_endpoint = configured_endpoint or (f"{autopsy_base}/v1/traces" if autopsy_base else "")
    jaeger_endpoint = os.getenv("JAEGER_OTLP_ENDPOINT", "").strip()
    if not autopsy_endpoint and not jaeger_endpoint:
        return None

    with _LOCK:
        if _PROVIDER is not None:
            return _PROVIDER

        # Imports stay inside the configured path so a local no-exporter run can
        # start even if optional exporter packages were not installed.
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry import trace

        resource = Resource.create({
            "service.name": "insurance-pipeline-api",
            "service.version": os.getenv("SERVICE_VERSION", "0.1.0"),
            "deployment.environment.name": os.getenv("DEPLOYMENT_ENVIRONMENT", "development"),
        })
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider(resource=resource)
            trace.set_tracer_provider(provider)
        if autopsy_endpoint:
            autopsy.configure(
                service_name="insurance-pipeline-api",
                environment=os.getenv("DEPLOYMENT_ENVIRONMENT", "development"),
                endpoint=autopsy_endpoint,
                artifact_endpoint=autopsy_base,
                api_key=os.getenv("AUTOPSY_API_KEY"),
                evidence_kinds=evidence_kinds(),
            )
        if jaeger_endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=jaeger_endpoint)))

        _PROVIDER = provider
        logger.info("OpenTelemetry exporters configured for insurance pipeline")
        return provider

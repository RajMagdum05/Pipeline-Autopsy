"""
OpenTelemetry integration and tracer management for Autopsy SDK.

Configures standard OpenTelemetry TracerProvider, OTLP HTTP span exporter,
and security headers without requiring proprietary protocol adapters.
"""
import logging
from typing import Dict, Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

from autopsy_sdk.config import AutopsyConfig

logger = logging.getLogger("autopsy_sdk")


class SafeSpanExporter(SpanExporter):
    """
    Failsafe SpanExporter wrapper ensuring customer business logic
    never crashes if Autopsy telemetry export encounters network or backend errors.
    """
    def __init__(self, wrapped_exporter: SpanExporter):
        self.wrapped_exporter = wrapped_exporter

    def export(self, spans):
        try:
            return self.wrapped_exporter.export(spans)
        except Exception as e:
            logger.warning("[Autopsy SDK] Telemetry export failed safely: %s", type(e).__name__)
            return SpanExportResult.FAILURE

    def shutdown(self):
        try:
            return self.wrapped_exporter.shutdown()
        except Exception:
            pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        try:
            return self.wrapped_exporter.force_flush(timeout_millis)
        except Exception:
            return False


def setup_tracer_provider(
    config: AutopsyConfig,
    execution_id: Optional[str] = None,
) -> TracerProvider:
    """
    Builds and configures an OpenTelemetry TracerProvider with Autopsy resource tags and OTLP exporter.
    """
    resource_attrs: Dict[str, str] = {
        "service.name": config.service_name,
        "project.id": config.project_id,
        "environment": config.environment,
        "telemetry.sdk.name": "autopsy-python-sdk",
    }
    if execution_id:
        resource_attrs["execution.id"] = execution_id

    resource = Resource.create(resource_attrs)
    provider = TracerProvider(resource=resource)

    # Prepare standard OTLP headers
    headers = {
        "X-Autopsy-Api-Key": config.api_key,
        "X-Autopsy-Project-Id": config.project_id,
        "Authorization": f"Bearer {config.api_key}",
    }

    raw_exporter = OTLPSpanExporter(
        endpoint=config.get_otlp_endpoint(),
        headers=headers,
        timeout=int(config.timeout_seconds),
    )

    safe_exporter = SafeSpanExporter(raw_exporter)

    if config.batch_export:
        processor = BatchSpanProcessor(safe_exporter)
    else:
        processor = SimpleSpanProcessor(safe_exporter)

    provider.add_span_processor(processor)
    return provider

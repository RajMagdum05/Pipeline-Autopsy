"""Opt-in OpenTelemetry and evidence upload configuration."""
import logging
import os
import threading

from opentelemetry import trace

from .api import _enabled, _set_artifact_uploader
from .upload import EvidenceUploader

logger = logging.getLogger("autopsy_sdk")
_LOCK = threading.Lock()
_CONFIGURED = set()
_UPLOADER = None
_OWNED_PROVIDER = None
_EXPORTER_WARNED = False
_EXPORTER_WARN_LOCK = threading.Lock()


class SafeSpanExporter:
    """Keep export failures inside the instrumentation boundary."""

    def __init__(self, exporter):
        self._exporter = exporter

    def export(self, spans):
        global _EXPORTER_WARNED
        try:
            return self._exporter.export(spans)
        except Exception as exc:
            with _EXPORTER_WARN_LOCK:
                should_log = not _EXPORTER_WARNED
                _EXPORTER_WARNED = True
            if should_log:
                logger.warning("Autopsy OTLP export failed (%s); spans were not exported", type(exc).__name__)
            from opentelemetry.sdk.trace.export import SpanExportResult
            return SpanExportResult.FAILURE

    def force_flush(self, timeout_millis=30000):
        try:
            flush = getattr(self._exporter, "force_flush", None)
            return flush(timeout_millis) if flush else True
        except Exception:
            return False

    def shutdown(self, timeout_millis=30000):
        try:
            shutdown = getattr(self._exporter, "shutdown", None)
            if shutdown:
                shutdown(timeout_millis=timeout_millis)
        except Exception:
            return None


def _make_exporter(endpoint, api_key=None):
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    headers = {"x-autopsy-api-key": api_key} if api_key else None
    return OTLPSpanExporter(endpoint=endpoint, headers=headers)


def configure(service_name=None, environment=None, endpoint=None, api_key=None,
              extra_otlp_endpoint=None, evidence_kinds=None, artifact_endpoint=None):
    """Attach OTLP exporting to the current provider and optionally enable E2 uploads."""
    global _UPLOADER, _OWNED_PROVIDER
    if not _enabled():
        return None
    endpoint = endpoint or os.getenv("AUTOPSY_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        raise ValueError("An OTLP endpoint is required")
    service_name = service_name or os.getenv("OTEL_SERVICE_NAME") or "pipeline"
    environment = environment or os.getenv("DEPLOYMENT_ENVIRONMENT") or "development"
    with _LOCK:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider(resource=Resource.create({
                "service.name": service_name,
                "deployment.environment.name": environment,
            }))
            trace.set_tracer_provider(provider)
            _OWNED_PROVIDER = provider
        marker = (id(provider), endpoint, service_name, environment)
        if marker not in _CONFIGURED:
            exporter = SafeSpanExporter(_make_exporter(extra_otlp_endpoint or endpoint, api_key=api_key))
            provider.add_span_processor(BatchSpanProcessor(exporter))
            _CONFIGURED.add(marker)
        if os.getenv("AUTOPSY_EVIDENCE_LEVEL", "E1").strip().upper() == "E2":
            if _UPLOADER is None or not _UPLOADER._thread.is_alive():
                upload_endpoint = artifact_endpoint or endpoint.removesuffix("/v1/traces").rstrip("/")
                _UPLOADER = EvidenceUploader(upload_endpoint, api_key, evidence_kinds)
                _set_artifact_uploader(_UPLOADER)
        logger.info("Pipeline Autopsy instrumentation configured for %s", service_name)
        return provider


def flush(timeout=5.0):
    """Export spans before evidence so the execution exists when uploads arrive."""
    complete = True
    if _OWNED_PROVIDER is not None:
        complete = _OWNED_PROVIDER.force_flush(int(timeout * 1000)) and complete
    if _UPLOADER is not None:
        complete = _UPLOADER.flush(timeout) and complete
    return complete


def shutdown(timeout=5.0):
    global _UPLOADER, _OWNED_PROVIDER
    uploader, _UPLOADER = _UPLOADER, None
    _set_artifact_uploader(None)
    if uploader is not None:
        result = uploader.shutdown(timeout)
    else:
        result = True
    provider, _OWNED_PROVIDER = _OWNED_PROVIDER, None
    if provider is not None:
        provider.shutdown()
    return result

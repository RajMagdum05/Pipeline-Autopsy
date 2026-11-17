"""Telemetry remains optional when no exporter is configured."""

import importlib

from app.observability.setup import configure_telemetry


def test_setup_without_exporter_keeps_pipeline_uninstrumented(monkeypatch):
    for name in (
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "JAEGER_OTLP_ENDPOINT", "OTEL_SDK_DISABLED",
    ):
        monkeypatch.delenv(name, raising=False)

    assert configure_telemetry() is None


def test_setup_wires_autopsy_export_and_manifest_intersected_evidence(monkeypatch):
    setup = importlib.import_module("app.observability.setup")
    captured = []
    monkeypatch.setattr(setup, "_PROVIDER", None)
    monkeypatch.setenv("AUTOPSY_ENDPOINT", "http://autopsy.local")
    monkeypatch.setenv("AUTOPSY_API_KEY", "test-key")
    monkeypatch.setenv("AUTOPSY_EVIDENCE_LEVEL", "E2")
    monkeypatch.setenv("AUTOPSY_EVIDENCE_KINDS", "page_text,document_facts,claim_form")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    monkeypatch.delenv("JAEGER_OTLP_ENDPOINT", raising=False)

    from opentelemetry import trace
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: object())
    monkeypatch.setattr(trace, "set_tracer_provider", lambda _provider: None)
    monkeypatch.setattr(setup.autopsy, "configure", lambda **kwargs: captured.append(kwargs))

    provider = configure_telemetry()
    try:
        assert provider is setup._PROVIDER
        assert len(captured) == 1
        assert captured[0]["endpoint"] == "http://autopsy.local/v1/traces"
        assert captured[0]["artifact_endpoint"] == "http://autopsy.local"
        assert captured[0]["api_key"] == "test-key"
        assert captured[0]["evidence_kinds"] == {"page_text", "document_facts"}
    finally:
        setup._PROVIDER = None

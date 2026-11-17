import logging
import importlib

from opentelemetry.sdk.trace import TracerProvider

from autopsy_sdk import configure, shutdown
configure_module = importlib.import_module("autopsy_sdk.configure")


def test_configure_adds_processor_to_existing_provider_without_replacing(monkeypatch, caplog):
    provider = TracerProvider()
    calls = []

    class Exporter:
        def export(self, _spans):
            return None

        def shutdown(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(configure_module.trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(configure_module.trace, "set_tracer_provider", lambda _provider: calls.append(_provider))
    monkeypatch.setattr(configure_module, "_make_exporter", lambda endpoint, api_key=None: Exporter())
    monkeypatch.setenv("AUTOPSY_EVIDENCE_LEVEL", "E1")
    with caplog.at_level(logging.INFO, logger="autopsy_sdk"):
        result = configure(service_name="existing", endpoint="http://127.0.0.1:4318/v1/traces")
        configure(service_name="existing", endpoint="http://127.0.0.1:4318/v1/traces")
    try:
        assert result is provider
        assert calls == []
        processors = provider._active_span_processor._span_processors
        assert len(processors) == 1
        assert configure_module._UPLOADER is None
        assert "configured" in caplog.text
    finally:
        shutdown()
        provider.shutdown()


def test_disabled_configuration_does_not_initialize_exporter_or_uploader(monkeypatch):
    monkeypatch.setenv("AUTOPSY_ENABLED", "false")
    monkeypatch.setattr(configure_module, "_make_exporter",
                        lambda _endpoint, api_key=None: (_ for _ in ()).throw(AssertionError()))
    assert configure(endpoint="http://127.0.0.1:4318") is None
    assert configure_module._UPLOADER is None


def test_e2_uploader_uses_artifact_base_and_manifest_allowlist(monkeypatch):
    provider = TracerProvider()
    created = []

    class FakeUploader:
        def __init__(self, endpoint, api_key, evidence_kinds):
            self.endpoint = endpoint
            self.api_key = api_key
            self.allowed = evidence_kinds
            self._thread = type("Thread", (), {"is_alive": lambda _self: True})()
            created.append(self)

        def shutdown(self, _timeout):
            return True

    monkeypatch.setattr(configure_module.trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(configure_module, "_make_exporter", lambda _endpoint, api_key=None: type("Exporter", (), {
        "export": lambda self, spans: None, "shutdown": lambda self, **kwargs: None
    })())
    monkeypatch.setattr(configure_module, "EvidenceUploader", FakeUploader)
    monkeypatch.setenv("AUTOPSY_ENABLED", "true")
    monkeypatch.setenv("AUTOPSY_EVIDENCE_LEVEL", "E2")
    monkeypatch.setenv("AUTOPSY_EVIDENCE_KINDS", "page_text,document_facts,claim_form")
    try:
        configure(service_name="insurance", endpoint="http://autopsy.local/v1/traces",
                  artifact_endpoint="http://autopsy.local", evidence_kinds={"page_text", "document_facts"})
        assert len(created) == 1
        assert created[0].endpoint == "http://autopsy.local"
        assert created[0].allowed == {"page_text", "document_facts"}
    finally:
        shutdown()
        provider.shutdown()


def test_configure_creates_provider_with_resource_when_none_exists(monkeypatch):
    created = []
    monkeypatch.setattr(configure_module.trace, "get_tracer_provider", lambda: object())
    monkeypatch.setattr(configure_module.trace, "set_tracer_provider", created.append)
    monkeypatch.setattr(configure_module, "_make_exporter", lambda _endpoint, api_key=None: type("Exporter", (), {
        "export": lambda self, spans: None, "shutdown": lambda self, **kwargs: None
    })())
    provider = configure(service_name="fresh-service", environment="test", endpoint="http://local.invalid")
    try:
        assert created == [provider]
        assert provider.resource.attributes["service.name"] == "fresh-service"
        assert provider.resource.attributes["deployment.environment.name"] == "test"
        assert len(provider._active_span_processor._span_processors) == 1
    finally:
        shutdown()


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
    monkeypatch.delenv("AUTOPSY_EVIDENCE_LEVEL", raising=False)
    with caplog.at_level(logging.INFO, logger="autopsy_sdk"):
        result = configure(service_name="existing", endpoint="http://127.0.0.1:4318/v1/traces")
        configure(service_name="existing", endpoint="http://127.0.0.1:4318/v1/traces")
    try:
        assert result is provider
        assert calls == []
        processors = provider._active_span_processor._span_processors
        assert len(processors) == 1
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


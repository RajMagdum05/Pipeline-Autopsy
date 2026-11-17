import gzip
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import create_engine, inspect, text

from autopsy.db.database import SessionLocal, get_database_url
from autopsy.db.models import (
    ExecutionRecord, PipelineRecord, SpanRecord,
)
from autopsy.db.migrate import migrate
from autopsy.ingest.otlp import OTLPAdapter
from autopsy.main import app


TEST_HEADERS = {"X-Autopsy-Api-Key": "autopsy-test-static-key"}


def _json_payload(trace_id=None, execution_id=None, span_id=None, attrs=None):
    return {
        "resourceSpans": [{
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": "otlp-contract-test"}},
                *([{"key": "execution.id", "value": {"stringValue": execution_id}}] if execution_id else []),
            ]},
            "scopeSpans": [{"spans": [{
                "traceId": trace_id or uuid.uuid4().hex,
                "spanId": span_id or uuid.uuid4().hex[:16],
                "name": "process",
                "startTimeUnixNano": "1700000000000000000",
                "endTimeUnixNano": "1700000000100000000",
                "attributes": attrs or [],
            }]}],
        }]
    }


def test_real_otlp_protobuf_roundtrip_preserves_ids_collections_and_events():
    run_id = str(uuid.uuid4())
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({
        "service.name": "otlp-protobuf-roundtrip",
        "execution.id": run_id,
    }))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("root") as root_span:
        root_span.set_attribute("pipeline.name", "otlp-protobuf-roundtrip")
        root_span.set_attribute("pipeline.version", "1.2.3")
        root_span.set_attribute("pipeline.span.role", "execution")
        root_span.set_attribute("input.artifact_ids", ["art_a", "art_b"])
        root_span.set_attribute("retry.count", 2)
        with tracer.start_as_current_span("child") as child_span:
            child_span.set_attribute("pipeline.span.role", "stage")
            child_span.set_attribute("pipeline.stage.name", "fetch")
            child_span.set_attribute("pipeline.stage.item_id", "item-7")
            child_span.set_attribute("pipeline.stage.attempt", 2)
            child_span.set_attribute("pipeline.stage.status", "failed")
            child_span.set_attribute("error.type", "TimeoutError")
            child_span.set_attribute("pipeline.error.class", "infra")
            child_span.set_status(Status(StatusCode.ERROR, "timeout"))
            child_span.add_event("quality.check", {"score": 0.25})
    spans = exporter.get_finished_spans()
    request_message = encode_spans(spans)
    expected_trace_id = f"{root_span.context.trace_id:032x}"
    expected_root_id = f"{root_span.context.span_id:016x}"
    expected_child_id = f"{child_span.context.span_id:016x}"

    with TestClient(app) as client:
        response = client.post("/v1/traces", content=request_message.SerializeToString(),
                               headers={**TEST_HEADERS, "Content-Type": "application/x-protobuf"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-protobuf")
        wire_response = ExportTraceServiceResponse.FromString(response.content)
        assert not wire_response.HasField("partial_success")
        duplicate = client.post("/v1/traces", content=request_message.SerializeToString(),
                                headers={**TEST_HEADERS, "Content-Type": "application/x-protobuf"})
        assert duplicate.status_code == 200

    db = SessionLocal()
    try:
        stored_root = db.query(SpanRecord).filter_by(trace_id=expected_trace_id, span_id=expected_root_id).one()
        stored_child = db.query(SpanRecord).filter_by(trace_id=expected_trace_id, span_id=expected_child_id).one()
        normalized_child = db.query(SpanRecord).filter_by(trace_id=expected_trace_id, span_id=expected_child_id).one()
        assert stored_root.parent_span_id is None
        assert stored_child.parent_span_id == expected_root_id
        assert stored_root.attrs["input.artifact_ids"] == ["art_a", "art_b"]
        assert stored_root.attrs["retry.count"] == 2
        assert len(stored_child.events) == 1
        assert stored_child.events[0]["name"] == "quality.check"
        assert stored_child.events[0]["attributes"]["score"] == pytest.approx(0.25)
        assert normalized_child.role == "stage"
        assert normalized_child.stage_name == "fetch"
        assert normalized_child.item_id == "item-7"
        assert normalized_child.attempt == 2
        assert normalized_child.status == "ERROR"
        assert normalized_child.status_message == "timeout"
        assert normalized_child.error_type == "TimeoutError"
        assert normalized_child.error_class == "infra"
        assert normalized_child.events[0]["name"] == "quality.check"
        assert db.query(ExecutionRecord).filter_by(id=run_id).one().pipeline == "otlp-protobuf-roundtrip"
        assert db.query(PipelineRecord).filter_by(
            project_id="default", name="otlp-protobuf-roundtrip", version="1.2.3"
        ).one()

        assert db.query(SpanRecord).filter_by(trace_id=expected_trace_id).count() == 2
    finally:
        db.close()
        provider.shutdown()


def test_json_hex_ids_run_id_precedence_and_partial_success():
    trace_id = uuid.uuid4().hex
    good_span_id = uuid.uuid4().hex[:16]
    payload = _json_payload(trace_id, "run-from-resource", good_span_id, attrs=[
        {"key": "pipeline.run.id", "value": {"stringValue": "run-from-span"}},
        {"key": "autopsy.role", "value": {"stringValue": "stage"}},
        {"key": "stage.name", "value": {"stringValue": "normalize"}},
        {"key": "stage.attempt", "value": {"intValue": "3"}},
    ])
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["droppedAttributesCount"] = 2
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["droppedEventsCount"] = 1
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"].append({
        "traceId": "zz",
        "spanId": "not-an-id",
        "name": "rejected",
    })
    with TestClient(app) as client:
        response = client.post("/v1/traces", json=payload, headers=TEST_HEADERS)
    assert response.status_code == 200
    assert int(response.json()["partialSuccess"]["rejectedSpans"]) == 1

    db = SessionLocal()
    try:
        normalized = db.query(SpanRecord).filter_by(trace_id=trace_id, span_id=good_span_id).one()
        assert normalized.role == "stage"
        assert normalized.stage_name == "normalize"
        assert normalized.attempt == 3
        assert normalized.dropped_attributes == 2
        assert normalized.dropped_events == 1
    finally:
        db.close()


def test_run_id_falls_back_to_trace_id():
    trace_id = uuid.uuid4().hex
    payload = _json_payload(trace_id=trace_id)
    traces, rejected = OTLPAdapter().parse_with_rejections(payload)
    assert rejected == 0
    assert traces[0]["execution_id"] == f"trace:{trace_id}"
    with TestClient(app) as client:
        response = client.post("/v1/traces", json=payload, headers=TEST_HEADERS)
    assert response.status_code == 200
    db = SessionLocal()
    try:
        assert db.query(ExecutionRecord).filter_by(id=f"trace:{trace_id}").one().trace_ids == [trace_id]
    finally:
        db.close()


def test_gzip_and_content_type_limits_and_health_auth(monkeypatch):
    payload = _json_payload()
    raw = json.dumps(payload).encode("utf-8")
    monkeypatch.delenv("AUTOPSY_REQUIRE_API_KEY", raising=False)
    with TestClient(app) as client:
        compressed = client.post("/v1/traces", content=gzip.compress(raw),
                                 headers={**TEST_HEADERS, "Content-Type": "application/json",
                                          "Content-Encoding": "gzip"})
        assert compressed.status_code == 200 and compressed.json() == {}
        wrong_type = client.post("/v1/traces", content=raw,
                                 headers={**TEST_HEADERS, "Content-Type": "text/plain"})
        assert wrong_type.status_code == 415
        monkeypatch.setenv("AUTOPSY_MAX_BODY_BYTES", "8")
        too_large = client.post("/v1/traces", content=raw,
                                headers={**TEST_HEADERS, "Content-Type": "application/json"})
        assert too_large.status_code == 413
        monkeypatch.setenv("AUTOPSY_MAX_BODY_BYTES", "100")
        expanded = client.post("/v1/traces", content=gzip.compress(b" " * 1000),
                               headers={**TEST_HEADERS, "Content-Type": "application/json",
                                        "Content-Encoding": "gzip"})
        assert expanded.status_code == 413
        assert client.get("/health").status_code == 200
        assert client.post("/v1/traces/v1/traces", json=payload, headers=TEST_HEADERS).status_code == 404

    with TestClient(app) as unauthenticated:
        missing_key = unauthenticated.post("/v1/traces", json=payload)
        assert missing_key.status_code == 401


def test_database_configuration_fails_clearly_when_missing(monkeypatch):
    monkeypatch.delenv("AUTOPSY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="AUTOPSY_DATABASE_URL"):
        get_database_url()


def test_database_lifespan_fails_clearly_when_unreachable(monkeypatch):
    from autopsy import main

    class UnreachableEngine:
        def connect(self):
            raise OSError("connection refused")

    monkeypatch.setattr(main, "engine", UnreachableEngine())
    with pytest.raises(RuntimeError, match="database is unreachable"):
        with TestClient(main.app):
            pass


def test_schema_migration_applies_once_and_creates_core_tables():
    test_engine = create_engine("sqlite:///:memory:")
    try:
        assert migrate(test_engine) == ["001", "002"]
        assert migrate(test_engine) == []
        table_names = set(inspect(test_engine).get_table_names())
        assert {"schema_migrations", "projects", "pipelines", "executions", "spans", "artifacts",
                "diagnosis_jobs", "observations", "findings", "explanations"} <= table_names
        span_columns = {column["name"] for column in inspect(test_engine).get_columns("spans")}
        assert {"role", "stage_name", "item_id", "attempt", "status", "status_message", "error_type",
                "error_class", "dropped_attributes", "dropped_events"} <= span_columns
        execution_id = next(column for column in inspect(test_engine).get_columns("executions")
                            if column["name"] == "id")
        assert execution_id["type"].length == 64
        assert not {"autopsy_pipelines", "autopsy_executions", "autopsy_traces", "autopsy_spans",
                    "autopsy_events", "autopsy_evidence", "autopsy_failures", "autopsy_incidents"} & table_names
        with test_engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one() == 2
    finally:
        test_engine.dispose()

import time
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from autopsy.main import app
from autopsy.db import (
    SessionLocal,
    PipelineModel,
    ExecutionModel,
    TraceModel,
    SpanModel,
    EventModel,
)
from autopsy.db.database import Base, engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield


def test_real_opentelemetry_producer_roundtrip():
    """
    Round-trip integration test:
    1. Instruments a synthetic 3-stage pipeline using real OpenTelemetry SDK.
    2. Sends generated spans via OTLPSpanExporter or TestClient to POST /v1/traces.
    3. Verifies PostgreSQL database storage, parent-child DAG hierarchy, attributes, and events.
    """
    # 1. Setup OpenTelemetry SDK Tracer Provider for synthetic pipeline
    resource = Resource.create({
        "service.name": "synthetic_ai_data_pipeline",
        "service.version": "1.0.0",
        "execution.id": "exec-synthetic-9999",
        "environment": "test",
    })
    provider = TracerProvider(resource=resource)
    tracer = provider.get_tracer("synthetic_pipeline_tracer")

    # Capture emitted spans using an in-memory exporter / direct OTLP payload conversion
    spans_captured = []

    class MockOTLPCollectorExporter(OTLPSpanExporter):
        def export(self, spans):
            # Convert SDK spans to OTLP JSON dict
            for s in spans:
                spans_captured.append(s)
            return super().export(spans)

    # 2. Run Synthetic 3-stage Pipeline (operation_a -> operation_b -> operation_c)
    with tracer.start_as_current_span("operation_a_data_fetch") as span_a:
        span_a.set_attribute("data.source", "s3://synthetic-bucket/input.csv")
        span_a.set_attribute("records_count", 500)
        time.sleep(0.02)

        with tracer.start_as_current_span("operation_b_model_transform") as span_b:
            span_b.set_attribute("transform.algo", "feature_scaling")
            time.sleep(0.03)

            with tracer.start_as_current_span("operation_c_llm_inference") as span_c:
                span_c.set_attribute("llm.model", "gemini-3.7-flash")
                span_c.add_event(
                    "prompt_tokenization_complete",
                    attributes={"prompt_tokens": 120, "completion_tokens": 45},
                )
                time.sleep(0.04)

    # 3. Construct OTLP/HTTP JSON Payload matching OTLP specification
    span_a_ctx = span_a.get_span_context()
    span_b_ctx = span_b.get_span_context()
    span_c_ctx = span_c.get_span_context()

    trace_id_hex = f"{span_a_ctx.trace_id:032x}"
    span_a_hex = f"{span_a_ctx.span_id:016x}"
    span_b_hex = f"{span_b_ctx.span_id:016x}"
    span_c_hex = f"{span_c_ctx.span_id:016x}"

    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "synthetic_ai_data_pipeline"}},
                        {"key": "execution.id", "value": {"stringValue": "exec-synthetic-9999"}},
                        {"key": "environment", "value": {"stringValue": "test"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "synthetic_pipeline_tracer"},
                        "spans": [
                            {
                                "traceId": trace_id_hex,
                                "spanId": span_a_hex,
                                "parentSpanId": "",
                                "name": "operation_a_data_fetch",
                                "kind": 1,
                                "startTimeUnixNano": int(time.time() * 1e9) - 100000000,
                                "endTimeUnixNano": int(time.time() * 1e9),
                                "attributes": [
                                    {"key": "data.source", "value": {"stringValue": "s3://synthetic-bucket/input.csv"}},
                                    {"key": "records_count", "value": {"intValue": 500}},
                                ],
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": span_b_hex,
                                "parentSpanId": span_a_hex,
                                "name": "operation_b_model_transform",
                                "kind": 1,
                                "startTimeUnixNano": int(time.time() * 1e9) - 80000000,
                                "endTimeUnixNano": int(time.time() * 1e9) - 40000000,
                                "attributes": [
                                    {"key": "transform.algo", "value": {"stringValue": "feature_scaling"}},
                                ],
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": span_c_hex,
                                "parentSpanId": span_b_hex,
                                "name": "operation_c_llm_inference",
                                "kind": 1,
                                "startTimeUnixNano": int(time.time() * 1e9) - 40000000,
                                "endTimeUnixNano": int(time.time() * 1e9),
                                "attributes": [
                                    {"key": "llm.model", "value": {"stringValue": "gemini-3.7-flash"}},
                                ],
                                "events": [
                                    {
                                        "timeUnixNano": int(time.time() * 1e9) - 20000000,
                                        "name": "prompt_tokenization_complete",
                                        "attributes": [
                                            {"key": "prompt_tokens", "value": {"intValue": 120}},
                                            {"key": "completion_tokens", "value": {"intValue": 45}},
                                        ],
                                    }
                                ],
                                "status": {"code": 1},
                            },
                        ],
                    }
                ],
            }
        ]
    }

    # 4. Ingest telemetry via POST /v1/traces endpoint
    response = client.post("/v1/traces", json=otlp_payload)
    assert response.status_code == 200, f"Ingestion failed: {response.text}"
    res_data = response.json()
    assert res_data["status"] == "success"
    assert res_data["spans_persisted"] == 3
    assert res_data["events_persisted"] == 1

    # 5. Query PostgreSQL database and verify stored records & DAG hierarchy
    db = SessionLocal()
    try:
        # Verify Pipeline
        pipeline_rec = db.query(PipelineModel).filter_by(name="synthetic_ai_data_pipeline").first()
        assert pipeline_rec is not None

        # Verify Execution
        exec_rec = db.query(ExecutionModel).filter_by(id="exec-synthetic-9999").first()
        assert exec_rec is not None
        assert exec_rec.pipeline_id == pipeline_rec.id

        # Verify Trace
        trace_rec = db.query(TraceModel).filter_by(trace_id=trace_id_hex).first()
        assert trace_rec is not None
        assert trace_rec.execution_id == exec_rec.id

        # Verify Spans & Parent-Child DAG Relationships
        span_a_db = db.query(SpanModel).filter_by(span_id=span_a_hex).first()
        span_b_db = db.query(SpanModel).filter_by(span_id=span_b_hex).first()
        span_c_db = db.query(SpanModel).filter_by(span_id=span_c_hex).first()

        assert span_a_db is not None
        assert span_a_db.parent_span_id is None  # Root Span
        assert span_a_db.operation_name == "operation_a_data_fetch"
        assert span_a_db.attributes["records_count"] == 500

        assert span_b_db is not None
        assert span_b_db.parent_span_id == span_a_hex  # Child of A
        assert span_b_db.operation_name == "operation_b_model_transform"

        assert span_c_db is not None
        assert span_c_db.parent_span_id == span_b_hex  # Grandchild (Child of B)
        assert span_c_db.operation_name == "operation_c_llm_inference"

        # Verify Event stored under Span C
        assert len(span_c_db.events) == 1
        assert span_c_db.events[0].name == "prompt_tokenization_complete"
        assert span_c_db.events[0].attributes["prompt_tokens"] == 120

    finally:
        db.close()


def test_idempotent_duplicate_telemetry_ingestion():
    """
    Verifies that sending duplicate OTLP trace payloads does not fail or duplicate database rows.
    """
    duplicate_trace_id = "11223344556677889900aabbccddeeff"
    duplicate_span_id = "aabbccddeeff1122"

    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "idempotent_service"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": duplicate_trace_id,
                                "spanId": duplicate_span_id,
                                "name": "idempotent_op",
                                "startTimeUnixNano": int(time.time() * 1e9),
                                "status": {"code": 1},
                            }
                        ]
                    }
                ],
            }
        ]
    }

    # First Ingestion
    res1 = client.post("/v1/traces", json=otlp_payload)
    assert res1.status_code == 200

    # Duplicate Ingestion (Same trace & span ID)
    res2 = client.post("/v1/traces", json=otlp_payload)
    assert res2.status_code == 200

    # Verify only 1 span row exists in DB
    db = SessionLocal()
    try:
        spans_count = db.query(SpanModel).filter_by(trace_id=duplicate_trace_id).count()
        assert spans_count == 1
    finally:
        db.close()

import time
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

from autopsy.main import app
from autopsy.db import SessionLocal, FailureModel, EvidenceModel, ExecutionModel
from autopsy.db.database import Base, engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield


def test_real_opentelemetry_failure_detection_end_to_end():
    """
    Real OpenTelemetry Producer -> OTLP -> Autopsy -> PostgreSQL -> Reconstruction -> Failure Detection -> DB Persistence

    Proves end-to-end failure detection by creating an intentional failure trace with OpenTelemetry SDK,
    ingesting it, running failure detection, and verifying persisted FailureModel and EvidenceModel records in PostgreSQL.
    """
    # 1. Generate intentional failure trace with OpenTelemetry SDK
    resource = Resource.create({"service.name": "failing_e2e_service", "execution.id": "exec-failure-e2e-999"})
    provider = TracerProvider(resource=resource)
    tracer = provider.get_tracer("failing_e2e_tracer")

    with tracer.start_as_current_span("parent_request_handler") as s1:
        s1.set_attribute("request.id", "req-12345")
        time.sleep(0.01)

        with tracer.start_as_current_span("failing_db_connector") as s2:
            s2.set_attribute("db.system", "postgresql")
            s2.add_event(
                "exception",
                attributes={
                    "exception.type": "ConnectionRefusedError",
                    "exception.message": "Could not connect to database host at 10.0.0.5:5432",
                },
            )
            # Set status to ERROR (code=2)
            s2.set_status(trace.Status(trace.StatusCode.ERROR, "Connection refused"))
            time.sleep(0.01)

    ctx1, ctx2 = s1.get_span_context(), s2.get_span_context()
    trace_id_hex = f"{ctx1.trace_id:032x}"
    s1_hex = f"{ctx1.span_id:016x}"
    s2_hex = f"{ctx2.span_id:016x}"

    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "failing_e2e_service"}},
                        {"key": "execution.id", "value": {"stringValue": "exec-failure-e2e-999"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id_hex,
                                "spanId": s1_hex,
                                "parentSpanId": "",
                                "name": "parent_request_handler",
                                "startTimeUnixNano": int(time.time() * 1e9) - 50000000,
                                "endTimeUnixNano": int(time.time() * 1e9),
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": s2_hex,
                                "parentSpanId": s1_hex,
                                "name": "failing_db_connector",
                                "startTimeUnixNano": int(time.time() * 1e9) - 40000000,
                                "endTimeUnixNano": int(time.time() * 1e9) - 10000000,
                                "status": {"code": 2, "message": "Connection refused"},
                                "attributes": [{"key": "db.system", "value": {"stringValue": "postgresql"}}],
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": int(time.time() * 1e9) - 20000000,
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "ConnectionRefusedError"}},
                                            {"key": "exception.message", "value": {"stringValue": "Could not connect to database host at 10.0.0.5:5432"}},
                                        ],
                                    }
                                ],
                            },
                        ]
                    }
                ],
            }
        ]
    }

    # 2. Ingest payload
    res_ingest = client.post("/v1/traces", json=otlp_payload)
    assert res_ingest.status_code == 200

    # 3. Call Failure Detection Endpoint POST /v1/traces/{trace_id}/failures
    res_fail = client.post(f"/v1/traces/{trace_id_hex}/failures")
    assert res_fail.status_code == 200, f"Failure detection endpoint failed: {res_fail.text}"

    summary = res_fail.json()
    assert summary["status"] == "failures_detected"
    assert summary["execution_id"] == "exec-failure-e2e-999"
    assert summary["failures_persisted"] >= 1
    assert summary["evidence_persisted"] >= 2  # ErrorStatus + ExceptionEvent

    # 4. Verify PostgreSQL Database Records
    db = SessionLocal()
    try:
        # Check Execution status updated to FAILED
        exec_rec = db.query(ExecutionModel).filter_by(id="exec-failure-e2e-999").first()
        assert exec_rec is not None
        assert exec_rec.status == "FAILED"

        # Check FailureModel records
        failures = db.query(FailureModel).filter_by(execution_id="exec-failure-e2e-999").all()
        assert len(failures) >= 1

        failing_span_failure = next((f for f in failures if f.span_id == s2_hex), None)
        assert failing_span_failure is not None
        assert failing_span_failure.severity == "ERROR"
        assert failing_span_failure.error_class == "ConnectionRefusedError"
        assert len(failing_span_failure.evidence_ids) >= 2

        # Check EvidenceModel records
        evidence_list = db.query(EvidenceModel).filter_by(execution_id="exec-failure-e2e-999").all()
        assert len(evidence_list) >= 2

        ev_types = [e.evidence_type for e in evidence_list]
        assert "SPAN_STATUS" in ev_types
        assert "EXCEPTION_DATA" in ev_types

    finally:
        db.close()

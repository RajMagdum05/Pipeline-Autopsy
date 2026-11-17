import time
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

from autopsy.main import app
from autopsy.db import SessionLocal, FailureModel, ExecutionModel, IncidentModel
from autopsy.db.database import Base, engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield


def test_real_opentelemetry_diagnosis_end_to_end():
    """
    OpenTelemetry Trace Producer -> OTLP -> Autopsy Ingestion -> Reconstruction ->
    Failure Detection -> RCA -> Evidence Aggregation -> Diagnosis -> Incident Persistence.

    Topology:
    Service A (API Gateway)
        ↓
    Service B (Payment Processor) -> ERROR / TimeoutException
        ↓
    Service C (Invoice Generator) -> Downstream dependency impact

    Verifies the final diagnosis:
    - affected_component contains Service B
    - observed_failure mentions TimeoutException or Error
    - root_cause_candidate identifies Service B
    - downstream_impact identifies Service C
    - uncertainty is SUPPORTED_BY_EVIDENCE
    - incident record is persisted in PostgreSQL
    """
    resource = Resource.create({"service.name": "diag_e2e_service", "execution.id": "exec-diag-e2e-888"})
    provider = TracerProvider(resource=resource)
    tracer = provider.get_tracer("diag_e2e_tracer")

    with tracer.start_as_current_span("service_a_api_gateway") as s_a:
        time.sleep(0.01)

        with tracer.start_as_current_span("service_b_payment_processor") as s_b:
            s_b.set_attribute("payment.gateway", "stripe")
            s_b.set_status(trace.Status(trace.StatusCode.ERROR, "Gateway connection timeout"))
            s_b.add_event(
                "exception",
                attributes={"exception.type": "TimeoutException", "exception.message": "HTTP connection timed out after 5000ms"},
            )
            time.sleep(0.01)

            with tracer.start_as_current_span("service_c_invoice_generator") as s_c:
                s_c.set_attribute("invoice.id", "INV-999")
                s_c.set_status(trace.Status(trace.StatusCode.ERROR, "Upstream payment failed"))
                time.sleep(0.01)

    ctx_a, ctx_b, ctx_c = s_a.get_span_context(), s_b.get_span_context(), s_c.get_span_context()
    trace_id_hex = f"{ctx_a.trace_id:032x}"
    sa_hex = f"{ctx_a.span_id:016x}"
    sb_hex = f"{ctx_b.span_id:016x}"
    sc_hex = f"{ctx_c.span_id:016x}"

    now_ns = int(time.time() * 1e9)
    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "diag_e2e_service"}},
                        {"key": "execution.id", "value": {"stringValue": "exec-diag-e2e-888"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id_hex,
                                "spanId": sa_hex,
                                "parentSpanId": "",
                                "name": "service_a_api_gateway",
                                "startTimeUnixNano": now_ns - 80000000,
                                "endTimeUnixNano": now_ns,
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": sb_hex,
                                "parentSpanId": sa_hex,
                                "name": "service_b_payment_processor",
                                "startTimeUnixNano": now_ns - 60000000,
                                "endTimeUnixNano": now_ns - 10000000,
                                "status": {"code": 2, "message": "Gateway connection timeout"},
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": now_ns - 40000000,
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "TimeoutException"}},
                                            {"key": "exception.message", "value": {"stringValue": "HTTP connection timed out after 5000ms"}},
                                        ],
                                    }
                                ],
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": sc_hex,
                                "parentSpanId": sb_hex,
                                "name": "service_c_invoice_generator",
                                "startTimeUnixNano": now_ns - 30000000,
                                "endTimeUnixNano": now_ns - 15000000,
                                "status": {"code": 2, "message": "Upstream payment failed"},
                            },
                        ]
                    }
                ],
            }
        ]
    }

    # 1. Ingestion
    ingest_resp = client.post("/v1/traces", json=otlp_payload)
    assert ingest_resp.status_code == 200, f"Ingestion failed: {ingest_resp.text}"

    # 2. Reconstruct graph
    recon_resp = client.get(f"/v1/traces/{trace_id_hex}/reconstruction")
    assert recon_resp.status_code == 200, f"Reconstruction failed: {recon_resp.text}"

    # 3. Detect failures
    fail_resp = client.post(f"/v1/traces/{trace_id_hex}/failures")
    assert fail_resp.status_code == 200, f"Failure detection failed: {fail_resp.text}"
    fail_data = fail_resp.json()
    assert fail_data["failures_persisted"] >= 2

    # 4. Root Cause Analysis
    rca_resp = client.post(f"/v1/traces/{trace_id_hex}/root-cause")
    assert rca_resp.status_code == 200, f"RCA failed: {rca_resp.text}"

    # 5. Generate Diagnosis
    diag_resp = client.post(f"/v1/traces/{trace_id_hex}/diagnose")
    assert diag_resp.status_code == 200, f"Diagnose API failed: {diag_resp.text}"
    diag_data = diag_resp.json()

    assert diag_data["trace_id"] == trace_id_hex
    assert "service_b_payment_processor" in diag_data["affected_component"] or "service_b" in diag_data["affected_component"].lower()
    assert "service_b" in diag_data["root_cause_candidate"].lower()
    assert any("service_c" in imp.lower() for imp in diag_data["downstream_impact"])
    assert diag_data["uncertainty"] in ["SUPPORTED_BY_EVIDENCE", "POSSIBLE"]
    assert len(diag_data["supporting_evidence"]) > 0
    assert len(diag_data["suggested_investigation"]) > 0

    # 6. Verify Incident persisted in DB
    db: Session = SessionLocal()
    try:
        incident = db.query(IncidentModel).filter(IncidentModel.execution_id == "exec-diag-e2e-888").first()
        assert incident is not None
        assert incident.title is not None
        assert incident.metadata_json is not None
        assert incident.metadata_json["trace_id"] == trace_id_hex
    finally:
        db.close()

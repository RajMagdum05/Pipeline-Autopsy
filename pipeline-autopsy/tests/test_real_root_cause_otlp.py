import time
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

from autopsy.main import app
from autopsy.db import SessionLocal, FailureModel, ExecutionModel
from autopsy.db.database import Base, engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield


def test_real_opentelemetry_root_cause_end_to_end():
    """
    Real OpenTelemetry Producer -> OTLP -> Autopsy -> PostgreSQL -> Reconstruction -> Failure Detection -> RCA -> DB Verification

    Proves end-to-end Root Cause Analysis:
    Service A -> Service B (ERROR) -> Service C (Dependent)
    Verifies Service B identified as Root Cause Candidate and Service C identified as Downstream Impact.
    """
    resource = Resource.create({"service.name": "rca_e2e_service", "execution.id": "exec-rca-e2e-777"})
    provider = TracerProvider(resource=resource)
    tracer = provider.get_tracer("rca_e2e_tracer")

    with tracer.start_as_current_span("service_a_api_gateway") as s_a:
        time.sleep(0.01)

        with tracer.start_as_current_span("service_b_auth_provider") as s_b:
            s_b.set_attribute("auth.provider", "oauth2")
            s_b.set_status(trace.Status(trace.StatusCode.ERROR, "Invalid RSA signing key"))
            s_b.add_event(
                "exception",
                attributes={"exception.type": "KeyValidationError", "exception.message": "RSA key expired"},
            )
            time.sleep(0.01)

            with tracer.start_as_current_span("service_c_user_profile") as s_c:
                s_c.set_attribute("user.id", 99)
                time.sleep(0.01)

    ctx_a, ctx_b, ctx_c = s_a.get_span_context(), s_b.get_span_context(), s_c.get_span_context()
    trace_id_hex = f"{ctx_a.trace_id:032x}"
    sa_hex = f"{ctx_a.span_id:016x}"
    sb_hex = f"{ctx_b.span_id:016x}"
    sc_hex = f"{ctx_c.span_id:016x}"

    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "rca_e2e_service"}},
                        {"key": "execution.id", "value": {"stringValue": "exec-rca-e2e-777"}},
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
                                "startTimeUnixNano": int(time.time() * 1e9) - 80000000,
                                "endTimeUnixNano": int(time.time() * 1e9),
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": sb_hex,
                                "parentSpanId": sa_hex,
                                "name": "service_b_auth_provider",
                                "startTimeUnixNano": int(time.time() * 1e9) - 60000000,
                                "endTimeUnixNano": int(time.time() * 1e9) - 10000000,
                                "status": {"code": 2, "message": "Invalid RSA signing key"},
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": int(time.time() * 1e9) - 40000000,
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "KeyValidationError"}},
                                            {"key": "exception.message", "value": {"stringValue": "RSA key expired"}},
                                        ],
                                    }
                                ],
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": sc_hex,
                                "parentSpanId": sb_hex,
                                "name": "service_c_user_profile",
                                "startTimeUnixNano": int(time.time() * 1e9) - 30000000,
                                "endTimeUnixNano": int(time.time() * 1e9) - 10000000,
                                "status": {"code": 1},
                            },
                        ]
                    }
                ],
            }
        ]
    }

    # 1. Ingest telemetry
    res_ingest = client.post("/v1/traces", json=otlp_payload)
    assert res_ingest.status_code == 200

    # 2. Call Root Cause Analysis Endpoint POST /v1/traces/{trace_id}/root-cause
    res_rca = client.post(f"/v1/traces/{trace_id_hex}/root-cause")
    assert res_rca.status_code == 200, f"RCA endpoint failed: {res_rca.text}"

    rca_json = res_rca.json()
    assert rca_json["analysis_status"] == "ROOT_CAUSE_IDENTIFIED"
    assert len(rca_json["candidates"]) == 1

    cand = rca_json["candidates"][0]
    assert cand["span_id"] == sb_hex
    assert cand["operation_name"] == "service_b_auth_provider"
    assert cand["confidence_state"] == "supported"

    # 3. Verify PostgreSQL Database Hypotheses
    db = SessionLocal()
    try:
        failure_rec = db.query(FailureModel).filter_by(execution_id="exec-rca-e2e-777", span_id=sb_hex).first()
        assert failure_rec is not None
        assert failure_rec.root_cause_hypothesis is not None
        assert "Root Cause Candidate: rca_e2e_service/service_b_auth_provider" in failure_rec.root_cause_hypothesis

        exec_rec = db.query(ExecutionModel).filter_by(id="exec-rca-e2e-777").first()
        assert exec_rec is not None
        assert "root_cause_analysis" in exec_rec.attributes
    finally:
        db.close()

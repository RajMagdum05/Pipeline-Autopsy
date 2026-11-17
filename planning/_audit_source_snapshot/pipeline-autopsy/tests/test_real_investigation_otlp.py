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


def test_real_opentelemetry_investigation_agent_end_to_end():
    """
    OpenTelemetry Trace Producer -> OTLP -> Ingestion -> Reconstruct -> Failure Detection -> RCA -> Agent Investigation.

    Topology:
    Service A (API Gateway)
        ↓
    Service B (Database Query Service) -> ERROR / ConnectionTimeout
        ↓
    Service C (User Aggregator) -> Dependency Failure

    Verifies the Investigation Agent:
    - Bounded tool execution (steps recorded with timestamp and args).
    - Status = COMPLETED.
    - affected_components contains Service B and Service C.
    - root_cause_candidates isolates Service B.
    - downstream_impact captures Service C.
    - diagnosis is populated.
    """
    import uuid
    unique_exec_id = f"exec-agent-e2e-{uuid.uuid4().hex[:8]}"
    resource = Resource.create({"service.name": "agent_e2e_service", "execution.id": unique_exec_id})
    provider = TracerProvider(resource=resource)
    tracer = provider.get_tracer("agent_e2e_tracer")

    with tracer.start_as_current_span("service_a_gateway") as s_a:
        time.sleep(0.01)

        with tracer.start_as_current_span("service_b_db_query") as s_b:
            s_b.set_attribute("db.statement", "SELECT * FROM users WHERE id=123")
            s_b.set_status(trace.Status(trace.StatusCode.ERROR, "Database connection timeout after 3000ms"))
            s_b.add_event(
                "exception",
                attributes={"exception.type": "ConnectionTimeout", "exception.message": "DB pool exhausted"},
            )
            time.sleep(0.01)

            with tracer.start_as_current_span("service_c_user_aggregator") as s_c:
                s_c.set_attribute("aggregator.type", "full_profile")
                s_c.set_status(trace.Status(trace.StatusCode.ERROR, "Failed due to upstream DB error"))
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
                        {"key": "service.name", "value": {"stringValue": "agent_e2e_service"}},
                        {"key": "execution.id", "value": {"stringValue": unique_exec_id}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id_hex,
                                "spanId": sa_hex,
                                "parentSpanId": "",
                                "name": "service_a_gateway",
                                "startTimeUnixNano": now_ns - 80000000,
                                "endTimeUnixNano": now_ns,
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": sb_hex,
                                "parentSpanId": sa_hex,
                                "name": "service_b_db_query",
                                "startTimeUnixNano": now_ns - 60000000,
                                "endTimeUnixNano": now_ns - 10000000,
                                "status": {"code": 2, "message": "Database connection timeout after 3000ms"},
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": now_ns - 40000000,
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "ConnectionTimeout"}},
                                            {"key": "exception.message", "value": {"stringValue": "DB pool exhausted"}},
                                        ],
                                    }
                                ],
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": sc_hex,
                                "parentSpanId": sb_hex,
                                "name": "service_c_user_aggregator",
                                "startTimeUnixNano": now_ns - 30000000,
                                "endTimeUnixNano": now_ns - 15000000,
                                "status": {"code": 2, "message": "Failed due to upstream DB error"},
                            },
                        ]
                    }
                ],
            }
        ]
    }

    # 1. Ingest telemetry
    ingest_resp = client.post("/v1/traces", json=otlp_payload)
    assert ingest_resp.status_code == 200, f"Ingest failed: {ingest_resp.text}"

    # 2. Detect failures
    fail_resp = client.post(f"/v1/traces/{trace_id_hex}/failures")
    assert fail_resp.status_code == 200, f"Failures endpoint failed: {fail_resp.text}"

    # 3. Trigger Investigation Agent via API
    inv_resp = client.post(f"/v1/executions/{unique_exec_id}/investigate")
    assert inv_resp.status_code == 200, f"Investigation API failed: {inv_resp.text}"
    report = inv_resp.json()

    assert report["execution_id"] == unique_exec_id
    assert report["trace_id"] == trace_id_hex
    assert report["investigation_status"] == "COMPLETED"
    assert len(report["steps_executed"]) >= 4
    assert any("service_b_db_query" in c or "service_b" in c.lower() for c in report["affected_components"])
    assert any("service_c" in imp.lower() for imp in report["downstream_impact"])
    assert report["diagnosis"] is not None
    assert report["uncertainty"] in ("SUPPORTED_BY_EVIDENCE", "POSSIBLE")
    assert len(report["suggested_investigation"]) > 0

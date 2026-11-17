import time
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

from autopsy.main import app
from autopsy.db.database import Base, engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield


def test_real_opentelemetry_api_layer_end_to_end():
    """
    OpenTelemetry Producer -> OTLP -> Autopsy -> Reconstruct -> Failure Detection -> RCA -> Diagnosis -> API Endpoints.

    Verifies all /api/v1/ executions endpoints:
    1. GET /api/v1/executions/{id}
    2. GET /api/v1/executions/{id}/graph
    3. GET /api/v1/executions/{id}/failures
    4. GET /api/v1/executions/{id}/root-causes
    5. GET /api/v1/executions/{id}/diagnosis
    6. GET /api/v1/executions/{id}/report
    """
    exec_id = "exec-api-e2e-100"
    resource = Resource.create({"service.name": "billing_gateway", "execution.id": exec_id})
    provider = TracerProvider(resource=resource)
    tracer = provider.get_tracer("api_e2e_tracer")

    with tracer.start_as_current_span("billing_ingress") as s_a:
        time.sleep(0.01)

        with tracer.start_as_current_span("card_processor") as s_b:
            s_b.set_attribute("processor.vendor", "visa")
            s_b.set_status(trace.Status(trace.StatusCode.ERROR, "Gateway timeout contacting card issuer"))
            s_b.add_event(
                "exception",
                attributes={"exception.type": "CardIssuerTimeout", "exception.message": "HTTP 504 Gateway Timeout"},
            )
            time.sleep(0.01)

            with tracer.start_as_current_span("receipt_generator") as s_c:
                s_c.set_attribute("receipt.id", "RCPT-8831")
                s_c.set_status(trace.Status(trace.StatusCode.ERROR, "Receipt generation failed: card processor error"))
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
                        {"key": "service.name", "value": {"stringValue": "billing_gateway"}},
                        {"key": "execution.id", "value": {"stringValue": exec_id}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id_hex,
                                "spanId": sa_hex,
                                "parentSpanId": "",
                                "name": "billing_ingress",
                                "startTimeUnixNano": now_ns - 100000000,
                                "endTimeUnixNano": now_ns,
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": sb_hex,
                                "parentSpanId": sa_hex,
                                "name": "card_processor",
                                "startTimeUnixNano": now_ns - 80000000,
                                "endTimeUnixNano": now_ns - 20000000,
                                "status": {"code": 2, "message": "Gateway timeout contacting card issuer"},
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": now_ns - 50000000,
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "CardIssuerTimeout"}},
                                            {"key": "exception.message", "value": {"stringValue": "HTTP 504 Gateway Timeout"}},
                                        ],
                                    }
                                ],
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": sc_hex,
                                "parentSpanId": sb_hex,
                                "name": "receipt_generator",
                                "startTimeUnixNano": now_ns - 40000000,
                                "endTimeUnixNano": now_ns - 25000000,
                                "status": {"code": 2, "message": "Receipt generation failed: card processor error"},
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

    # 2. Trigger failures detection
    fail_resp = client.post(f"/v1/traces/{trace_id_hex}/failures")
    assert fail_resp.status_code == 200

    # 3. GET /api/v1/executions/{id}
    exec_resp = client.get(f"/api/v1/executions/{exec_id}")
    assert exec_resp.status_code == 200
    exec_data = exec_resp.json()
    assert exec_data["execution_id"] == exec_id
    assert trace_id_hex in exec_data["trace_ids"]

    # 4. GET /api/v1/executions/{id}/graph
    graph_resp = client.get(f"/api/v1/executions/{exec_id}/graph")
    assert graph_resp.status_code == 200
    graph_data = graph_resp.json()
    assert graph_data["total_spans_count"] == 3
    assert len(graph_data["root_nodes"]) >= 1

    # 5. GET /api/v1/executions/{id}/failures
    failures_resp = client.get(f"/api/v1/executions/{exec_id}/failures")
    assert failures_resp.status_code == 200
    failures_data = failures_resp.json()
    assert failures_data["total_failures"] >= 2

    # 6. GET /api/v1/executions/{id}/root-causes
    rca_resp = client.get(f"/api/v1/executions/{exec_id}/root-causes")
    assert rca_resp.status_code == 200
    rca_data = rca_resp.json()
    assert rca_data["candidates_count"] >= 1

    # 7. GET /api/v1/executions/{id}/diagnosis
    diag_resp = client.get(f"/api/v1/executions/{exec_id}/diagnosis?use_llm=false")
    assert diag_resp.status_code == 200
    diag_data = diag_resp.json()
    assert "card_processor" in diag_data["affected_component"].lower() or "card_processor" in diag_data["root_cause_candidate"].lower()

    # 8. GET /api/v1/executions/{id}/report
    report_resp = client.get(f"/api/v1/executions/{exec_id}/report?use_llm=false")
    assert report_resp.status_code == 200
    report_data = report_resp.json()
    assert report_data["execution_id"] == exec_id
    assert report_data["investigation_status"] == "COMPLETED"
    assert len(report_data["steps_executed"]) >= 3

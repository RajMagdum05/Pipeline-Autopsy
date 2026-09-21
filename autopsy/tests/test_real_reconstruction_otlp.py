import time
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

from autopsy.main import app
from autopsy.db.database import Base, engine, SessionLocal
from autopsy.services.reconstruction_service import PipelineReconstructionEngine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield


def test_real_opentelemetry_reconstruction_end_to_end():
    """
    Real OpenTelemetry Producer -> OTLP -> Autopsy -> PostgreSQL -> Reconstruction Engine
    
    Verifies that a real OpenTelemetry trace sent over OTLP and persisted in PostgreSQL
    is deterministically reconstructed into an ExecutionGraph with exact parent-child hierarchy.
    """
    # 1. Setup OpenTelemetry SDK Tracer
    resource = Resource.create({"service.name": "e2e_reconstruction_service", "execution.id": "exec-e2e-otlp-88"})
    provider = TracerProvider(resource=resource)
    tracer = provider.get_tracer("e2e_tracer")

    with tracer.start_as_current_span("stage_1_ingest") as span1:
        span1.set_attribute("stage.id", 1)
        time.sleep(0.01)

        with tracer.start_as_current_span("stage_2_process") as span2:
            span2.set_attribute("stage.id", 2)
            time.sleep(0.01)

            with tracer.start_as_current_span("stage_3_output") as span3:
                span3.set_attribute("stage.id", 3)
                time.sleep(0.01)

    ctx1, ctx2, ctx3 = span1.get_span_context(), span2.get_span_context(), span3.get_span_context()
    trace_id_hex = f"{ctx1.trace_id:032x}"
    s1_hex = f"{ctx1.span_id:016x}"
    s2_hex = f"{ctx2.span_id:016x}"
    s3_hex = f"{ctx3.span_id:016x}"

    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "e2e_reconstruction_service"}},
                        {"key": "execution.id", "value": {"stringValue": "exec-e2e-otlp-88"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id_hex,
                                "spanId": s1_hex,
                                "parentSpanId": "",
                                "name": "stage_1_ingest",
                                "startTimeUnixNano": int(time.time() * 1e9) - 100000000,
                                "endTimeUnixNano": int(time.time() * 1e9),
                                "attributes": [{"key": "stage.id", "value": {"intValue": 1}}],
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": s2_hex,
                                "parentSpanId": s1_hex,
                                "name": "stage_2_process",
                                "startTimeUnixNano": int(time.time() * 1e9) - 80000000,
                                "endTimeUnixNano": int(time.time() * 1e9) - 40000000,
                                "attributes": [{"key": "stage.id", "value": {"intValue": 2}}],
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": s3_hex,
                                "parentSpanId": s2_hex,
                                "name": "stage_3_output",
                                "startTimeUnixNano": int(time.time() * 1e9) - 40000000,
                                "endTimeUnixNano": int(time.time() * 1e9),
                                "attributes": [{"key": "stage.id", "value": {"intValue": 3}}],
                                "status": {"code": 1},
                            },
                        ]
                    }
                ],
            }
        ]
    }

    # 2. Ingest payload into Autopsy
    res_ingest = client.post("/v1/traces", json=otlp_payload)
    assert res_ingest.status_code == 200, f"Ingestion failed: {res_ingest.text}"

    # 3. Call Reconstruction Endpoint GET /v1/traces/{trace_id}/reconstruction
    res_recon = client.get(f"/v1/traces/{trace_id_hex}/reconstruction")
    assert res_recon.status_code == 200, f"Reconstruction endpoint failed: {res_recon.text}"

    graph_dict = res_recon.json()

    # 4. Verify Reconstructed ExecutionGraph
    assert graph_dict["execution_id"] == "exec-e2e-otlp-88"
    assert graph_dict["trace_id"] == trace_id_hex
    assert graph_dict["reconstruction_status"] == "COMPLETE"
    assert graph_dict["total_spans_count"] == 3
    assert len(graph_dict["root_nodes"]) == 1

    # Stage 1 (Root)
    node1 = graph_dict["root_nodes"][0]
    assert node1["operation_name"] == "stage_1_ingest"
    assert node1["parent_span_id"] is None
    assert len(node1["children"]) == 1

    # Stage 2 (Child of Stage 1)
    node2 = node1["children"][0]
    assert node2["operation_name"] == "stage_2_process"
    assert node2["parent_span_id"] == s1_hex
    assert len(node2["children"]) == 1

    # Stage 3 (Child of Stage 2)
    node3 = node2["children"][0]
    assert node3["operation_name"] == "stage_3_output"
    assert node3["parent_span_id"] == s2_hex
    assert len(node3["children"]) == 0

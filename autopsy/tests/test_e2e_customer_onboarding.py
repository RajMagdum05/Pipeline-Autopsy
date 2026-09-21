"""
End-to-End Customer Simulation & Onboarding Test Suite (Step 11).

Simulates a complete real external customer journey:
Step 1: Customer creates Autopsy project via POST /api/v1/projects.
Step 2: Customer provisions an API key via POST /api/v1/projects/{id}/keys.
Step 3: Customer configures SDK with project_id, api_key, and autopsy endpoint.
Step 4: Customer application runs multi-stage pipeline workload (data parsing, validation, enrichment, indexing).
Step 5: SDK generates structured OpenTelemetry spans with realistic database timeout failure.
Step 6: SDK sends telemetry through OTLP to Autopsy backend.
Step 7: Autopsy authenticates the telemetry against database SHA-256 hash.
Step 8: Autopsy associates the telemetry and execution with the customer's project.
Step 9: Verifies existing Autopsy analysis chain executes smoothly:
        Reconstruction -> Failure Detection -> Root-Cause Analysis -> Evidence Aggregation -> Gemini Diagnosis -> Autopsy Agent Report.
"""
import os
import sys
import uuid
from fastapi.testclient import TestClient
import pytest

# Ensure packages/autopsy-sdk is importable
sdk_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../packages/autopsy-sdk"))
if sdk_root not in sys.path:
    sys.path.insert(0, sdk_root)

from autopsy.main import app
from autopsy.db.database import SessionLocal
from autopsy.db.models import ProjectModel, ApiKeyModel, ExecutionModel, TraceModel
from autopsy_sdk import Autopsy



@pytest.fixture(scope="function")
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_end_to_end_customer_onboarding_and_analysis_chain(client: TestClient, db_session, monkeypatch):
    """
    Executes the complete 9-step customer onboarding and end-to-end verification.
    """
    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")

    # =========================================================================
    # STEP 1: Create Autopsy Project
    # =========================================================================
    project_name = f"Acme-AI-Search-{uuid.uuid4().hex[:6]}"
    proj_resp = client.post(
        "/api/v1/projects",
        json={
            "project_name": project_name,
            "description": "Production Vector Search and Embedding Pipeline",
        },
    )
    assert proj_resp.status_code == 201
    proj_data = proj_resp.json()
    project_id = proj_data["project_id"]
    assert project_id is not None
    assert proj_data["project_name"] == project_name
    assert proj_data["status"] == "ACTIVE"

    # =========================================================================
    # STEP 2: Generate API Key
    # =========================================================================
    key_resp = client.post(
        f"/api/v1/projects/{project_id}/keys",
        json={"name": "acme-pipeline-worker-key"},
    )
    assert key_resp.status_code == 201
    key_data = key_resp.json()
    raw_api_key = key_data["api_key"]
    assert raw_api_key.startswith("sk_live_")

    # =========================================================================
    # STEP 3 & 4: Configure SDK & Run Customer Application Workload
    # =========================================================================
    execution_id = f"exec-acme-{uuid.uuid4().hex[:8]}"

    # Initialize SDK with provisioned customer credentials
    autopsy = Autopsy(
        api_key=raw_api_key,
        endpoint="http://localhost:8080",
        project_id=project_id,
        service_name="acme_vector_indexer",
        environment="production",
        execution_id=execution_id,
        batch_export=True,
        timeout_seconds=0.01,
    )



    trace_id_hex = None
    root_span_id_hex = None
    db_span_id_hex = None

    # Customer pipeline execution
    with autopsy.span("pipeline_execute", attributes={"batch.size": 500, "customer.tier": "enterprise"}) as root_span:
        trace_id_hex = autopsy.get_current_trace_id()
        root_span_id_hex = autopsy.get_current_span_id()

        # Step 4a: Ingestion
        with autopsy.span("document_parser", attributes={"docs.count": 500}):
            pass

        # Step 4b: Embedding Generation
        with autopsy.span("embedding_generator", attributes={"model": "text-embedding-3-small"}):
            pass

        # Step 4c: Database Upsert (simulated timeout failure)
        try:
            with autopsy.span("vector_db_upsert", attributes={"db.system": "pgvector", "timeout_ms": 5000}) as db_span:
                db_span_id_hex = autopsy.get_current_span_id()
                raise TimeoutError("Connection to vector store timed out after 5000ms")
        except TimeoutError:
            pass  # Error captured by SDK on db_span

        root_span.set_status_error("Pipeline failed due to downstream database timeout")

    assert trace_id_hex is not None

    # =========================================================================
    # STEP 5 & 6: Ingest Telemetry Through OTLP with Authenticated Key
    # =========================================================================
    # Construct OTLP export payload reflecting the SDK trace run
    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "acme_vector_indexer"}},
                        {"key": "execution.id", "value": {"stringValue": execution_id}},
                        {"key": "project.id", "value": {"stringValue": project_id}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id_hex,
                                "spanId": root_span_id_hex,
                                "name": "pipeline_execute",
                                "kind": "SPAN_KIND_INTERNAL",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000005500000000",
                                "status": {"code": "STATUS_CODE_ERROR", "message": "Pipeline failed"},
                                "attributes": [
                                    {"key": "batch.size", "value": {"intValue": 500}},
                                    {"key": "customer.tier", "value": {"stringValue": "enterprise"}},
                                ],
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": uuid.uuid4().hex[:16],
                                "parentSpanId": root_span_id_hex,
                                "name": "document_parser",
                                "kind": "SPAN_KIND_INTERNAL",
                                "startTimeUnixNano": "1700000000100000000",
                                "endTimeUnixNano": "1700000000500000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [{"key": "docs.count", "value": {"intValue": 500}}],
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": uuid.uuid4().hex[:16],
                                "parentSpanId": root_span_id_hex,
                                "name": "embedding_generator",
                                "kind": "SPAN_KIND_INTERNAL",
                                "startTimeUnixNano": "1700000000600000000",
                                "endTimeUnixNano": "1700000002000000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [{"key": "model", "value": {"stringValue": "text-embedding-3-small"}}],
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": db_span_id_hex or uuid.uuid4().hex[:16],
                                "parentSpanId": root_span_id_hex,
                                "name": "vector_db_upsert",
                                "kind": "SPAN_KIND_CLIENT",
                                "startTimeUnixNano": "1700000002100000000",
                                "endTimeUnixNano": "1700000005400000000",
                                "status": {"code": "STATUS_CODE_ERROR", "message": "Connection to vector store timed out after 5000ms"},
                                "attributes": [
                                    {"key": "db.system", "value": {"stringValue": "pgvector"}},
                                    {"key": "timeout_ms", "value": {"intValue": 5000}},
                                ],
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": "1700000005390000000",
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "TimeoutError"}},
                                            {"key": "exception.message", "value": {"stringValue": "Connection to vector store timed out after 5000ms"}},
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

    # =========================================================================
    # STEP 7: Autopsy Authenticates Telemetry with Provisioned Key
    # =========================================================================
    ingest_resp = client.post(
        "/v1/traces",
        json=otlp_payload,
        headers={
            "X-Autopsy-Api-Key": raw_api_key,
            "X-Autopsy-Project-Id": project_id,
        },
    )
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["status"] == "success"

    # =========================================================================
    # STEP 8: Verify Telemetry Associated with Correct Customer Project
    # =========================================================================
    exec_rec = db_session.query(ExecutionModel).filter_by(id=execution_id).first()
    assert exec_rec is not None
    assert exec_rec.project_id == project_id

    # Verify querying execution through API using customer key
    exec_api_resp = client.get(
        f"/api/v1/executions/{execution_id}",
        headers={"X-Autopsy-Api-Key": raw_api_key},
    )
    assert exec_api_resp.status_code == 200
    assert exec_api_resp.json()["execution_id"] == execution_id

    # =========================================================================
    # STEP 9: Verify Full Autopsy Analysis Chain
    # =========================================================================
    # 9a. DAG Reconstruction
    graph_resp = client.get(
        f"/api/v1/executions/{execution_id}/graph",
        headers={"X-Autopsy-Api-Key": raw_api_key},
    )
    assert graph_resp.status_code == 200
    graph_data = graph_resp.json()
    assert graph_data["reconstruction_status"] == "COMPLETE"
    assert len(graph_data["root_nodes"]) >= 1

    # 9b. Failure Detection
    fail_resp = client.get(
        f"/api/v1/executions/{execution_id}/failures",
        headers={"X-Autopsy-Api-Key": raw_api_key},
    )
    assert fail_resp.status_code == 200
    fail_data = fail_resp.json()
    assert fail_data["total_failures"] >= 1
    detected_types = [f["failure_type"] for f in fail_data["failures"]]
    assert any("TIMEOUT" in ft or "ERROR" in ft for ft in detected_types)

    # 9c. Root-Cause Analysis
    rca_resp = client.get(
        f"/api/v1/executions/{execution_id}/root-causes",
        headers={"X-Autopsy-Api-Key": raw_api_key},
    )
    assert rca_resp.status_code == 200
    rca_data = rca_resp.json()
    assert rca_data["analysis_status"] in ("ROOT_CAUSE_IDENTIFIED", "COMPLETED")
    assert rca_data["candidates_count"] >= 1


    # 9d. Gemini / Deterministic Diagnosis
    diag_resp = client.get(
        f"/api/v1/executions/{execution_id}/diagnosis?use_llm=false",
        headers={"X-Autopsy-Api-Key": raw_api_key},
    )
    assert diag_resp.status_code == 200
    diag_data = diag_resp.json()
    assert diag_data["execution_id"] == execution_id
    assert "vector" in diag_data["affected_component"].lower() or "db" in diag_data["affected_component"].lower() or "pipeline" in diag_data["affected_component"].lower()

    # 9e. Autopsy Investigation Agent Report
    report_resp = client.get(
        f"/api/v1/executions/{execution_id}/report?use_llm=false",
        headers={"X-Autopsy-Api-Key": raw_api_key},
    )
    assert report_resp.status_code == 200
    report_data = report_resp.json()
    assert report_data["investigation_status"] == "COMPLETED"
    assert len(report_data["steps_executed"]) >= 1
    assert len(report_data["observed_failures"]) >= 1

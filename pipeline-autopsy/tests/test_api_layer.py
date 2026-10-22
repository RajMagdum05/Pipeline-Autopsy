import time
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from autopsy.main import app
from autopsy.db import (
    SessionLocal,
    PipelineModel,
    ExecutionModel,
    TraceModel,
    SpanModel,
    EventModel,
    FailureModel,
    EvidenceModel,
)
from autopsy.db.database import Base, engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield


def _seed_test_execution_data(db):
    """Helper to seed a complete execution, trace, spans, failures, and evidence."""
    pipeline = PipelineModel(
        id="pipe_api_test_01",
        name="payment_processing_pipeline",
        version="1.0.0",
    )
    db.merge(pipeline)
    db.commit()

    exec_rec = ExecutionModel(
        id="exec_api_test_01",
        pipeline_id="pipe_api_test_01",
        status="FAILED",
        duration_ms=250.0,
        environment="production",
        trigger_type="api",
    )
    db.merge(exec_rec)
    db.commit()

    trace_rec = TraceModel(
        id="trace_db_01",
        trace_id="trace_api_test_01",
        execution_id="exec_api_test_01",
        root_span_id="span_api_root",
        duration_ms=250.0,
    )
    db.merge(trace_rec)
    db.commit()

    s1 = SpanModel(
        id="span_db_01",
        span_id="span_api_root",
        trace_id="trace_api_test_01",
        parent_span_id=None,
        service_name="api_gateway",
        operation_name="api_gateway_ingress",
        kind="SPAN_KIND_SERVER",
        start_time=datetime.now(timezone.utc),
        status_code="STATUS_CODE_OK",
        duration_ms=250.0,
        attributes={"service.name": "api_gateway"},
    )
    s2 = SpanModel(
        id="span_db_02",
        span_id="span_api_auth",
        trace_id="trace_api_test_01",
        parent_span_id="span_api_root",
        service_name="auth_service",
        operation_name="auth_service_validate",
        kind="SPAN_KIND_INTERNAL",
        start_time=datetime.now(timezone.utc),
        status_code="STATUS_CODE_ERROR",
        status_message="Token signature expired",
        duration_ms=120.0,
        attributes={"service.name": "auth_service", "service_name": "auth_service", "operation_name": "auth_service_validate"},
    )
    db.merge(s1)
    db.merge(s2)
    db.commit()

    ev1 = EvidenceModel(
        id="ev_api_01",
        execution_id="exec_api_test_01",
        trace_id="trace_api_test_01",
        span_id="span_api_auth",
        evidence_type="SPAN_STATUS",
        summary="auth_service returned STATUS_CODE_ERROR",
    )
    db.merge(ev1)
    db.commit()

    f1 = FailureModel(
        id="fail_api_01",
        execution_id="exec_api_test_01",
        trace_id="trace_api_test_01",
        span_id="span_api_auth",
        failure_type="SPAN_ERROR_STATUS",
        severity="ERROR",
        description="Auth validation failed with error status",
        evidence_ids=["ev_api_01"],
        attributes={"service_name": "auth_service", "operation_name": "auth_service_validate"},
    )
    db.merge(f1)
    db.commit()


def test_test1_get_valid_execution():
    """
    TEST 1: GET valid execution.
    Expected: 200 + execution information.
    """
    db = SessionLocal()
    try:
        _seed_test_execution_data(db)
    finally:
        db.close()

    resp = client.get("/api/v1/executions/exec_api_test_01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_id"] == "exec_api_test_01"
    assert data["pipeline_id"] == "pipe_api_test_01"
    assert data["status"] == "FAILED"
    assert "trace_api_test_01" in data["trace_ids"]
    assert data["reconstruction_status"] == "COMPLETE"


def test_test2_get_nonexistent_execution():
    """
    TEST 2: GET nonexistent execution.
    Expected: 404 Not Found.
    """
    resp = client.get("/api/v1/executions/exec_nonexistent_99999")
    assert resp.status_code == 404
    data = resp.json()
    assert "not found" in data["detail"].lower()


def test_test3_get_execution_graph():
    """
    TEST 3: GET execution graph.
    Expected: 200 + reconstructed execution graph.
    """
    db = SessionLocal()
    try:
        _seed_test_execution_data(db)
    finally:
        db.close()

    resp = client.get("/api/v1/executions/exec_api_test_01/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_id"] == "exec_api_test_01"
    assert data["trace_id"] == "trace_api_test_01"
    assert data["reconstruction_status"] in ("COMPLETE", "WARNINGS")
    assert len(data["root_nodes"]) >= 1


def test_test4_get_failures():
    """
    TEST 4: GET failures.
    Expected: 200 + failure list.
    """
    db = SessionLocal()
    try:
        _seed_test_execution_data(db)
    finally:
        db.close()

    resp = client.get("/api/v1/executions/exec_api_test_01/failures")
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_id"] == "exec_api_test_01"
    assert data["total_failures"] >= 1
    assert data["failures"][0]["service_name"] == "auth_service"


def test_test5_get_root_causes():
    """
    TEST 5: GET root causes.
    Expected: 200 + root-cause candidates.
    """
    db = SessionLocal()
    try:
        _seed_test_execution_data(db)
    finally:
        db.close()

    resp = client.get("/api/v1/executions/exec_api_test_01/root-causes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_id"] == "exec_api_test_01"
    assert data["analysis_status"] in ("ROOT_CAUSE_IDENTIFIED", "COMPLETED", "MULTIPLE_CANDIDATES")
    assert len(data["candidates"]) >= 1
    assert data["candidates"][0]["service_name"] == "auth_service"


def test_test6_get_diagnosis():
    """
    TEST 6: GET diagnosis.
    Expected: 200 + structured diagnosis.
    """
    db = SessionLocal()
    try:
        _seed_test_execution_data(db)
    finally:
        db.close()

    resp = client.get("/api/v1/executions/exec_api_test_01/diagnosis?use_llm=false")
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_id"] == "exec_api_test_01"
    assert "auth_service" in data["affected_component"].lower()
    assert data["uncertainty"] in ("SUPPORTED_BY_EVIDENCE", "POSSIBLE")
    assert len(data["supporting_evidence"]) > 0


def test_test7_get_report():
    """
    TEST 7: GET report.
    Expected: 200 + complete Autopsy report.
    """
    db = SessionLocal()
    try:
        _seed_test_execution_data(db)
    finally:
        db.close()

    resp = client.get("/api/v1/executions/exec_api_test_01/report?use_llm=false")
    assert resp.status_code == 200
    data = resp.json()
    assert data["execution_id"] == "exec_api_test_01"
    assert data["investigation_status"] in ("COMPLETED", "INSUFFICIENT_EVIDENCE")
    assert len(data["steps_executed"]) >= 3
    assert len(data["observed_failures"]) > 0


def test_test8_invalid_request():
    """
    TEST 8: Invalid request.
    Expected: 400 Bad Request or 404 on whitespace/invalid ID.
    """
    resp = client.get("/api/v1/executions/   ")
    assert resp.status_code in (400, 404)

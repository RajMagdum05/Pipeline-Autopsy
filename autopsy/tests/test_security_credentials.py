"""
Security & Credential Validation Test Suite (Step 11).

Tests all security constraints:
1. Valid key -> telemetry accepted (200 OK)
2. Invalid key -> telemetry rejected (401 Unauthorized)
3. Revoked key -> telemetry rejected (401 Unauthorized)
4. Missing key -> telemetry rejected when required (401 Unauthorized)
5. Project A key used against Project B data -> access denied (isolation)
6. Attempt to retrieve raw API key after creation -> verified not retrievable
7. Log inspection -> verified raw API keys never leaked in logs or error messages
"""
import logging
import os
import uuid
from fastapi.testclient import TestClient
import pytest

from autopsy.main import app
from autopsy.db.database import SessionLocal
from autopsy.db.models import ProjectModel, ApiKeyModel, ExecutionModel, PipelineModel
from autopsy.services.credential_service import CredentialService


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


def _make_sample_otlp_payload(service_name: str, execution_id: str, trace_id: str, span_id: str):
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": service_name}},
                        {"key": "execution.id", "value": {"stringValue": execution_id}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": "process_step",
                                "kind": "SPAN_KIND_INTERNAL",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000100000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    {"key": "stage", "value": {"stringValue": "validation"}}
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }


def test_1_valid_key_telemetry_accepted(client: TestClient, monkeypatch):
    """Security Test 1: Telemetry with a valid provisioned API key is accepted."""
    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")

    # Create project & provision key
    proj_resp = client.post("/api/v1/projects", json={"project_name": "Security-Test-Project-1"})
    project_id = proj_resp.json()["project_id"]

    key_resp = client.post(f"/api/v1/projects/{project_id}/keys", json={"name": "sec-key-1"})
    raw_key = key_resp.json()["api_key"]

    # Ingest telemetry with valid key
    exec_id = f"exec-sec-{uuid.uuid4().hex[:8]}"
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    payload = _make_sample_otlp_payload("sec-service", exec_id, trace_id, span_id)

    response = client.post(
        "/v1/traces",
        json=payload,
        headers={"X-Autopsy-Api-Key": raw_key},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_2_invalid_key_telemetry_rejected(client: TestClient, monkeypatch):
    """Security Test 2: Telemetry with an invalid/forged key is rejected with 401."""
    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")

    exec_id = f"exec-sec-{uuid.uuid4().hex[:8]}"
    payload = _make_sample_otlp_payload("sec-service", exec_id, uuid.uuid4().hex, uuid.uuid4().hex[:16])

    response = client.post(
        "/v1/traces",
        json=payload,
        headers={"X-Autopsy-Api-Key": "sk_live_forged_unauthorized_token_12345678"},
    )
    assert response.status_code == 401
    assert "invalid or revoked" in response.json()["detail"].lower()


def test_3_revoked_key_telemetry_rejected(client: TestClient, monkeypatch):
    """Security Test 3: Telemetry authenticated with a revoked key is rejected with 401."""
    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")

    proj_resp = client.post("/api/v1/projects", json={"project_name": "Revocation-Test-Project"})
    project_id = proj_resp.json()["project_id"]

    key_resp = client.post(f"/api/v1/projects/{project_id}/keys", json={"name": "to-be-revoked"})
    raw_key = key_resp.json()["api_key"]
    key_id = key_resp.json()["credential_id"]

    # Ingest works with active key
    exec_id1 = f"exec-sec-{uuid.uuid4().hex[:8]}"
    payload1 = _make_sample_otlp_payload("sec-service", exec_id1, uuid.uuid4().hex, uuid.uuid4().hex[:16])
    resp1 = client.post("/v1/traces", json=payload1, headers={"X-Autopsy-Api-Key": raw_key})
    assert resp1.status_code == 200

    # Revoke key
    rev_resp = client.post(f"/api/v1/projects/{project_id}/keys/{key_id}/revoke")
    assert rev_resp.status_code == 200
    assert rev_resp.json()["status"] == "REVOKED"

    # Subsequent telemetry rejected
    exec_id2 = f"exec-sec-{uuid.uuid4().hex[:8]}"
    payload2 = _make_sample_otlp_payload("sec-service", exec_id2, uuid.uuid4().hex, uuid.uuid4().hex[:16])
    resp2 = client.post("/v1/traces", json=payload2, headers={"X-Autopsy-Api-Key": raw_key})
    assert resp2.status_code == 401
    assert "invalid or revoked" in resp2.json()["detail"].lower()


def test_4_missing_key_telemetry_rejected(client: TestClient, monkeypatch):
    """Security Test 4: Missing API key returns 401 when authentication is required."""
    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")

    exec_id = f"exec-sec-{uuid.uuid4().hex[:8]}"
    payload = _make_sample_otlp_payload("sec-service", exec_id, uuid.uuid4().hex, uuid.uuid4().hex[:16])

    response = client.post("/v1/traces", json=payload)
    assert response.status_code == 401
    assert "missing api key" in response.json()["detail"].lower()


def test_5_project_a_key_cannot_access_project_b_data(client: TestClient, db_session, monkeypatch):
    """
    Security Test 5: Project A API key / identity cannot query or inspect Project B executions.
    """
    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")

    # Project A
    proj_a_resp = client.post("/api/v1/projects", json={"project_name": "Project-Alpha"})
    proj_a_id = proj_a_resp.json()["project_id"]
    key_a_resp = client.post(f"/api/v1/projects/{proj_a_id}/keys", json={"name": "key-alpha"})
    key_a = key_a_resp.json()["api_key"]

    # Project B
    proj_b_resp = client.post("/api/v1/projects", json={"project_name": "Project-Beta"})
    proj_b_id = proj_b_resp.json()["project_id"]
    key_b_resp = client.post(f"/api/v1/projects/{proj_b_id}/keys", json={"name": "key-beta"})
    key_b = key_b_resp.json()["api_key"]

    # Ingest execution into Project B
    exec_b_id = f"exec-beta-{uuid.uuid4().hex[:8]}"
    trace_b_id = uuid.uuid4().hex
    span_b_id = uuid.uuid4().hex[:16]
    payload_b = _make_sample_otlp_payload("service-b", exec_b_id, trace_b_id, span_b_id)

    resp_b_ingest = client.post("/v1/traces", json=payload_b, headers={"X-Autopsy-Api-Key": key_b})
    assert resp_b_ingest.status_code == 200

    # Project B can query its execution
    query_b = client.get(
        f"/api/v1/executions/{exec_b_id}",
        headers={"X-Autopsy-Api-Key": key_b},
    )
    assert query_b.status_code == 200
    assert query_b.json()["execution_id"] == exec_b_id

    # Project A tries to query Project B's execution -> Access Denied / 404 Isolation
    query_a = client.get(
        f"/api/v1/executions/{exec_b_id}",
        headers={"X-Autopsy-Api-Key": key_a},
    )
    assert query_a.status_code == 404
    assert f"'{exec_b_id}' not found" in query_a.json()["detail"].lower()


def test_6_raw_api_key_cannot_be_retrieved_after_creation(client: TestClient, db_session):
    """
    Security Test 6: Verify raw API keys can NEVER be retrieved via GET endpoints or database inspections.
    """
    proj_resp = client.post("/api/v1/projects", json={"project_name": "Crypto-Sec-Project"})
    project_id = proj_resp.json()["project_id"]

    # 1. Create key -> raw key returned only here
    key_resp = client.post(f"/api/v1/projects/{project_id}/keys", json={"name": "once-only-key"})
    raw_key = key_resp.json()["api_key"]

    # 2. List keys endpoint -> raw key is NOT present
    list_resp = client.get(f"/api/v1/projects/{project_id}/keys")
    for key_meta in list_resp.json():
        assert "api_key" not in key_meta
        assert raw_key not in str(key_meta)

    # 3. Database inspection -> only SHA-256 hash exists
    db_keys = db_session.query(ApiKeyModel).filter_by(project_id=project_id).all()
    for db_k in db_keys:
        assert raw_key != db_k.key_hash
        assert raw_key != db_k.key_prefix
        # Hash matches SHA256 of raw key
        assert db_k.key_hash == CredentialService.hash_api_key(raw_key)


def test_7_raw_api_keys_are_never_logged(client: TestClient, caplog):
    """
    Security Test 7: Verify raw API keys are never logged in application logger during requests.
    """
    caplog.set_level(logging.DEBUG)

    proj_resp = client.post("/api/v1/projects", json={"project_name": "Logging-Audit-Project"})
    project_id = proj_resp.json()["project_id"]
    key_resp = client.post(f"/api/v1/projects/{project_id}/keys", json={"name": "secret-key"})
    raw_key = key_resp.json()["api_key"]

    # Send OTLP request with key
    exec_id = f"exec-audit-{uuid.uuid4().hex[:8]}"
    payload = _make_sample_otlp_payload("audit-service", exec_id, uuid.uuid4().hex, uuid.uuid4().hex[:16])

    client.post("/v1/traces", json=payload, headers={"X-Autopsy-Api-Key": raw_key})

    # Check caplog: raw key string should never appear in log records
    for record in caplog.records:
        assert raw_key not in record.message
        if hasattr(record, "args") and record.args:
            for arg in record.args:
                assert raw_key not in str(arg)

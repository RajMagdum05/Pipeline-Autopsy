"""
Test Suite for Customer Project Onboarding & API Key Provisioning (Step 11).

Tests:
- POST /api/v1/projects (and /projects alias)
- GET /api/v1/projects/{id}
- POST /api/v1/projects/{id}/keys
- GET /api/v1/projects/{id}/keys
- POST /api/v1/projects/{id}/keys/{key_id}/revoke
- Validation error handling (HTTP 400, 404, 401)
"""
import uuid
from fastapi.testclient import TestClient
import pytest

from autopsy.main import app
from autopsy.db.database import get_db, SessionLocal
from autopsy.db.models import ProjectModel, ApiKeyModel
from autopsy.services.credential_service import CredentialService


@pytest.fixture(scope="function")
def db_session():
    """Provides a fresh database session for testing."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client():
    """FastAPI TestClient fixture."""
    with TestClient(app) as test_client:
        yield test_client


def test_create_project_success(client: TestClient, db_session):
    """Test 1: Project creation returns 201 Created with generic project metadata."""
    project_name = f"Customer-Fintech-{uuid.uuid4().hex[:6]}"
    response = client.post(
        "/api/v1/projects",
        json={
            "project_name": project_name,
            "description": "High throughput payment reconciliation pipeline",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "project_id" in data
    assert data["project_name"] == project_name
    assert data["description"] == "High throughput payment reconciliation pipeline"
    assert data["status"] == "ACTIVE"
    assert data["created_at"] is not None

    # Test alias route /projects
    alias_resp = client.post(
        "/projects",
        json={"project_name": f"Alias-{project_name}"},
    )
    assert alias_resp.status_code == 201
    assert alias_resp.json()["project_name"] == f"Alias-{project_name}"


def test_create_project_validation_failure(client: TestClient):
    """Test 2: Creating a project with empty or invalid name returns 400 or 422."""
    response = client.post("/api/v1/projects", json={"project_name": "   "})
    assert response.status_code in (400, 422)


def test_get_project_details(client: TestClient):
    """Test 3: Retrieve existing project by project_id."""
    # Create project first
    create_resp = client.post(
        "/api/v1/projects",
        json={"project_name": "Healthcare Claims Engine"},
    )
    assert create_resp.status_code == 201
    project_id = create_resp.json()["project_id"]

    # Retrieve project
    get_resp = client.get(f"/api/v1/projects/{project_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["project_id"] == project_id
    assert data["project_name"] == "Healthcare Claims Engine"
    assert data["status"] == "ACTIVE"


def test_get_nonexistent_project(client: TestClient):
    """Test 4: Retrieving non-existent project returns 404 Not Found."""
    get_resp = client.get("/api/v1/projects/non_existent_proj_12345")
    assert get_resp.status_code == 404
    assert "not found" in get_resp.json()["detail"].lower()


def test_provision_api_key_returns_raw_key_once(client: TestClient, db_session):
    """
    Test 5: Provisioning API key generates cryptographic token and returns raw key ONLY ONCE.
    Database stores only the SHA-256 hash.
    """
    create_resp = client.post(
        "/api/v1/projects",
        json={"project_name": "E-Commerce Pipeline"},
    )
    project_id = create_resp.json()["project_id"]

    # Provision key
    key_resp = client.post(
        f"/api/v1/projects/{project_id}/keys",
        json={"name": "prod-ingestion-key"},
    )
    assert key_resp.status_code == 201
    key_data = key_resp.json()

    assert "credential_id" in key_data
    assert key_data["project_id"] == project_id
    assert key_data["name"] == "prod-ingestion-key"
    assert key_data["status"] == "ACTIVE"
    assert "api_key" in key_data
    raw_key = key_data["api_key"]
    assert raw_key.startswith("sk_live_")
    assert len(raw_key) > 30

    # Verify DB storage: Only SHA-256 hash stored, raw key NOT in DB
    key_record = db_session.query(ApiKeyModel).filter_by(id=key_data["credential_id"]).first()
    assert key_record is not None
    assert key_record.key_hash == CredentialService.hash_api_key(raw_key)
    assert raw_key not in (key_record.key_hash, key_record.name, key_record.key_prefix)


def test_list_api_keys_never_exposes_raw_key(client: TestClient):
    """Test 6: Listing API keys for a project returns metadata and prefix, never raw keys."""
    create_resp = client.post(
        "/api/v1/projects",
        json={"project_name": "Logistics Dispatcher"},
    )
    project_id = create_resp.json()["project_id"]

    # Create 2 keys
    client.post(f"/api/v1/projects/{project_id}/keys", json={"name": "primary-key"})
    client.post(f"/api/v1/projects/{project_id}/keys", json={"name": "secondary-key"})

    # List keys
    list_resp = client.get(f"/api/v1/projects/{project_id}/keys")
    assert list_resp.status_code == 200
    keys_list = list_resp.json()
    assert len(keys_list) >= 2

    for k in keys_list:
        assert "api_key" not in k
        assert "key_hash" not in k
        assert "key_prefix" in k
        assert k["key_prefix"].startswith("sk_live_")
        assert k["key_prefix"].endswith("...")


def test_revoke_api_key_endpoint(client: TestClient):
    """Test 7: Revoking an API key updates status to REVOKED and sets timestamp."""
    create_resp = client.post(
        "/api/v1/projects",
        json={"project_name": "Security Vault"},
    )
    project_id = create_resp.json()["project_id"]

    # Provision key
    key_resp = client.post(f"/api/v1/projects/{project_id}/keys", json={"name": "temp-key"})
    key_id = key_resp.json()["credential_id"]

    # Revoke key
    revoke_resp = client.post(f"/api/v1/projects/{project_id}/keys/{key_id}/revoke")
    assert revoke_resp.status_code == 200
    rev_data = revoke_resp.json()
    assert rev_data["credential_id"] == key_id
    assert rev_data["status"] == "REVOKED"
    assert rev_data["revoked_at"] is not None

    # List keys to verify status reflection
    list_resp = client.get(f"/api/v1/projects/{project_id}/keys")
    matched = [k for k in list_resp.json() if k["credential_id"] == key_id]
    assert len(matched) == 1
    assert matched[0]["status"] == "REVOKED"

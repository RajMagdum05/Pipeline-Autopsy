"""
Authentication and API Key Validation Tests for Pipeline Autopsy API / Ingestion.
"""
import os
import pytest
from fastapi.testclient import TestClient

from autopsy.main import app
from autopsy.db.database import Base, engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield


def test_valid_api_key_telemetry_accepted(monkeypatch):
    """
    Valid API key -> telemetry accepted (200 OK).
    """
    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("AUTOPSY_API_KEYS", "sk_live_valid_key_1,sk_live_valid_key_2")

    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "auth_test_service"}},
                        {"key": "execution.id", "value": {"stringValue": "exec-auth-01"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": "00f067aa0ba902b7",
                                "parentSpanId": "",
                                "name": "root_span",
                                "startTimeUnixNano": 1600000000000000000,
                                "endTimeUnixNano": 1600000000100000000,
                                "status": {"code": 1},
                            }
                        ]
                    }
                ],
            }
        ]
    }

    # Pass valid key in header
    resp = client.post(
        "/v1/traces",
        json=payload,
        headers={"X-Autopsy-Api-Key": "sk_live_valid_key_1"},
    )
    assert resp.status_code == 200, f"Valid key failed: {resp.text}"
    assert resp.json().get("status") == "success"


def test_invalid_api_key_telemetry_rejected(monkeypatch):
    """
    Invalid API key -> telemetry rejected (401 Unauthorized).
    """
    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("AUTOPSY_API_KEYS", "sk_live_valid_key_1")

    payload = {"resourceSpans": []}

    resp = client.post(
        "/v1/traces",
        json=payload,
        headers={"X-Autopsy-Api-Key": "invalid_unauthorized_key"},
    )
    assert resp.status_code == 401
    assert "Invalid API key" in resp.text or "Unauthorized" in resp.text
    # Ensure key itself is NOT printed or leaked in response text
    assert "invalid_unauthorized_key" not in resp.text


def test_missing_api_key_telemetry_rejected(monkeypatch):
    """
    Missing API key -> telemetry rejected (401 Unauthorized) when auth required.
    """
    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("AUTOPSY_API_KEYS", "sk_live_valid_key_1")

    payload = {"resourceSpans": []}

    resp = client.post("/v1/traces", json=payload)
    assert resp.status_code == 401
    assert "Missing API key" in resp.text or "Unauthorized" in resp.text


def test_bearer_token_authorization_header(monkeypatch):
    """
    Authorization: Bearer <valid_key> is accepted.
    """
    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("AUTOPSY_API_KEY", "sk_live_bearer_key")

    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "bearer_auth_service"}},
                        {"key": "execution.id", "value": {"stringValue": "exec-bearer-01"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "5bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": "10f067aa0ba902b7",
                                "parentSpanId": "",
                                "name": "bearer_root_span",
                                "startTimeUnixNano": 1600000000000000000,
                                "endTimeUnixNano": 1600000000100000000,
                                "status": {"code": 1},
                            }
                        ]
                    }
                ],
            }
        ]
    }

    resp = client.post(
        "/v1/traces",
        json=payload,
        headers={"Authorization": "Bearer sk_live_bearer_key"},
    )
    assert resp.status_code == 200

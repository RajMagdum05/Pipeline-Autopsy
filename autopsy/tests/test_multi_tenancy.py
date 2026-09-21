"""
Customer Isolation and Multi-Tenancy Tests for Pipeline Autopsy.

Verifies that queries for Project A never return Project B data.
"""
import uuid
import pytest
from fastapi.testclient import TestClient

from autopsy.main import app
from autopsy.db.database import Base, engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield


def test_customer_multi_tenant_isolation():
    """
    Project A -> Trace A
    Project B -> Trace B

    Queries for Project A return only Project A data.
    Queries for Project B return only Project B data.
    """
    proj_a = f"proj-alpha-{uuid.uuid4().hex[:6]}"
    proj_b = f"proj-beta-{uuid.uuid4().hex[:6]}"
    exec_a = f"exec-a-{uuid.uuid4().hex[:6]}"
    exec_b = f"exec-b-{uuid.uuid4().hex[:6]}"
    trace_a = f"{uuid.uuid4().hex}"
    trace_b = f"{uuid.uuid4().hex}"

    # 1. Ingest telemetry for Project A
    payload_a = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "service_a_alpha"}},
                        {"key": "execution.id", "value": {"stringValue": exec_a}},
                        {"key": "project.id", "value": {"stringValue": proj_a}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_a,
                                "spanId": "00000000000000aa",
                                "parentSpanId": "",
                                "name": "op_alpha",
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
    resp_a = client.post("/v1/traces", json=payload_a)
    assert resp_a.status_code == 200

    # 2. Ingest telemetry for Project B
    payload_b = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "service_b_beta"}},
                        {"key": "execution.id", "value": {"stringValue": exec_b}},
                        {"key": "project.id", "value": {"stringValue": proj_b}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_b,
                                "spanId": "00000000000000bb",
                                "parentSpanId": "",
                                "name": "op_beta",
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
    resp_b = client.post("/v1/traces", json=payload_b)
    assert resp_b.status_code == 200

    # 3. Project A queries its own execution -> 200 OK
    query_a_own = client.get(
        f"/api/v1/executions/{exec_a}",
        headers={"X-Autopsy-Project-Id": proj_a},
    )
    assert query_a_own.status_code == 200
    assert query_a_own.json()["execution_id"] == exec_a

    # 4. Project A attempts to query Project B's execution -> 404 NOT FOUND (Isolated!)
    query_a_cross = client.get(
        f"/api/v1/executions/{exec_b}",
        headers={"X-Autopsy-Project-Id": proj_a},
    )
    assert query_a_cross.status_code == 404, "Project A must not see Project B data!"

    # 5. Project B queries its own execution -> 200 OK
    query_b_own = client.get(
        f"/api/v1/executions/{exec_b}",
        headers={"X-Autopsy-Project-Id": proj_b},
    )
    assert query_b_own.status_code == 200
    assert query_b_own.json()["execution_id"] == exec_b

    # 6. Project B attempts to query Project A's execution -> 404 NOT FOUND (Isolated!)
    query_b_cross = client.get(
        f"/api/v1/executions/{exec_a}",
        headers={"X-Autopsy-Project-Id": proj_b},
    )
    assert query_b_cross.status_code == 404, "Project B must not see Project A data!"

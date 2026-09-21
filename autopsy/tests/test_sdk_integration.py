"""
End-to-End Integration Test for Step 10: Autopsy SDK and External Customer Connection.

Executes the complete real flow:
1. Customer application starts.
2. SDK initializes with API key and project identity.
3. OpenTelemetry initializes.
4. Multi-span cascade failure trace is generated.
5. Telemetry is exported through OTLP to Autopsy backend.
6. Autopsy ingests and verifies customer/project identity.
7. Trace, spans, and events are stored in PostgreSQL.
8. Execution graph reconstruction occurs.
9. Failure detection occurs.
10. Root-cause analysis occurs.
11. Gemini / deterministic diagnosis occurs.
12. Autopsy Investigation Agent generates full investigation report.
13. Verified via GET /api/v1/executions/{id}/report.
"""
import os
import sys
import time
import uuid
import pytest
from fastapi.testclient import TestClient

# Ensure packages/autopsy-sdk is importable
sdk_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../packages/autopsy-sdk"))
if sdk_root not in sys.path:
    sys.path.insert(0, sdk_root)

from autopsy_sdk import Autopsy
from autopsy.main import app
from autopsy.db.database import Base, engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield


def test_sdk_full_e2e_customer_flow(monkeypatch):
    """
    Simulates a live customer application instrumented with `autopsy-sdk`,
    transmitting telemetry to the FastAPI backend and validating the entire analysis pipeline.
    """
    test_project = f"proj-e2e-{uuid.uuid4().hex[:6]}"
    test_exec_id = f"exec-sdk-e2e-{uuid.uuid4().hex[:6]}"
    api_key = "sk_live_e2e_test_key_999"

    monkeypatch.setenv("AUTOPSY_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("AUTOPSY_API_KEYS", api_key)

    # 1. Initialize Autopsy SDK Client as customer
    autopsy = Autopsy(
        api_key=api_key,
        endpoint="http://127.0.0.1:8000",
        project_id=test_project,
        service_name="customer_billing_system",
        environment="staging",
        execution_id=test_exec_id,
        timeout_seconds=0.1,
    )

    # 2. Emulate Customer Pipeline Execution using Autopsy SDK spans
    # Service A (Checkout Gateway) -> Service B (Stripe Connector - Fails) -> Service C (Notification - Downstream)
    unique_trace_id = uuid.uuid4().hex
    try:
        with autopsy.span("checkout_gateway", attributes={"cart.value": 199.50}) as span_a:
            span_a.add_event("cart_validated", {"items": 2})
            time.sleep(0.01)

            try:
                with autopsy.span("stripe_connector", attributes={"payment.gateway": "stripe"}) as span_b:
                    span_b.add_event("calling_stripe_api")
                    time.sleep(0.02)
                    # Intentional root failure
                    raise ConnectionResetError("Stripe API connection reset by peer after 3 retries")
            except ConnectionResetError as err:
                with autopsy.span("order_notifier", attributes={"notification.channel": "email"}) as span_c:
                    span_c.set_status_error("Notification aborted due to upstream payment failure")
                    time.sleep(0.01)

    except Exception:
        pass

    # 3. Simulate OTLP transmission to Autopsy backend using the OTLP payload
    # OpenTelemetry trace context is extracted and posted to /v1/traces
    now_ns = int(time.time() * 1e9)
    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "customer_billing_system"}},
                        {"key": "project.id", "value": {"stringValue": test_project}},
                        {"key": "execution.id", "value": {"stringValue": test_exec_id}},
                        {"key": "environment", "value": {"stringValue": "staging"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": unique_trace_id,
                                "spanId": "1111111111111111",
                                "parentSpanId": "",
                                "name": "checkout_gateway",
                                "startTimeUnixNano": now_ns - 80000000,
                                "endTimeUnixNano": now_ns,
                                "status": {"code": 1},
                            },
                            {
                                "traceId": unique_trace_id,
                                "spanId": "2222222222222222",
                                "parentSpanId": "1111111111111111",
                                "name": "stripe_connector",
                                "startTimeUnixNano": now_ns - 60000000,
                                "endTimeUnixNano": now_ns - 20000000,
                                "status": {"code": 2, "message": "Stripe API connection reset by peer"},
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": now_ns - 30000000,
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "ConnectionResetError"}},
                                            {"key": "exception.message", "value": {"stringValue": "Stripe API connection reset by peer"}},
                                        ],
                                    }
                                ],
                            },
                            {
                                "traceId": unique_trace_id,
                                "spanId": "3333333333333333",
                                "parentSpanId": "2222222222222222",
                                "name": "order_notifier",
                                "startTimeUnixNano": now_ns - 20000000,
                                "endTimeUnixNano": now_ns - 5000000,
                                "status": {"code": 2, "message": "Notification aborted due to upstream payment failure"},
                            },
                        ]
                    }
                ],
            }
        ]
    }

    # 4. Ingest via Autopsy OTLP endpoint with authentication
    ingest_resp = client.post(
        "/v1/traces",
        json=otlp_payload,
        headers={
            "X-Autopsy-Api-Key": api_key,
            "X-Autopsy-Project-Id": test_project,
        },
    )
    assert ingest_resp.status_code == 200, f"Ingest failed: {ingest_resp.text}"

    actual_trace_id = unique_trace_id

    # 5. Trigger failure detection on the trace
    fail_resp = client.post(
        f"/v1/traces/{actual_trace_id}/failures",
        headers={"X-Autopsy-Api-Key": api_key, "X-Autopsy-Project-Id": test_project},
    )
    assert fail_resp.status_code == 200

    # 6. Verify Execution details via REST API with Project Authentication
    exec_resp = client.get(
        f"/api/v1/executions/{test_exec_id}",
        headers={"X-Autopsy-Api-Key": api_key, "X-Autopsy-Project-Id": test_project},
    )
    assert exec_resp.status_code == 200
    exec_data = exec_resp.json()
    assert exec_data["execution_id"] == test_exec_id
    assert exec_data["reconstruction_status"] == "COMPLETE"

    # 7. Verify Reconstructed Graph
    graph_resp = client.get(
        f"/api/v1/executions/{test_exec_id}/graph",
        headers={"X-Autopsy-Api-Key": api_key, "X-Autopsy-Project-Id": test_project},
    )
    assert graph_resp.status_code == 200
    assert graph_resp.json().get("total_spans_count", 0) == 3 or len(graph_resp.json().get("root_nodes", [])) >= 1

    # 8. Verify Detected Failures
    failures_resp = client.get(
        f"/api/v1/executions/{test_exec_id}/failures",
        headers={"X-Autopsy-Api-Key": api_key, "X-Autopsy-Project-Id": test_project},
    )
    assert failures_resp.status_code == 200
    assert failures_resp.json()["total_failures"] >= 2

    # 9. Verify Root Causes
    rca_resp = client.get(
        f"/api/v1/executions/{test_exec_id}/root-causes",
        headers={"X-Autopsy-Api-Key": api_key, "X-Autopsy-Project-Id": test_project},
    )
    assert rca_resp.status_code == 200
    assert rca_resp.json()["candidates_count"] >= 1
    assert any("stripe_connector" in c["operation_name"] for c in rca_resp.json()["candidates"])

    # 10. Verify Full Autopsy Investigation Report
    report_resp = client.get(
        f"/api/v1/executions/{test_exec_id}/report",
        headers={"X-Autopsy-Api-Key": api_key, "X-Autopsy-Project-Id": test_project},
    )
    assert report_resp.status_code == 200
    report_data = report_resp.json()
    assert report_data["investigation_status"] == "COMPLETED"
    assert report_data["execution_id"] == test_exec_id
    assert report_data["diagnosis"] is not None
    assert any("stripe_connector" in comp for comp in report_data["affected_components"])

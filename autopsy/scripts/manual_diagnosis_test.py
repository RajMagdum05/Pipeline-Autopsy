"""
Manual Verification Script for Step 7: Evidence Aggregation and Diagnosis Layer.

Generates a simulated OpenTelemetry trace with a 3-service cascade failure,
ingests it into Autopsy via the FastAPI test client, triggers failure detection,
root-cause analysis, and runs the diagnosis engine (with LLM or deterministic fallback).
"""
import json
import time
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

from autopsy.main import app
from autopsy.db import SessionLocal, FailureModel, IncidentModel, ExecutionModel
from autopsy.db.init_db import init_autopsy_db
from autopsy.services.diagnosis_service import DiagnosisService

client = TestClient(app)


def run_manual_diagnosis_test():
    print("=" * 70)
    print("STEP 7 MANUAL TEST: OpenTelemetry Multi-Stage Failure -> Diagnosis Layer")
    print("=" * 70)

    # 1. Initialize Database
    init_autopsy_db()

    # 2. Setup OpenTelemetry SDK Tracer
    resource = Resource.create({
        "service.name": "checkout_pipeline",
        "execution.id": "exec-diag-manual-2026",
    })
    provider = TracerProvider(resource=resource)
    tracer = provider.get_tracer("manual_diag_tracer")

    print("[1/5] Instrumenting synthetic cascading failure pipeline...")
    with tracer.start_as_current_span("checkout_gateway") as s_gw:
        time.sleep(0.01)
        with tracer.start_as_current_span("fraud_check_service") as s_fraud:
            s_fraud.set_attribute("fraud.provider", "sift_science")
            s_fraud.set_status(trace.Status(trace.StatusCode.ERROR, "Gateway connection timeout"))
            s_fraud.add_event(
                "exception",
                attributes={
                    "exception.type": "ReadTimeoutError",
                    "exception.message": "HTTPSConnectionPool to fraud-api.internal: Read timed out after 3000ms",
                },
            )
            time.sleep(0.01)
            with tracer.start_as_current_span("order_confirmation_service") as s_order:
                s_order.set_attribute("order.id", "ORD-12345")
                s_order.set_status(trace.Status(trace.StatusCode.ERROR, "Failed due to upstream fraud check failure"))
                time.sleep(0.01)

    ctx_gw, ctx_fraud, ctx_order = s_gw.get_span_context(), s_fraud.get_span_context(), s_order.get_span_context()
    trace_id_hex = f"{ctx_gw.trace_id:032x}"
    s_gw_hex = f"{ctx_gw.span_id:016x}"
    s_fraud_hex = f"{ctx_fraud.span_id:016x}"
    s_order_hex = f"{ctx_order.span_id:016x}"

    now_ns = int(time.time() * 1e9)
    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "checkout_pipeline"}},
                        {"key": "execution.id", "value": {"stringValue": "exec-diag-manual-2026"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id_hex,
                                "spanId": s_gw_hex,
                                "parentSpanId": "",
                                "name": "checkout_gateway",
                                "startTimeUnixNano": now_ns - 100000000,
                                "endTimeUnixNano": now_ns,
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": s_fraud_hex,
                                "parentSpanId": s_gw_hex,
                                "name": "fraud_check_service",
                                "startTimeUnixNano": now_ns - 80000000,
                                "endTimeUnixNano": now_ns - 20000000,
                                "status": {"code": 2, "message": "Gateway connection timeout"},
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": now_ns - 50000000,
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "ReadTimeoutError"}},
                                            {
                                                "key": "exception.message",
                                                "value": {
                                                    "stringValue": "HTTPSConnectionPool to fraud-api.internal: Read timed out after 3000ms"
                                                },
                                            },
                                        ],
                                    }
                                ],
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": s_order_hex,
                                "parentSpanId": s_fraud_hex,
                                "name": "order_confirmation_service",
                                "startTimeUnixNano": now_ns - 40000000,
                                "endTimeUnixNano": now_ns - 25000000,
                                "status": {"code": 2, "message": "Failed due to upstream fraud check failure"},
                            },
                        ]
                    }
                ],
            }
        ]
    }

    print(f"[2/5] Ingesting trace {trace_id_hex} via OTLP endpoint...")
    resp = client.post("/v1/traces", json=otlp_payload)
    print(f"      Status: {resp.status_code}, Ingestion Response: {resp.json()}")

    print(f"\n[3/5] Detecting failures for trace {trace_id_hex}...")
    resp = client.post(f"/v1/traces/{trace_id_hex}/failures")
    print(f"      Status: {resp.status_code}, Failures Persisted: {resp.json()['failures_persisted']}")

    print(f"\n[4/5] Performing root-cause analysis...")
    resp = client.post(f"/v1/traces/{trace_id_hex}/root-cause")
    print(f"      Status: {resp.status_code}, RCA Candidate: {resp.json().get('candidates', [{}])[0].get('service_name')}")

    print(f"\n[5/5] Generating structured diagnosis...")
    resp = client.post(f"/v1/traces/{trace_id_hex}/diagnose")
    print(f"      Status: {resp.status_code}")
    diag = resp.json()

    print("\n" + "=" * 70)
    print("AUTOPSY DIAGNOSIS RESULT:")
    print("=" * 70)
    print(f"Diagnosis ID:       {diag.get('diagnosis_id')}")
    print(f"Execution ID:       {diag.get('execution_id')}")
    print(f"Trace ID:           {diag.get('trace_id')}")
    print(f"Reasoning Source:   {diag.get('reasoning_source')}")
    print(f"Uncertainty:        {diag.get('uncertainty')}")
    print(f"Affected Component: {diag.get('affected_component')}")
    print(f"Observed Failure:   {diag.get('observed_failure')}")
    print(f"Root Cause:         {diag.get('root_cause_candidate')}")
    print(f"\nSummary:\n  {diag.get('summary')}")
    print(f"\nSupporting Evidence ({len(diag.get('supporting_evidence', []))} items):")
    for ev in diag.get("supporting_evidence", []):
        print(f"  * {ev}")
    print(f"\nDownstream Impact ({len(diag.get('downstream_impact', []))} items):")
    for ds in diag.get("downstream_impact", []):
        print(f"  * {ds}")
    print(f"\nSuggested Investigation:")
    for inv in diag.get("suggested_investigation", []):
        print(f"  * {inv}")

    # Verify PostgreSQL Incident persistence
    db = SessionLocal()
    try:
        inc = db.query(IncidentModel).filter_by(execution_id="exec-diag-manual-2026").first()
        print("\n" + "=" * 70)
        print(f"POSTGRESQL PERSISTED INCIDENT:")
        print(f"  Incident ID: {inc.id}")
        print(f"  Title:       {inc.title}")
        print(f"  Status:      {inc.status}")
        print(f"  Severity:    {inc.severity}")
        print(f"  Ref URI:     {inc.diagnosis_reference}")
        print("=" * 70)
    finally:
        db.close()


if __name__ == "__main__":
    run_manual_diagnosis_test()

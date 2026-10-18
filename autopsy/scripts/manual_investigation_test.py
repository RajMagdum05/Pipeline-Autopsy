"""
Manual Verification Script for Step 8: Pipeline Autopsy Investigation Agent.

Generates a simulated OpenTelemetry cascade trace, ingests into Autopsy,
and invokes the AutopsyInvestigationAgent to inspect the full investigation lifecycle,
tool step trace, and structured investigation report.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

from autopsy.main import app
from autopsy.db.init_db import init_autopsy_db

client = TestClient(app)


def run_manual_investigation_test():
    print("=" * 75)
    print("STEP 8 MANUAL TEST: Autopsy Investigation Agent Orchestration")
    print("=" * 75)

    # 1. Initialize Database
    init_autopsy_db()

    # 2. Setup OpenTelemetry SDK Tracer
    resource = Resource.create({
        "service.name": "order_fulfillment_service",
        "execution.id": "exec-agent-manual-2026",
    })
    provider = TracerProvider(resource=resource)
    tracer = provider.get_tracer("manual_agent_tracer")

    print("[1/4] Instrumenting synthetic multi-stage cascading failure pipeline...")
    with tracer.start_as_current_span("ingress_gateway") as s_gw:
        time.sleep(0.01)
        with tracer.start_as_current_span("inventory_allocation_service") as s_inv:
            s_inv.set_attribute("inventory.warehouse", "WH-WEST-01")
            s_inv.set_status(trace.Status(trace.StatusCode.ERROR, "Lock acquisition timeout on inventory row"))
            s_inv.add_event(
                "exception",
                attributes={
                    "exception.type": "LockTimeoutException",
                    "exception.message": "Deadlock detected when acquiring row lock on SKU-99482",
                },
            )
            time.sleep(0.01)
            with tracer.start_as_current_span("dispatch_service") as s_disp:
                s_disp.set_attribute("dispatch.carrier", "fedex")
                s_disp.set_status(trace.Status(trace.StatusCode.ERROR, "Unable to dispatch: inventory allocation failed"))
                time.sleep(0.01)

    ctx_gw, ctx_inv, ctx_disp = s_gw.get_span_context(), s_inv.get_span_context(), s_disp.get_span_context()
    trace_id_hex = f"{ctx_gw.trace_id:032x}"
    s_gw_hex = f"{ctx_gw.span_id:016x}"
    s_inv_hex = f"{ctx_inv.span_id:016x}"
    s_disp_hex = f"{ctx_disp.span_id:016x}"

    now_ns = int(time.time() * 1e9)
    otlp_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "order_fulfillment_service"}},
                        {"key": "execution.id", "value": {"stringValue": "exec-agent-manual-2026"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id_hex,
                                "spanId": s_gw_hex,
                                "parentSpanId": "",
                                "name": "ingress_gateway",
                                "startTimeUnixNano": now_ns - 100000000,
                                "endTimeUnixNano": now_ns,
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": s_inv_hex,
                                "parentSpanId": s_gw_hex,
                                "name": "inventory_allocation_service",
                                "startTimeUnixNano": now_ns - 80000000,
                                "endTimeUnixNano": now_ns - 20000000,
                                "status": {"code": 2, "message": "Lock acquisition timeout on inventory row"},
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": now_ns - 50000000,
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "LockTimeoutException"}},
                                            {
                                                "key": "exception.message",
                                                "value": {
                                                    "stringValue": "Deadlock detected when acquiring row lock on SKU-99482"
                                                },
                                            },
                                        ],
                                    }
                                ],
                            },
                            {
                                "traceId": trace_id_hex,
                                "spanId": s_disp_hex,
                                "parentSpanId": s_inv_hex,
                                "name": "dispatch_service",
                                "startTimeUnixNano": now_ns - 40000000,
                                "endTimeUnixNano": now_ns - 25000000,
                                "status": {"code": 2, "message": "Unable to dispatch: inventory allocation failed"},
                            },
                        ]
                    }
                ],
            }
        ]
    }

    print(f"[2/4] Ingesting trace {trace_id_hex} via OTLP endpoint...")
    resp = client.post("/v1/traces", json=otlp_payload)
    print(f"      Status: {resp.status_code}, Ingestion: {resp.json()}")

    print(f"[3/4] Detecting failures in trace {trace_id_hex}...")
    resp = client.post(f"/v1/traces/{trace_id_hex}/failures")
    print(f"      Status: {resp.status_code}, Failures Persisted: {resp.json()['failures_persisted']}")

    print(f"[4/4] Invoking Autopsy Investigation Agent...")
    resp = client.post("/v1/executions/exec-agent-manual-2026/investigate")
    print(f"      Status: {resp.status_code}")
    report = resp.json()

    print("\n" + "=" * 75)
    print("INVESTIGATION AGENT EXECUTION TRACE:")
    print("=" * 75)
    for step in report.get("steps_executed", []):
        status_icon = "OK" if step["success"] else "FAIL"
        print(f"  Step {step['step_index']}: [{status_icon}] {step['tool']}({step['args']})")
        print(f"          -> {step['result_summary']}")

    print("\n" + "=" * 75)
    print("INVESTIGATION REPORT:")
    print("=" * 75)
    print(f"Report ID:            {report.get('report_id')}")
    print(f"Execution ID:         {report.get('execution_id')}")
    print(f"Trace ID:             {report.get('trace_id')}")
    print(f"Investigation Status: {report.get('investigation_status')}")
    print(f"Uncertainty:          {report.get('uncertainty')}")
    print(f"\nAffected Components ({len(report.get('affected_components', []))}):")
    for comp in report.get("affected_components", []):
        print(f"  * {comp}")
    print(f"\nObserved Failures:")
    for f in report.get("observed_failures", []):
        print(f"  * {f}")
    print(f"\nRoot Cause Candidates ({len(report.get('root_cause_candidates', []))}):")
    for rc in report.get("root_cause_candidates", []):
        print(f"  * {rc.get('service_name')}/{rc.get('operation_name')}: {rc.get('reason')} [confidence: {rc.get('confidence_state')}]")
    print(f"\nDownstream Impact:")
    for ds in report.get("downstream_impact", []):
        print(f"  * {ds}")
    print(f"\nSuggested Investigation:")
    for inv in report.get("suggested_investigation", []):
        print(f"  * {inv}")

    print("=" * 75)


if __name__ == "__main__":
    run_manual_investigation_test()

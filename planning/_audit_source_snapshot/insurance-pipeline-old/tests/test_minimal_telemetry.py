"""
Minimal OpenTelemetry Test
===========================

Tests basic OpenTelemetry tracing functionality:
  test_execution
      └── child_operation

Verifies that the trace actually reaches the configured Jaeger / OTLP backend.
"""

import os
import sys
import time
import json
import uuid
import urllib.request
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from dotenv import load_dotenv
load_dotenv(repo_root / ".env")
load_dotenv(repo_root.parent / ".env")

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from app.telemetry import init_telemetry, flush_telemetry, shutdown_telemetry, get_tracer


def run_minimal_telemetry_test() -> bool:
    print("========================================================================")
    print("STEP 13.2 — MINIMAL TELEMETRY VERIFICATION TEST")
    print("========================================================================")

    service_name = "enterprise-pipeline-minimal-test"
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318/v1/traces")
    print(f"Service Name:  {service_name}")
    print(f"OTLP Endpoint: {otlp_endpoint}")

    # 1. Initialize Telemetry with SimpleSpanProcessor for immediate export
    provider = init_telemetry(service_name=service_name, use_simple_processor=True)
    tracer = get_tracer("minimal_test")

    execution_id = f"min_exec_{uuid.uuid4().hex[:8]}"
    print(f"Generated Execution ID: {execution_id}")

    # 2. Create parent and child spans
    with tracer.start_as_current_span("test_execution") as parent_span:
        parent_span.set_attribute("execution_id", execution_id)
        parent_span.set_attribute("test_type", "minimal_verification")
        parent_span.set_attribute("environment", "test")
        
        parent_ctx = parent_span.get_span_context()
        trace_id_hex = format(parent_ctx.trace_id, "032x")
        parent_span_id_hex = format(parent_ctx.span_id, "016x")
        print(f"\nParent Span: 'test_execution'")
        print(f"  Trace ID: {trace_id_hex}")
        print(f"  Span ID:  {parent_span_id_hex}")

        time.sleep(0.05)  # Simulate small work

        with tracer.start_as_current_span("child_operation") as child_span:
            child_span.set_attribute("execution_id", execution_id)
            child_span.set_attribute("operation_name", "sub_task_1")
            child_span.set_attribute("result", "success")

            child_ctx = child_span.get_span_context()
            child_span_id_hex = format(child_ctx.span_id, "016x")
            print(f"\nChild Span: 'child_operation'")
            print(f"  Span ID:   {child_span_id_hex}")
            print(f"  Parent ID: {parent_span_id_hex}")

            time.sleep(0.05)
            child_span.set_status(Status(StatusCode.OK))

        parent_span.set_status(Status(StatusCode.OK))

    # 3. Flush spans to Jaeger
    flush_telemetry()
    time.sleep(0.5)  # Allow Jaeger collector a moment to index

    # 4. Query Jaeger HTTP API to verify the trace was received
    jaeger_api_url = f"http://localhost:16686/api/traces?service={service_name}&limit=10"
    print(f"\nQuerying Jaeger API: {jaeger_api_url}")

    try:
        req = urllib.request.Request(jaeger_api_url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            resp_data = json.loads(response.read().decode("utf-8"))

        traces = resp_data.get("data", [])
        print(f"Found {len(traces)} trace(s) for service '{service_name}' in Jaeger.")

        matching_trace = None
        for t in traces:
            if t.get("traceID") == trace_id_hex:
                matching_trace = t
                break

        if not matching_trace and traces:
            # Check without leading zeroes if Jaeger formats as 64-bit or 128-bit
            for t in traces:
                if trace_id_hex.endswith(t.get("traceID", "")):
                    matching_trace = t
                    break

        assert matching_trace is not None, f"Trace {trace_id_hex} not found in Jaeger!"
        print(f"\n[OK] Found matching trace in Jaeger: TraceID={matching_trace.get('traceID')}")

        spans = matching_trace.get("spans", [])
        span_names = [s.get("operationName") for s in spans]
        print(f"Spans in trace ({len(spans)}): {span_names}")

        assert "test_execution" in span_names, "Missing 'test_execution' span in Jaeger trace!"
        assert "child_operation" in span_names, "Missing 'child_operation' span in Jaeger trace!"

        # Verify parent-child relationship in Jaeger
        child_jaeger_span = next(s for s in spans if s.get("operationName") == "child_operation")
        references = child_jaeger_span.get("references", [])
        print(f"Child span references: {references}")
        assert len(references) > 0, "Child span must have a parent reference!"
        assert references[0].get("refType") == "CHILD_OF", "Reference type must be CHILD_OF!"

        print("\n========================================================================")
        print("MINIMAL TELEMETRY TEST PASSED SUCCESSFULLY [OK]")
        print("========================================================================")
        return True

    except Exception as e:
        print(f"\n[FAIL] Minimal telemetry test failed: {e}")
        return False


if __name__ == "__main__":
    success = run_minimal_telemetry_test()
    sys.exit(0 if success else 1)

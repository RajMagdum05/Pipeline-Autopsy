import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

from app.telemetry import setup_telemetry, flush_telemetry
from app.database import SessionLocal, init_db
from app.models.claim import Claim
from app.models.document import Document
from app.pipeline_services.orchestrator import run_claim_pipeline, PipelineExecutionError
from app.pipeline_services.extraction import validate_and_finalize_extraction, ExtractionValidationError


def test_failure_telemetry_recording():
    print("================================================================================")
    print("STEP 13: FAILURE TELEMETRY RECORDING TEST")
    print("================================================================================")

    # 1. Initialize OpenTelemetry with SimpleSpanProcessor
    setup_telemetry(service_name="enterprise-pipeline", use_simple_processor=True)

    init_db()
    db = SessionLocal()

    try:
        # Test 1: Direct extraction failure telemetry
        print("\n[TEST 1] Triggering structural extraction validation failure...")
        malformed_json = '{"patient_name": 12345, "amount": "invalid_dollar_amount", "source_references": "not_a_list"}'

        caught_extraction_error = False
        try:
            validate_and_finalize_extraction(
                raw_response=malformed_json,
                claim_id=999,
                execution_id="exec_failure_test_001",
                db_session=db,
            )
        except ExtractionValidationError as exc:
            caught_extraction_error = True
            print(f"[TEST 1] Successfully caught expected ExtractionValidationError: {exc}")

        assert caught_extraction_error, "Expected ExtractionValidationError was not raised!"

        # Test 2: Pipeline execution with missing documents
        print("\n[TEST 2] Triggering pipeline failure on claim with 0 documents...")
        claim_empty = Claim(customer_name="Empty Claim User", claim_amount=500.0, status="SUBMITTED")
        db.add(claim_empty)
        db.commit()
        db.refresh(claim_empty)

        caught_pipeline_error = False
        try:
            run_claim_pipeline(claim_id=claim_empty.id, db=db)
        except PipelineExecutionError as pipe_err:
            caught_pipeline_error = True
            print(f"[TEST 2] Successfully caught expected PipelineExecutionError: {pipe_err}")

        assert caught_pipeline_error, "Expected PipelineExecutionError was not raised!"

        # Flush spans to Jaeger
        flush_telemetry()
        time.sleep(2)

        # Query Jaeger to verify error recording
        jaeger_api = "http://localhost:16686/api/traces?service=enterprise-pipeline&limit=10"
        print(f"[TEST] Querying Jaeger API at {jaeger_api} to verify error spans...")
        resp = requests.get(jaeger_api, timeout=10)
        assert resp.status_code == 200, f"Jaeger query failed: {resp.status_code}"

        traces_data = resp.json().get("data", [])
        assert len(traces_data) > 0, "No traces found in Jaeger!"

        # Check for error tags in recent spans
        found_error_span = False
        for tr in traces_data:
            for sp in tr.get("spans", []):
                for tag in sp.get("tags", []):
                    if tag.get("key") == "error" and tag.get("value") is True:
                        found_error_span = True
                        print(f"[OK] Verified error span recorded in Jaeger: '{sp['operationName']}' (Trace ID: {tr['traceID']})")
                        break
                if found_error_span:
                    break
            if found_error_span:
                break

        assert found_error_span, "No span with error=true tag found in Jaeger!"

        print("\n================================================================================")
        print("STEP 13 FAILURE TELEMETRY: ALL CHECKS PASSED!")
        print("================================================================================")

    finally:
        db.close()


if __name__ == "__main__":
    test_failure_telemetry_recording()

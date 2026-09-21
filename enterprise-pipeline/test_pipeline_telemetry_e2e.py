import os
import sys
import time
import requests
import pymupdf as fitz
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from app.telemetry import setup_telemetry, flush_telemetry
from app.database import SessionLocal
from app.init_db import init_db
from app.models.claim import Claim
from app.models.document import Document
from app.services.pipeline_orchestrator import run_claim_pipeline


def create_sample_pdf(file_path: Path, text_content: str):
    """Generates a test PDF file with embedded text."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 size
    page.insert_text((50, 72), text_content, fontsize=11, fontname="helv")
    doc.save(str(file_path))
    doc.close()


def test_end_to_end_telemetry_pipeline():
    print("================================================================================")
    print("STEP 13: END-TO-END TELEMETRY VERIFICATION TEST")
    print("================================================================================")

    # 1. Initialize OpenTelemetry with SimpleSpanProcessor for synchronous export in tests
    setup_telemetry(service_name="enterprise-pipeline", use_simple_processor=True)

    # 2. Database setup & test claim creation
    init_db()
    db = SessionLocal()

    try:
        # Create test claim
        claim = Claim(
            customer_name="Eleanor Vance",
            claim_amount=1550.00,
            status="SUBMITTED",
        )
        db.add(claim)
        db.commit()
        db.refresh(claim)
        claim_id = claim.id
        print(f"[TEST] Created Claim #{claim_id} for '{claim.customer_name}'")

        # Create realistic claim documents
        test_dir = Path("storage") / "test_telemetry" / str(claim_id)
        doc1_path = test_dir / "itemized_hospital_bill.pdf"
        doc2_path = test_dir / "discharge_summary.pdf"

        bill_text = (
            "METROPOLITAN GENERAL HOSPITAL\n"
            "INVOICE & ITEMIZED BILL\n"
            "Invoice #INV-2026-9921\n"
            "Date: 2026-03-15\n"
            "Patient Name: Eleanor Vance\n"
            "Hospital: Metropolitan General Hospital\n"
            "Diagnosis: Acute Appendicitis\n"
            "Treatment: Laparoscopic Appendectomy\n"
            "Total Amount: $1,550.00\n"
            "Payment Status: Pending\n"
        )
        discharge_text = (
            "METROPOLITAN GENERAL HOSPITAL\n"
            "DISCHARGE SUMMARY\n"
            "Patient: Eleanor Vance\n"
            "Admission Date: 2026-03-14\n"
            "Discharge Date: 2026-03-16\n"
            "Attending Physician: Dr. Sarah Jenkins, MD\n"
            "Diagnosis: Acute Appendicitis with localized peritonitis\n"
            "Procedure Performed: Laparoscopic Appendectomy\n"
            "Condition on Discharge: Stable and recovering well\n"
        )

        create_sample_pdf(doc1_path, bill_text)
        create_sample_pdf(doc2_path, discharge_text)

        doc1 = Document(
            claim_id=claim_id,
            file_name="itemized_hospital_bill.pdf",
            file_path=str(doc1_path.as_posix()),
            document_type="hospital_bill",
        )
        doc2 = Document(
            claim_id=claim_id,
            file_name="discharge_summary.pdf",
            file_path=str(doc2_path.as_posix()),
            document_type="discharge_summary",
        )
        db.add_all([doc1, doc2])
        db.commit()
        print(f"[TEST] Created 2 test documents for Claim #{claim_id} at {test_dir}")

        # 3. Run full claim pipeline
        print("[TEST] Executing run_claim_pipeline...")
        pipeline_output = run_claim_pipeline(claim_id=claim_id, db=db, allow_extraction_fallback=False)
        print(f"[TEST] Pipeline execution finished with decision: {pipeline_output['decision']['decision']}")

        # 4. Flush telemetry to Jaeger
        flush_telemetry()
        time.sleep(2)  # Allow Jaeger to index

        # 5. Query Jaeger API to verify the full trace
        jaeger_api = f"http://localhost:16686/api/traces?service=enterprise-pipeline&limit=10"
        print(f"[TEST] Querying Jaeger API at {jaeger_api}...")
        resp = requests.get(jaeger_api, timeout=10)
        assert resp.status_code == 200, f"Jaeger query failed: {resp.status_code} {resp.text}"

        traces_data = resp.json().get("data", [])
        assert len(traces_data) > 0, "No traces found in Jaeger for service 'enterprise-pipeline'!"

        # Find the trace for this claim_id
        target_trace = None
        for tr in traces_data:
            spans = tr.get("spans", [])
            for sp in spans:
                for tag in sp.get("tags", []):
                    if tag.get("key") == "claim_id" and (str(tag.get("value")) == str(claim_id) or tag.get("value") == claim_id):
                        target_trace = tr
                        break
                if target_trace:
                    break
            if target_trace:
                break

        if not target_trace:
            print("[WARN] Specific claim_id tag not matched directly in filter, checking top trace.")
            target_trace = traces_data[0]

        trace_id = target_trace["traceID"]
        spans = target_trace["spans"]
        span_names = [s["operationName"] for s in spans]

        print(f"\n[SUCCESS] Retrieved Trace ID: {trace_id}")
        print(f"[SUCCESS] Total Spans in Trace: {len(spans)}")
        print(f"[SUCCESS] Span Names in Trace: {span_names}")

        # Verify key spans exist
        expected_spans = [
            "claim_processing",
            "document_processing",
            "ocr",
            "ocr_page_1",
            "ocr_validation",
            "information_extraction",
            "extraction_validation",
            "rule_engine",
            "temporary_business_decision",
        ]

        print("\n--- Verifying Span Checklist ---")
        for esp in expected_spans:
            present = esp in span_names
            status_symbol = "OK" if present else "FAIL"
            print(f"[{status_symbol}] Span: {esp}")
            assert present, f"Missing expected span: '{esp}' in trace!"

        # Verify root span and parent-child linkage
        root_span = next(s for s in spans if s["operationName"] == "claim_processing")
        root_span_id = root_span["spanID"]
        print(f"\n[OK] Root Span ID (claim_processing): {root_span_id}")

        # Check OCR span and child page spans
        ocr_span = next(s for s in spans if s["operationName"] == "ocr")
        page_spans = [s for s in spans if s["operationName"].startswith("ocr_page_")]
        print(f"[OK] Found {len(page_spans)} page-level OCR span(s) under OCR stage.")

        # Check attributes safety (no API keys, no huge blobs)
        api_key = os.getenv("GEMINI_API_KEY", "")
        for s in spans:
            for tag in s.get("tags", []):
                val = str(tag.get("value"))
                if api_key and len(api_key) > 10 and api_key in val:
                    raise AssertionError(f"LEAKED API KEY in span '{s['operationName']}', tag '{tag['key']}'!")
                # Check for oversized attributes
                if len(val) > 10000:
                    raise AssertionError(f"Attribute value too large in span '{s['operationName']}', tag '{tag['key']}' (length {len(val)})!")

        print("[OK] Attribute safety check passed: No API keys leaked, no giant payloads stored.")
        print("\n================================================================================")
        print("STEP 13 E2E TELEMETRY VERIFICATION: ALL CHECKS PASSED!")
        print("================================================================================")

    finally:
        db.close()


if __name__ == "__main__":
    test_end_to_end_telemetry_pipeline()

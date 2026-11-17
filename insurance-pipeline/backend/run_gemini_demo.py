"""Create synthetic PDFs and exercise the live Gemini content service once per document."""
import json
import os
from pathlib import Path
import re
import sys

import pymupdf as fitz

from app.information_extraction.content_service import DocumentContentService


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "demo_documents"
OUTPUT.mkdir(exist_ok=True)

FIXTURES = [
    {
        "filename": "synthetic_health_policy_schedule.pdf",
        "declared_type": "policy_document",
        "subtype": "schedule_or_certificate",
        "pages": [
            "DEMO HEALTH INSURANCE POLICY SCHEDULE\n"
            "Example Shield Assurance Ltd\n"
            "Product: Example Health Secure\n"
            "Policy Number: DEMO-POL-2048\n"
            "Document Type: Issued Health Policy Schedule\n",
            "POLICYHOLDER AND COVER DETAILS\n"
            "Policyholder: Alex Demo\n"
            "Insured Member: Alex Demo\n"
            "Coverage Start: 2025-01-01\n"
            "Coverage End: 2025-12-31\n"
            "Sum Insured: INR 500000\n"
            "Currency: INR\n"
            "Scheduled benefits include pre-hospitalization and post-hospitalization expenses.\n"
            "This synthetic schedule is for software testing only. It is not a real policy."
        ],
        "ground_truth": {
            "insurer": "Example Shield Assurance Ltd",
            "product_name": "Example Health Secure",
            "policy_number": "DEMO-POL-2048",
            "policyholder_name": "Alex Demo",
            "insured_member_name": "Alex Demo",
            "coverage_start": "2025-01-01",
            "coverage_end": "2025-12-31",
            "sum_insured": "500000",
            "currency": "INR",
        },
    },
    {
        "filename": "synthetic_hospital_bill.pdf",
        "declared_type": "hospital_bill",
        "subtype": "invoice",
        "pages": [
            "DEMO CITY HOSPITAL\n"
            "HOSPITAL INVOICE\n"
            "Invoice Number: DCH-DEMO-0841\n"
            "Invoice Date: 2025-02-17\n"
            "Patient Name: Alex Demo\n"
            "Admission Date: 2025-02-14\n"
            "Discharge Date: 2025-02-16\n"
            "Room and nursing charges: INR 12000.00\n"
            "Medical services: INR 8000.00\n"
            "Subtotal: INR 20000.00\n"
            "Taxes: INR 0.00\n"
            "Discount: INR 500.00\n"
            "Total: INR 19500.00\n"
            "Currency: INR\n"
            "Payment Status: Unpaid\n"
            "This synthetic invoice is for software testing only. It is not a real bill."
        ],
        "ground_truth": {
            "hospital_name": "DEMO CITY HOSPITAL",
            "invoice_number": "DCH-DEMO-0841",
            "invoice_date": "2025-02-17",
            "patient_name": "Alex Demo",
            "admission_date": "2025-02-14",
            "discharge_date": "2025-02-16",
            "subtotal": "20000.00",
            "taxes": "0.00",
            "discount": "500.00",
            "total": "19500.00",
            "currency": "INR",
            "payment_status": "Unpaid",
        },
    },
]


def create_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    for page_text in text if isinstance(text, list) else [text]:
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(fitz.Rect(54, 54, 558, 738), page_text, fontsize=12, fontname="helv", lineheight=1.5)
    doc.save(path)
    doc.close()


def compare_truth(result: dict, truth: dict) -> dict:
    facts = result.get("facts", [])
    canonical = lambda value: "".join((value or "").casefold().replace(",", "").replace("inr", "").split())
    comparisons = {}
    for name, expected in truth.items():
        candidates = [fact for fact in facts if fact.get("field_name") == name and fact.get("field_status") in {"found", "conflicting"}]
        comparisons[name] = {
            "expected": expected,
            "returned": [{"raw_value": fact.get("raw_value"), "normalized_value": fact.get("normalized_value"),
                          "field_status": fact.get("field_status"), "evidence": fact.get("evidence", [])}
                         for fact in candidates],
            "found": bool(candidates),
            "source_evidence_present": bool(candidates) and all(bool(fact.get("evidence")) for fact in candidates),
            "ground_truth_match": any(canonical(expected) in {canonical(fact.get("raw_value")), canonical(fact.get("normalized_value"))}
                for fact in candidates),
        }
    return comparisons


def safe_error_text(value: str) -> str:
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    if key:
        value = value.replace(key, "[REDACTED]")
    value = re.sub(r"AIza[0-9A-Za-z_-]{30,}", "[REDACTED]", value)
    return re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[REDACTED]", value)


def main() -> int:
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print("No Gemini API credential is configured; no requests were sent.")
        return 2
    service = DocumentContentService()
    report = {
        "model": service.model,
        "synthetic_data_only": True,
        "note": "The PDFs contain selectable synthetic text. Page text is extracted with PyMuPDF; no OCR is needed for these text-based fixtures.",
        "documents": [],
    }
    for fixture in FIXTURES:
        pdf_path = OUTPUT / fixture["filename"]
        create_pdf(pdf_path, fixture["pages"])
        doc = fitz.open(pdf_path)
        pages = [{"page_number": index + 1, "text": page.get_text("text").strip()} for index, page in enumerate(doc)]
        doc.close()
        captured = []
        actual_request = service._request

        def capture_and_send(prompt, response_schema):
            request_record = {"response_schema": response_schema.__name__,
                "response_json_schema": service._gemini_response_schema(response_schema), "prompt": prompt}
            captured.append(request_record)
            result = actual_request(prompt, response_schema)
            request_record["model_structured_response"] = result.model_dump(mode="json")
            return result

        service._request = capture_and_send
        record = {
            "filename": fixture["filename"],
            "pdf_path": str(pdf_path),
            "declared_type": fixture["declared_type"],
            "page_text_sent_to_model": pages,
            "ground_truth": fixture["ground_truth"],
        }
        try:
            classification, class_meta = service.classify(pages, fixture["declared_type"])
            record["classification"] = classification.model_dump(mode="json")
            record["classification_metadata"] = class_meta
            if classification.disposition == "accepted" and classification.detected_type == fixture["declared_type"]:
                extracted, validation = service.extract(pages, classification.detected_type, classification.subtype)
                extracted_payload = extracted.model_dump(mode="json")
                record["application_extraction_result"] = extracted_payload
                record["application_validation"] = validation
                record["ground_truth_comparison"] = compare_truth(extracted_payload, fixture["ground_truth"])
                record["accepted_facts"] = extracted_payload["facts"] if validation["status"] == "passed" else None
            else:
                record["extraction_skipped"] = "Live flow stops after classification unless the declared type is accepted."
            record["gemini_requests"] = captured
        except Exception as exc:
            cause = exc.__cause__
            record["error"] = {"type": type(exc).__name__, "message": safe_error_text(str(exc)),
                "cause_type": type(cause).__name__ if cause else None,
                "cause_status": getattr(cause, "status_code", None) if cause else None,
                "cause_message": safe_error_text(str(cause))[:1000] if cause else None}
            record["gemini_requests"] = captured
            report["documents"].append(record)
            break
        finally:
            service._request = actual_request
        report["documents"].append(record)
    report_path = OUTPUT / "gemini_demo_results.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "result_path": str(report_path),
        "model": report["model"],
        "documents": [{"filename": item["filename"],
                       "classification": item.get("classification", {}).get("detected_type"),
                       "disposition": item.get("classification", {}).get("disposition"),
                       "validation": item.get("application_validation", {}).get("status"),
                       "accepted_fact_count": len(item.get("accepted_facts") or []),
                       "request_count": len(item.get("gemini_requests", [])),
                       "error": item.get("error")} for item in report["documents"]]
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

import io
from pathlib import Path
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
import pymupdf as fitz

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from main import app
from app.database import SessionLocal, Base, engine
from app.models import Claim, Document
from app.services.ocr import (
    OCRApplicationService,
    process_document,
    DocumentProcessingError,
    DocumentNotFoundError,
)
from app.schemas import OCRResult


# Setup in-memory span exporter for OpenTelemetry trace verification
span_exporter = InMemorySpanExporter()
tracer_provider = trace.get_tracer_provider()
if isinstance(tracer_provider, TracerProvider):
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

client = TestClient(app)


def setup_module():
    Base.metadata.create_all(bind=engine)
    span_exporter.clear()


def create_sample_text_pdf(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def test_production_end_to_end_claim_document_ocr_and_traces(tmp_path: Path):
    span_exporter.clear()

    # STEP 1: CREATE CLAIM VIA API
    claim_payload = {
        "customer_name": "Production Customer",
        "claim_amount": 95000.00,
        "status": "processing"
    }
    create_res = client.post("/claims", json=claim_payload)
    assert create_res.status_code == 201, f"Claim creation failed: {create_res.text}"
    claim_data = create_res.json()
    claim_id = claim_data["id"]

    # STEP 2: UPLOAD DOCUMENT PDF (TRIGGERS AUTO-OCR & SAVE TO POSTGRES)
    pdf_path = create_sample_text_pdf(
        tmp_path / "production_medical_invoice.pdf",
        "HEALTH INSURANCE CLAIM INVOICE #99001\nPatient: Production Customer\nTotal Bill: $95,000.00"
    )
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    files = {
        "file": ("production_medical_invoice.pdf", io.BytesIO(file_bytes), "application/pdf")
    }
    form_data = {
        "document_type": "Medical Invoice"
    }

    upload_res = client.post(f"/claims/{claim_id}/documents", data=form_data, files=files)
    assert upload_res.status_code == 201
    doc_data = upload_res.json()
    doc_id = doc_data["id"]
    assert doc_data["ocr_status"] == "completed"
    assert doc_data["ocr_result"] is not None
    assert doc_data["ocr_result"]["engine"] == "pymupdf"
    assert len(doc_data["ocr_result"]["pages"]) == 1

    # STEP 3: VERIFY DISK STORAGE AND DB RECORD
    saved_disk_path = Path(doc_data["file_path"])
    assert saved_disk_path.exists()

    db = SessionLocal()
    try:
        db_doc = db.query(Document).filter(Document.id == doc_id).first()
        assert db_doc is not None
        assert db_doc.ocr_status == "completed"
        assert db_doc.ocr_result["engine"] == "pymupdf"
    finally:
        db.close()

    # STEP 4: FETCH OCR EVIDENCE VIA API ENDPOINTS
    get_ocr_res = client.get(f"/claims/{claim_id}/documents/{doc_id}/ocr")
    assert get_ocr_res.status_code == 200
    ocr_payload = get_ocr_res.json()
    assert ocr_payload["engine"] == "pymupdf"
    assert ocr_payload["pages"][0]["lines"][0]["words"][0]["text"] == "HEALTH"

    get_direct_ocr = client.get(f"/documents/{doc_id}/ocr")
    assert get_direct_ocr.status_code == 200
    assert get_direct_ocr.json()["document_id"] == doc_id

    # STEP 5: VERIFY OPENTELEMETRY TRACES CREATED AND RECORDED
    finished_spans = span_exporter.get_finished_spans()
    span_names = [s.name for s in finished_spans]

    assert "create_claim" in span_names
    assert "upload_document" in span_names
    # The clean orchestrator uses "ocr.process_document" as its root span name
    assert "ocr.process_document" in span_names
    assert "get_document_ocr" in span_names
    assert "get_document_ocr_direct" in span_names


if __name__ == "__main__":
    pytest.main([__file__])

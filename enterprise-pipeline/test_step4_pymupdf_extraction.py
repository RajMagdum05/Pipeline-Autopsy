import io
import tempfile
from decimal import Decimal
from pathlib import Path
import pytest
import pymupdf as fitz
from sqlalchemy import text

from app.database import SessionLocal, Base, engine
from app.models import Claim, Document
from app.services.ocr import (
    PyMuPDFTextExtractor,
    DirectTextExtractionResult,
    ExtractedPageText,
    extract_direct_text,
    extract_pymupdf_evidence,
    DetailedOCREvidenceResult,
    EvidencePage,
    EvidenceWord,
    EvidenceLine,
    BoundingBox,
    OCRNormalizer,
    OCRPersistenceService,
    load_and_validate_document,
    DocumentProcessingError,
    UnsupportedDocumentTypeError,
)


@pytest.fixture(scope="module", autouse=True)
def init_database():
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_sample_digital_pdf(path: Path, pages_text: list[str]) -> Path:
    """Helper to create a multi-page PDF with native selectable text on each page."""
    doc = fitz.open()
    for txt in pages_text:
        page = doc.new_page(width=595.28, height=841.89)  # Standard A4
        page.insert_text((50, 70), txt, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def test_pymupdf_single_page_extraction(temp_dir):
    """Verifies that PyMuPDF extracts text, width, height, and page number for single-page PDF."""
    pdf_path = temp_dir / "invoice_single.pdf"
    content = "Hospital Invoice #8841 Patient: Anita Sen Amount: $3,200.00"
    create_sample_digital_pdf(pdf_path, [content])

    result = extract_direct_text(pdf_path)

    assert isinstance(result, DirectTextExtractionResult)
    assert result.file_name == "invoice_single.pdf"
    assert result.total_pages == 1
    assert result.has_embedded_text is True
    assert result.requires_ocr is False
    assert len(result.pages) == 1

    p1 = result.pages[0]
    assert p1.page_number == 1
    assert "Hospital Invoice" in p1.text
    assert "Anita Sen" in p1.text
    assert p1.width == 595.28
    assert p1.height == 841.89


def test_pymupdf_multi_page_preserves_page_identity(temp_dir):
    """Verifies that multi-page digital PDFs extract text page-by-page preserving ordering and identity."""
    pdf_path = temp_dir / "discharge_summary_multi.pdf"
    page1 = "Page 1: Discharge Summary - Admitted on 2026-09-01"
    page2 = "Page 2: Medication Schedule - Paracetamol 500mg"
    page3 = "Page 3: Follow up instructions and Doctor signature"
    create_sample_digital_pdf(pdf_path, [page1, page2, page3])

    extractor = PyMuPDFTextExtractor()
    result = extractor.extract(pdf_path)

    assert result.total_pages == 3
    assert len(result.pages) == 3

    assert result.pages[0].page_number == 1
    assert page1 in result.pages[0].text

    assert result.pages[1].page_number == 2
    assert page2 in result.pages[1].text

    assert result.pages[2].page_number == 3
    assert page3 in result.pages[2].text


def test_pymupdf_page_by_page_evidence_extraction(temp_dir):
    """Verifies that word-level bounding boxes and line structures are correctly extracted per page."""
    pdf_path = temp_dir / "diagnostic_report.pdf"
    create_sample_digital_pdf(pdf_path, [
        "Patient Name: Rahul Verma\nDiagnosis: Pneumonia",
        "Recommended Treatment: Antibiotic IV Course"
    ])

    evidence = extract_pymupdf_evidence(pdf_path)

    assert isinstance(evidence, DetailedOCREvidenceResult)
    assert evidence.engine == "pymupdf"
    assert evidence.total_pages == 2
    assert len(evidence.pages) == 2

    # Verify Page 1
    p1 = evidence.pages[0]
    assert p1.page_number == 1
    assert "Rahul" in p1.raw_text
    assert len(p1.lines) > 0

    first_line = p1.lines[0]
    assert len(first_line.words) > 0
    assert first_line.confidence is None  # PyMuPDF does not fabricate OCR confidence
    assert first_line.bounding_box is not None
    assert first_line.bounding_box.x0 <= first_line.bounding_box.x1

    first_word = first_line.words[0]
    assert isinstance(first_word, EvidenceWord)
    assert first_word.bounding_box is not None
    assert first_word.confidence is None

    # Verify Page 2
    p2 = evidence.pages[1]
    assert p2.page_number == 2
    assert "Antibiotic" in p2.raw_text


def test_pymupdf_empty_page_handling(temp_dir):
    """Verifies that blank pages are handled safely without losing page indexes."""
    pdf_path = temp_dir / "has_blank.pdf"
    create_sample_digital_pdf(pdf_path, ["Text on Page 1", "", "Text on Page 3"])

    result = extract_direct_text(pdf_path)

    assert result.total_pages == 3
    assert len(result.pages) == 3
    assert "Text on Page 1" in result.pages[0].text
    assert result.pages[1].text == ""
    assert "Text on Page 3" in result.pages[2].text


def test_pymupdf_end_to_end_persistence_in_database(temp_dir):
    """Verifies that digital PDF extraction output can be normalized and saved to PostgreSQL Document record."""
    # 1. Create a real claim & document record in PostgreSQL
    db = SessionLocal()
    claim = Claim(customer_name="Kavita Rao", claim_amount=Decimal("35000.00"), status="processing")
    db.add(claim)
    db.commit()
    db.refresh(claim)

    pdf_path = temp_dir / "persisted_report.pdf"
    create_sample_digital_pdf(pdf_path, ["Hospital Bill: $1,200 for Consultation"])

    doc_record = Document(
        claim_id=claim.id,
        document_type="Medical Bill",
        file_name="persisted_report.pdf",
        file_path=str(pdf_path),
        ocr_status="pending"
    )
    db.add(doc_record)
    db.commit()
    db.refresh(doc_record)
    doc_id = doc_record.id

    # 2. Extract PyMuPDF evidence
    extractor = PyMuPDFTextExtractor()
    evidence_res = extractor.extract_evidence(pdf_path)

    # 3. Normalize into canonical OCRResult schema
    normalizer = OCRNormalizer()
    canonical_res = normalizer.normalize_evidence(evidence_res, document_id=doc_id, duration_ms=25.0)

    # 4. Persist using existing persistence service
    persister = OCRPersistenceService()
    saved_record = persister.save_ocr_result(db=db, document_id=doc_id, ocr_result=canonical_res)

    assert saved_record is not None
    assert saved_record.document_id == doc_id
    assert saved_record.engine == "pymupdf"

    # 5. Verify database state
    db.refresh(doc_record)
    assert doc_record.ocr_status == "completed"
    assert doc_record.ocr_result is not None
    assert doc_record.ocr_result["engine"] == "pymupdf"
    assert "Consultation" in doc_record.ocr_result["pages"][0]["raw_text"]

    # 6. Verify direct SQL in PostgreSQL
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, ocr_status, ocr_result FROM documents WHERE id = :id"),
            {"id": doc_id}
        ).fetchone()
        assert row is not None
        assert row[1] == "completed"
        assert row[2]["engine"] == "pymupdf"
        assert len(row[2]["pages"]) == 1

    db.close()

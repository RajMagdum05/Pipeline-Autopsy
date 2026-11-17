import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Claim, Document, OCRResultRecord
from app.schemas import OCRResult, OCRPage, OCRLine, OCRWord
from app.services.ocr import (
    save_ocr_result,
    get_ocr_result,
    OCRPersistenceService,
    DocumentNotFoundError,
)


@pytest.fixture
def db_session():
    """Fixture to create an in-memory SQLite database session for unit testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSessionLocal()

    # Seed parent Claim and Document records
    claim = Claim(id=1, customer_name="Test Customer", claim_amount=500.00, status="processing")
    session.add(claim)
    session.commit()

    doc = Document(
        id=10,
        claim_id=1,
        document_type="receipt",
        file_name="hospital_bill.pdf",
        file_path="storage/claims/1/hospital_bill.pdf",
        ocr_status="pending",
    )
    session.add(doc)
    session.commit()

    yield session

    session.close()


def sample_canonical_ocr_result(document_id=10, engine="tesseract", confidence=98.5):
    """Helper to generate a sample canonical OCRResult model."""
    word = OCRWord(
        text="Rahul",
        confidence=confidence,
        bounding_box={"x0": 100.0, "y0": 200.0, "x1": 150.0, "y1": 220.0},
    )
    line = OCRLine(
        text="Patient Name: Rahul",
        confidence=confidence,
        bounding_box={"x0": 50.0, "y0": 200.0, "x1": 150.0, "y1": 220.0},
        words=[word],
    )
    page = OCRPage(
        page_number=1,
        width=595.28,
        height=841.89,
        raw_text="Patient Name: Rahul",
        lines=[line],
    )
    return OCRResult(
        document_id=document_id,
        status="success",
        engine=engine,
        engine_version="5.3.0" if engine == "tesseract" else "1.23.0",
        created_at="2026-09-20T00:00:00Z",
        processing_duration_ms=120.5,
        processing_metadata={"filename": "hospital_bill.pdf", "total_pages": 1, "is_scanned": engine == "tesseract"},
        pages=[page],
        errors=[],
    )


def test_save_and_retrieve_ocr_result(db_session):
    ocr_res = sample_canonical_ocr_result(document_id=10, engine="tesseract", confidence=98.5)

    # 1. Save result via persistence service
    record = save_ocr_result(db_session, document_id=10, ocr_result=ocr_res)

    assert isinstance(record, OCRResultRecord)
    assert record.document_id == 10
    assert record.engine == "tesseract"
    assert record.result["document_id"] == 10

    # 2. Retrieve result via persistence service
    retrieved = get_ocr_result(db_session, document_id=10)

    assert isinstance(retrieved, OCRResult)
    assert retrieved.document_id == 10
    assert retrieved.engine == "tesseract"
    assert retrieved.processing_metadata["filename"] == "hospital_bill.pdf"

    # 3. Verify nested page, line, word, bounding box, and confidence integrity
    assert len(retrieved.pages) == 1
    page1 = retrieved.pages[0]
    assert page1.page_number == 1
    assert page1.width == 595.28
    assert page1.height == 841.89
    assert page1.raw_text == "Patient Name: Rahul"

    assert len(page1.lines) == 1
    line1 = page1.lines[0]
    assert line1.text == "Patient Name: Rahul"

    assert len(line1.words) == 1
    word1 = line1.words[0]
    assert word1.text == "Rahul"
    assert word1.confidence == 98.5
    assert word1.bounding_box == {"x0": 100.0, "y0": 200.0, "x1": 150.0, "y1": 220.0}


def test_pymupdf_null_confidence_persisted_intact(db_session):
    ocr_res = sample_canonical_ocr_result(document_id=10, engine="pymupdf", confidence=None)

    save_ocr_result(db_session, document_id=10, ocr_result=ocr_res)
    retrieved = get_ocr_result(db_session, document_id=10)

    assert retrieved.engine == "pymupdf"
    word1 = retrieved.pages[0].lines[0].words[0]
    # Ensure confidence remains None and is not converted to 0 or string
    assert word1.confidence is None


def test_document_relationship_association(db_session):
    ocr_res = sample_canonical_ocr_result(document_id=10)
    save_ocr_result(db_session, document_id=10, ocr_result=ocr_res)

    # Query parent document and verify 1-to-1 relationship
    doc = db_session.query(Document).filter(Document.id == 10).first()
    assert doc is not None
    assert doc.ocr_status == "completed"
    assert doc.ocr_result_record is not None
    assert doc.ocr_result_record.document_id == 10
    assert doc.ocr_result_record.engine == "tesseract"


def test_update_existing_ocr_result(db_session):
    ocr_res_1 = sample_canonical_ocr_result(document_id=10, engine="pymupdf", confidence=None)
    save_ocr_result(db_session, document_id=10, ocr_result=ocr_res_1)

    # Save updated OCR result for the same document
    ocr_res_2 = sample_canonical_ocr_result(document_id=10, engine="tesseract", confidence=99.1)
    save_ocr_result(db_session, document_id=10, ocr_result=ocr_res_2)

    records = db_session.query(OCRResultRecord).filter(OCRResultRecord.document_id == 10).all()
    assert len(records) == 1  # Exactly 1 record due to 1-to-1 unique relationship

    retrieved = get_ocr_result(db_session, document_id=10)
    assert retrieved.engine == "tesseract"
    assert retrieved.pages[0].lines[0].words[0].confidence == 99.1


def test_missing_document_raises_not_found(db_session):
    ocr_res = sample_canonical_ocr_result(document_id=999)

    with pytest.raises(DocumentNotFoundError) as exc_info:
        save_ocr_result(db_session, document_id=999, ocr_result=ocr_res)

    assert "Document #999 not found" in str(exc_info.value)


def test_missing_ocr_result_raises_not_found(db_session):
    with pytest.raises(DocumentNotFoundError) as exc_info:
        get_ocr_result(db_session, document_id=10)

    assert "OCR result for document #10 not found" in str(exc_info.value)

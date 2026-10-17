import io
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
import pymupdf as fitz
from PIL import Image, ImageDraw
import pytesseract
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Claim, Document, OCRResultRecord
from app.schemas import OCRResult
from app.services.ocr import (
    OCRApplicationService,
    process_document,
    get_ocr_result,
    DocumentNotFoundError,
    DocumentProcessingError,
)


def is_tesseract_installed() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.fixture
def temp_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        session = SessionLocal()

        claim = Claim(id=1, customer_name="Alice Smith", claim_amount=1200.00, status="processing")
        session.add(claim)
        session.commit()

        yield tmp_path, session

        session.close()


def create_digital_pdf(path: Path, text: str) -> Path:
    """Helper to create a digital text PDF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=595.28, height=841.89)
    page.insert_text((50, 50), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def create_test_image(path: Path, text: str) -> Path:
    """Helper to create a PNG image file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (300, 80), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(0, 0, 0))
    img.save(path, format="PNG")
    return path


def test_end_to_end_digital_pdf_processing(temp_workspace):
    tmp_path, db = temp_workspace
    pdf_path = tmp_path / "digital_bill.pdf"
    create_digital_pdf(pdf_path, "CITY HOSPITAL CLAIM #552")

    doc = Document(
        id=101,
        claim_id=1,
        document_type="invoice",
        file_name="digital_bill.pdf",
        file_path=str(pdf_path.as_posix()),
        ocr_status="pending",
    )
    db.add(doc)
    db.commit()

    # Execute orchestrator
    result = process_document(document_id=101, db=db)

    assert isinstance(result, OCRResult)
    assert result.document_id == 101
    assert result.engine == "pymupdf"
    assert "CITY HOSPITAL" in result.pages[0].raw_text

    # Verify document status updated in DB
    db.refresh(doc)
    assert doc.ocr_status == "completed"

    # Verify persisted OCRResultRecord in DB
    record = db.query(OCRResultRecord).filter(OCRResultRecord.document_id == 101).first()
    assert record is not None
    assert record.engine == "pymupdf"

    # Verify retrieval
    retrieved = get_ocr_result(db, document_id=101)
    assert retrieved.engine == "pymupdf"
    assert retrieved.pages[0].lines[0].words[0].confidence is None  # Null for PyMuPDF


def test_end_to_end_image_processing(temp_workspace):
    tmp_path, db = temp_workspace
    png_path = tmp_path / "scanned_receipt.png"
    create_test_image(png_path, "RECEIPT $450")

    doc = Document(
        id=202,
        claim_id=1,
        document_type="receipt",
        file_name="scanned_receipt.png",
        file_path=str(png_path.as_posix()),
        ocr_status="pending",
    )
    db.add(doc)
    db.commit()

    mock_tess_data = {
        "text": ["RECEIPT", "$450"],
        "conf": ["96.0", "99.0"],
        "left": [10, 90],
        "top": [10, 10],
        "width": [70, 40],
        "height": [20, 20],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
    }

    if not is_tesseract_installed():
        with patch("pytesseract.image_to_data", return_value=mock_tess_data):
            with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
                result = process_document(document_id=202, db=db)
    else:
        result = process_document(document_id=202, db=db)

    assert result.document_id == 202
    assert result.engine == "tesseract"
    assert result.processing_metadata["is_scanned"] is True

    db.refresh(doc)
    assert doc.ocr_status == "completed"


def test_missing_document_raises_not_found(temp_workspace):
    _, db = temp_workspace

    with pytest.raises(DocumentNotFoundError) as exc_info:
        process_document(document_id=999, db=db)

    assert "Document #999 not found" in str(exc_info.value)


def test_missing_file_on_disk_raises_not_found(temp_workspace):
    tmp_path, db = temp_workspace
    missing_file = tmp_path / "non_existent.pdf"

    doc = Document(
        id=303,
        claim_id=1,
        document_type="bill",
        file_name="non_existent.pdf",
        file_path=str(missing_file.as_posix()),
        ocr_status="pending",
    )
    db.add(doc)
    db.commit()

    with pytest.raises(DocumentNotFoundError) as exc_info:
        process_document(document_id=303, db=db)

    assert "Document file not found" in str(exc_info.value)

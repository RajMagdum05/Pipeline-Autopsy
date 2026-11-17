import io
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
import pymupdf as fitz
from PIL import Image, ImageDraw
import pytesseract

from app.services.ocr import (
    OCREvidenceExtractor,
    DetailedOCREvidenceResult,
    EvidencePage,
    EvidenceLine,
    EvidenceWord,
    BoundingBox,
    extract_ocr_evidence,
    load_and_validate_document,
    DocumentProcessingError,
    UnsupportedDocumentTypeError,
)


def is_tesseract_installed() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_digital_text_pdf(path: Path, text: str) -> Path:
    """Helper to generate a single-page digital PDF with embedded text."""
    doc = fitz.open()
    page = doc.new_page(width=595.28, height=841.89)
    page.insert_text((50, 50), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def create_scanned_image_pdf(path: Path, text: str) -> Path:
    """Helper to generate a scanned PDF containing a raster image of text."""
    img = Image.new("RGB", (300, 80), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(0, 0, 0))
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=300, height=80)
    page.insert_image(page.rect, stream=img_bytes.getvalue())
    doc.save(path)
    doc.close()
    return path


def create_test_image(path: Path, text: str) -> Path:
    """Helper to generate a PNG image file."""
    img = Image.new("RGB", (300, 80), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(0, 0, 0))
    img.save(path, format="PNG")
    return path


def test_pymupdf_evidence_digital_pdf(temp_dir):
    pdf_path = temp_dir / "claim_bill.pdf"
    create_digital_text_pdf(pdf_path, "Patient Name: Rahul Sharma")

    result = extract_ocr_evidence(pdf_path)

    assert isinstance(result, DetailedOCREvidenceResult)
    assert result.engine == "pymupdf"
    assert result.file_name == "claim_bill.pdf"
    assert result.total_pages == 1
    assert len(result.pages) == 1

    page1 = result.pages[0]
    assert page1.page_number == 1
    assert page1.width == 595.28
    assert page1.height == 841.89
    assert "Rahul" in page1.raw_text
    assert len(page1.lines) > 0

    first_line = page1.lines[0]
    assert "Patient" in first_line.text or "Rahul" in first_line.text
    assert first_line.confidence is None  # PyMuPDF does not fabricate confidence
    assert first_line.bounding_box is not None
    assert first_line.bounding_box.x0 <= first_line.bounding_box.x1

    assert len(first_line.words) > 0
    first_word = first_line.words[0]
    assert isinstance(first_word, EvidenceWord)
    assert first_word.confidence is None  # Must remain None for PyMuPDF
    assert first_word.bounding_box is not None


def test_tesseract_evidence_image(temp_dir):
    png_path = temp_dir / "receipt.png"
    create_test_image(png_path, "INVOICE #99482")

    mock_tess_data = {
        "text": ["INVOICE", "#99482"],
        "conf": ["95.5", "98.2"],
        "left": [10, 100],
        "top": [10, 10],
        "width": [80, 60],
        "height": [20, 20],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
    }

    if not is_tesseract_installed():
        with patch("pytesseract.image_to_data", return_value=mock_tess_data):
            with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
                result = extract_ocr_evidence(png_path)
    else:
        result = extract_ocr_evidence(png_path)

    assert result.engine == "tesseract"
    assert result.total_pages == 1
    assert len(result.pages) == 1

    page = result.pages[0]
    assert page.page_number == 1
    assert page.width > 0
    assert page.height > 0
    assert len(page.lines) > 0

    line = page.lines[0]
    assert len(line.words) > 0
    word = line.words[0]

    # Verify numeric float confidence for Tesseract
    assert isinstance(word.confidence, float)
    assert 0 <= word.confidence <= 100
    assert word.bounding_box is not None
    assert word.bounding_box.x0 < word.bounding_box.x1


def test_tesseract_evidence_scanned_pdf(temp_dir):
    pdf_path = temp_dir / "scanned_receipt.pdf"
    create_scanned_image_pdf(pdf_path, "Hospital Invoice Claim")

    mock_tess_data = {
        "text": ["Hospital", "Invoice"],
        "conf": ["92.0", "96.4"],
        "left": [10, 80],
        "top": [10, 10],
        "width": [60, 50],
        "height": [15, 15],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
    }

    if not is_tesseract_installed():
        with patch("pytesseract.image_to_data", return_value=mock_tess_data):
            with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
                val_doc = load_and_validate_document(pdf_path)
                extractor = OCREvidenceExtractor()
                result = extractor.extract_evidence(val_doc)
    else:
        val_doc = load_and_validate_document(pdf_path)
        extractor = OCREvidenceExtractor()
        result = extractor.extract_evidence(val_doc)

    assert result.engine == "tesseract"
    assert result.total_pages == 1
    assert len(result.pages[0].lines) > 0
    assert isinstance(result.pages[0].lines[0].words[0].confidence, float)


def test_corrupt_file_raises_error(temp_dir):
    bad_file = temp_dir / "corrupt.png"
    bad_file.write_bytes(b"Not an image")

    with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
        with pytest.raises(DocumentProcessingError) as exc_info:
            extract_ocr_evidence(bad_file)

        assert "Corrupt or invalid image file" in str(exc_info.value)


def test_unsupported_file_extension_raises_error(temp_dir):
    txt_file = temp_dir / "notes.txt"
    txt_file.write_text("Hello text")

    with pytest.raises(UnsupportedDocumentTypeError):
        extract_ocr_evidence(txt_file)

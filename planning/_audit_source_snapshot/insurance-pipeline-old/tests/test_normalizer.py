import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
import pymupdf as fitz
from PIL import Image, ImageDraw
import pytesseract

from app.schemas import OCRResult, OCRPage, OCRLine, OCRWord
from app.services.ocr import (
    OCRNormalizer,
    normalize_ocr_result,
    load_and_validate_document,
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


def create_digital_pdf(path: Path, text: str) -> Path:
    """Helper to generate a digital PDF with selectable text."""
    doc = fitz.open()
    page = doc.new_page(width=595.28, height=841.89)
    page.insert_text((50, 50), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def create_test_image(path: Path, text: str) -> Path:
    """Helper to generate a PNG image."""
    img = Image.new("RGB", (300, 80), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(0, 0, 0))
    img.save(path, format="PNG")
    return path


def test_pymupdf_normalization_to_canonical_ocr_result(temp_dir):
    pdf_path = temp_dir / "invoice.pdf"
    create_digital_pdf(pdf_path, "CITY CARE HOSPITAL")

    result = normalize_ocr_result(pdf_path, document_id=101)

    assert isinstance(result, OCRResult)
    assert result.document_id == 101
    assert result.status == "success"
    assert result.engine == "pymupdf"
    assert result.engine_version is not None
    assert result.processing_metadata["filename"] == "invoice.pdf"
    assert result.processing_metadata["is_scanned"] is False
    assert len(result.pages) == 1

    page = result.pages[0]
    assert page.page_number == 1
    assert page.width == 595.28
    assert page.height == 841.89
    assert "CITY" in page.raw_text

    assert len(page.lines) > 0
    line = page.lines[0]
    assert len(line.words) > 0
    word = line.words[0]

    # Verify confidence is None for PyMuPDF
    assert word.confidence is None
    assert isinstance(word.bounding_box, dict)
    assert "x0" in word.bounding_box
    assert "y0" in word.bounding_box
    assert "x1" in word.bounding_box
    assert "y1" in word.bounding_box


def test_tesseract_normalization_to_canonical_ocr_result(temp_dir):
    png_path = temp_dir / "receipt.png"
    create_test_image(png_path, "CLAIM PAYMENT $500")

    mock_tess_data = {
        "text": ["CLAIM", "PAYMENT"],
        "conf": ["95.0", "98.5"],
        "left": [10, 80],
        "top": [10, 10],
        "width": [60, 70],
        "height": [20, 20],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
    }

    if not is_tesseract_installed():
        with patch("pytesseract.image_to_data", return_value=mock_tess_data):
            with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
                result = normalize_ocr_result(png_path, document_id=202)
    else:
        result = normalize_ocr_result(png_path, document_id=202)

    assert isinstance(result, OCRResult)
    assert result.document_id == 202
    assert result.engine == "tesseract"
    assert result.processing_metadata["is_scanned"] is True
    assert len(result.pages) == 1

    page = result.pages[0]
    assert page.page_number == 1
    assert len(page.lines) > 0

    word = page.lines[0].words[0]
    # Verify numeric float confidence for Tesseract
    assert isinstance(word.confidence, float)
    assert word.confidence > 0
    assert isinstance(word.bounding_box, dict)
    assert "x0" in word.bounding_box


def test_full_json_serializability(temp_dir):
    pdf_path = temp_dir / "hospital_claim.pdf"
    create_digital_pdf(pdf_path, "PATIENT RAHUL SHARMA")

    result = normalize_ocr_result(pdf_path, document_id=99)

    # 1. Verify model_dump dictionary
    dump_dict = result.model_dump()
    assert dump_dict["document_id"] == 99
    assert dump_dict["status"] == "success"
    assert isinstance(dump_dict["pages"], list)

    # 2. Verify model_dump_json JSON string
    json_str = result.model_dump_json()
    assert isinstance(json_str, str)

    # 3. Verify standard json.loads parsing
    parsed_json = json.loads(json_str)
    assert parsed_json["document_id"] == 99
    assert parsed_json["engine"] == "pymupdf"
    assert parsed_json["pages"][0]["page_number"] == 1
    assert parsed_json["pages"][0]["lines"][0]["words"][0]["confidence"] is None

import io
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
import pymupdf as fitz
from PIL import Image, ImageDraw
import pytesseract

from app.services.ocr import (
    TesseractOCRProvider,
    TesseractOCRResult,
    TesseractPageResult,
    run_tesseract_ocr,
    load_and_validate_document,
    DocumentProcessingError,
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


def create_test_image(path: Path, text: str, fmt: str = "PNG") -> Path:
    """Helper to generate a PNG/JPG image with rendered text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (400, 100), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(0, 0, 0))
    img.save(path, format=fmt)
    return path


def create_scanned_multi_page_pdf(path: Path, text_p1: str, text_p2: str) -> Path:
    """Helper to generate a 2-page scanned PDF with raster images on each page."""
    doc = fitz.open()

    for text in [text_p1, text_p2]:
        img = Image.new("RGB", (300, 80), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, fill=(0, 0, 0))
        img_bytes = io.BytesIO()
        img.save(img_bytes, format="PNG")

        page = doc.new_page(width=300, height=80)
        page.insert_image(page.rect, stream=img_bytes.getvalue())

    doc.save(path)
    doc.close()
    return path


def test_png_image_ocr(temp_dir):
    png_path = temp_dir / "receipt.png"
    create_test_image(png_path, "INVOICE #99482")

    if not is_tesseract_installed():
        with patch("pytesseract.image_to_string", return_value="INVOICE #99482"):
            with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
                result = run_tesseract_ocr(png_path)
    else:
        result = run_tesseract_ocr(png_path)

    assert isinstance(result, TesseractOCRResult)
    assert result.engine == "tesseract"
    assert result.file_name == "receipt.png"
    assert result.total_pages == 1
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert "INVOICE" in result.pages[0].raw_text or "99482" in result.pages[0].raw_text


def test_jpg_image_ocr(temp_dir):
    jpg_path = temp_dir / "claim_photo.jpg"
    create_test_image(jpg_path, "PATIENT CLAIM 2026", fmt="JPEG")

    if not is_tesseract_installed():
        with patch("pytesseract.image_to_string", return_value="PATIENT CLAIM 2026"):
            with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
                result = run_tesseract_ocr(jpg_path)
    else:
        result = run_tesseract_ocr(jpg_path)

    assert result.total_pages == 1
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1


def test_scanned_multi_page_pdf_ocr(temp_dir):
    pdf_path = temp_dir / "scanned_doc.pdf"
    create_scanned_multi_page_pdf(pdf_path, "Hospital Bill Page 1", "Hospital Bill Page 2")

    if not is_tesseract_installed():
        with patch("pytesseract.image_to_string", side_effect=["Hospital Bill Page 1", "Hospital Bill Page 2"]):
            with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
                val_doc = load_and_validate_document(pdf_path)
                provider = TesseractOCRProvider()
                result = provider.process(val_doc)
    else:
        val_doc = load_and_validate_document(pdf_path)
        provider = TesseractOCRProvider()
        result = provider.process(val_doc)

    assert result.total_pages == 2
    assert len(result.pages) == 2
    assert result.pages[0].page_number == 1
    assert result.pages[1].page_number == 2


def test_invalid_corrupt_image_raises_error(temp_dir):
    bad_img = temp_dir / "corrupt.png"
    bad_img.write_bytes(b"Not a valid PNG header")

    with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
        with pytest.raises(DocumentProcessingError) as exc_info:
            run_tesseract_ocr(bad_img)

        assert "Corrupt or invalid image file" in str(exc_info.value)


def test_invalid_corrupt_pdf_raises_error(temp_dir):
    bad_pdf = temp_dir / "corrupt.pdf"
    bad_pdf.write_bytes(b"Not a valid PDF file stream")

    with patch("pytesseract.get_tesseract_version", return_value="5.3.0"):
        with pytest.raises(DocumentProcessingError) as exc_info:
            run_tesseract_ocr(bad_pdf)

        assert "Corrupt or invalid PDF file" in str(exc_info.value)


def test_missing_tesseract_executable_raises_error(temp_dir):
    png_path = temp_dir / "sample.png"
    create_test_image(png_path, "Sample Text")

    with patch("pytesseract.get_tesseract_version", side_effect=pytesseract.TesseractNotFoundError()):
        provider = TesseractOCRProvider()
        with pytest.raises(DocumentProcessingError) as exc_info:
            provider.process(png_path)

        assert "Tesseract OCR executable is not installed" in str(exc_info.value)

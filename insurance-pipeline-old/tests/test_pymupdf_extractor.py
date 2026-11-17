import io
import tempfile
from pathlib import Path
import pytest
import pymupdf as fitz
from PIL import Image

from app.services.ocr import (
    PyMuPDFTextExtractor,
    DirectTextExtractionResult,
    ExtractedPageText,
    extract_direct_text,
    load_and_validate_document,
    DocumentProcessingError,
    UnsupportedDocumentTypeError,
)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_single_page_pdf(path: Path, text: str) -> Path:
    """Helper to generate a single-page text PDF."""
    doc = fitz.open()
    page = doc.new_page(width=595.28, height=841.89)  # A4 size in points
    page.insert_text((50, 50), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def create_multi_page_pdf(path: Path, page1_text: str, page2_text: str) -> Path:
    """Helper to generate a 2-page text PDF."""
    doc = fitz.open()
    
    p1 = doc.new_page(width=595.28, height=841.89)
    p1.insert_text((50, 50), page1_text, fontsize=12)
    
    p2 = doc.new_page(width=595.28, height=841.89)
    p2.insert_text((50, 50), page2_text, fontsize=12)
    
    doc.save(path)
    doc.close()
    return path


def create_pdf_with_empty_page(path: Path, page1_text: str) -> Path:
    """Helper to generate a 2-page PDF where page 2 is blank."""
    doc = fitz.open()
    
    p1 = doc.new_page(width=595.28, height=841.89)
    p1.insert_text((50, 50), page1_text, fontsize=12)
    
    _p2 = doc.new_page(width=595.28, height=841.89)  # blank page
    
    doc.save(path)
    doc.close()
    return path


def create_scanned_image_only_pdf(path: Path) -> Path:
    """Helper to generate an image-only scanned PDF."""
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_image(page.rect, stream=img_bytes)
    doc.save(path)
    doc.close()
    return path


def test_single_page_text_pdf(temp_dir):
    pdf_path = temp_dir / "hospital_bill.pdf"
    expected_text = "CITY CARE HOSPITAL Patient Name: Rahul Sharma"
    create_single_page_pdf(pdf_path, expected_text)

    result = extract_direct_text(pdf_path)

    assert isinstance(result, DirectTextExtractionResult)
    assert result.file_name == "hospital_bill.pdf"
    assert result.total_pages == 1
    assert result.has_embedded_text is True
    assert result.requires_ocr is False
    assert len(result.pages) == 1

    page1 = result.pages[0]
    assert page1.page_number == 1
    assert expected_text in page1.text
    assert page1.width > 0
    assert page1.height > 0
    assert expected_text in result.full_text


def test_multi_page_text_pdf(temp_dir):
    pdf_path = temp_dir / "medical_records.pdf"
    p1_content = "Patient Admission Record #1002"
    p2_content = "Diagnosis: Acute Appendicitis Surgery Approved"
    create_multi_page_pdf(pdf_path, p1_content, p2_content)

    val_doc = load_and_validate_document(pdf_path)
    extractor = PyMuPDFTextExtractor()
    result = extractor.extract(val_doc)

    assert result.total_pages == 2
    assert result.has_embedded_text is True
    assert result.requires_ocr is False
    assert len(result.pages) == 2

    assert p1_content in result.pages[0].text
    assert p2_content in result.pages[1].text
    assert p1_content in result.full_text
    assert p2_content in result.full_text


def test_pdf_with_empty_page(temp_dir):
    pdf_path = temp_dir / "has_blank_page.pdf"
    p1_content = "Summary of Medical Expenses: $4,500.00"
    create_pdf_with_empty_page(pdf_path, p1_content)

    result = extract_direct_text(pdf_path)

    assert result.total_pages == 2
    assert result.has_embedded_text is True
    assert result.requires_ocr is False
    assert len(result.pages) == 2

    assert p1_content in result.pages[0].text
    assert result.pages[1].text == ""
    assert p1_content in result.full_text


def test_scanned_image_only_pdf_returns_requires_ocr(temp_dir):
    pdf_path = temp_dir / "scanned_receipt.pdf"
    create_scanned_image_only_pdf(pdf_path)

    result = extract_direct_text(pdf_path)

    assert result.file_name == "scanned_receipt.pdf"
    assert result.total_pages == 1
    assert result.has_embedded_text is False
    assert result.requires_ocr is True
    assert result.full_text == ""
    assert len(result.pages) == 1
    assert result.pages[0].text == ""


def test_corrupt_pdf_raises_error(temp_dir):
    corrupt_path = temp_dir / "invalid.pdf"
    corrupt_path.write_bytes(b"Corrupt PDF data header")

    with pytest.raises(DocumentProcessingError) as exc_info:
        extract_direct_text(corrupt_path)

    assert "Corrupt or invalid PDF file" in str(exc_info.value)


def test_non_pdf_file_raises_unsupported_error(temp_dir):
    png_path = temp_dir / "invoice.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n fake image content")

    with pytest.raises(UnsupportedDocumentTypeError) as exc_info:
        extract_direct_text(png_path)

    assert "PyMuPDFTextExtractor only processes '.pdf' files" in str(exc_info.value)

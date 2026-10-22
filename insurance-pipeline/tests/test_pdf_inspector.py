import io
import tempfile
from pathlib import Path
import pytest
import pymupdf as fitz
from PIL import Image

from app.services.ocr import (
    PDFInspector,
    PDFInspectionResult,
    PDFPageInspection,
    inspect_pdf,
    load_and_validate_document,
    DocumentProcessingError,
    UnsupportedDocumentTypeError,
)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_selectable_text_pdf(path: Path, text: str) -> Path:
    """Helper to generate a single-page PDF containing embedded selectable text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def create_multi_page_mixed_pdf(path: Path) -> Path:
    """Helper to generate a 3-page PDF: page 1 & 2 have text, page 3 is empty."""
    doc = fitz.open()
    
    p1 = doc.new_page()
    p1.insert_text((50, 50), "Hospital Invoice Claim #101", fontsize=12)
    
    p2 = doc.new_page()
    p2.insert_text((50, 50), "Itemized charges total: $1,250.00", fontsize=12)
    
    p3 = doc.new_page()  # Blank page, no text inserted
    
    doc.save(path)
    doc.close()
    return path


def create_scanned_image_only_pdf(path: Path) -> Path:
    """Helper to generate a PDF containing only a raster image (simulating a scanned document)."""
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


def test_pdf_with_selectable_text(temp_dir):
    pdf_path = temp_dir / "hospital_bill.pdf"
    create_selectable_text_pdf(pdf_path, "Medical Claim Details for Patient John Doe")

    result = inspect_pdf(pdf_path)

    assert isinstance(result, PDFInspectionResult)
    assert result.file_name == "hospital_bill.pdf"
    assert result.total_pages == 1
    assert result.has_embedded_text is True
    assert result.is_scanned is False
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert result.pages[0].has_text is True
    assert result.pages[0].text_length > 0


def test_scanned_image_only_pdf(temp_dir):
    pdf_path = temp_dir / "scanned_receipt.pdf"
    create_scanned_image_only_pdf(pdf_path)

    result = inspect_pdf(pdf_path)

    assert result.file_name == "scanned_receipt.pdf"
    assert result.total_pages == 1
    assert result.has_embedded_text is False
    assert result.is_scanned is True
    assert len(result.pages) == 1
    assert result.pages[0].has_text is False
    assert result.pages[0].text_length == 0


def test_multi_page_pdf(temp_dir):
    pdf_path = temp_dir / "multi_page_claim.pdf"
    create_multi_page_mixed_pdf(pdf_path)

    val_doc = load_and_validate_document(pdf_path)
    inspector = PDFInspector()
    result = inspector.inspect(val_doc)

    assert result.total_pages == 3
    assert result.has_embedded_text is True
    assert result.is_scanned is False
    assert len(result.pages) == 3

    assert result.pages[0].page_number == 1
    assert result.pages[0].has_text is True

    assert result.pages[1].page_number == 2
    assert result.pages[1].has_text is True

    assert result.pages[2].page_number == 3
    assert result.pages[2].has_text is False
    assert result.pages[2].text_length == 0


def test_corrupt_pdf_raises_error(temp_dir):
    corrupt_path = temp_dir / "corrupt_file.pdf"
    corrupt_path.write_bytes(b"This is not a valid PDF header content!")

    with pytest.raises(DocumentProcessingError) as exc_info:
        inspect_pdf(corrupt_path)

    assert "Corrupt or invalid PDF file" in str(exc_info.value)


def test_non_pdf_file_raises_unsupported_error(temp_dir):
    png_path = temp_dir / "receipt.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n fake image content")

    val_doc = load_and_validate_document(png_path)
    inspector = PDFInspector()

    with pytest.raises(UnsupportedDocumentTypeError) as exc_info:
        inspector.inspect(val_doc)

    assert "PDFInspector only processes '.pdf' files" in str(exc_info.value)

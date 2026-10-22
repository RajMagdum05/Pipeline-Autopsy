import io
import tempfile
from pathlib import Path
import pytest
import pymupdf as fitz
from PIL import Image

from app.services.ocr import (
    DocumentInspector,
    DocumentInspectionResult,
    PDFInspector,
    PDFInspectionResult,
    inspect_document,
    inspect_pdf,
    load_and_validate_document,
    DocumentProcessingError,
    UnsupportedDocumentTypeError,
)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_digital_pdf(path: Path, text: str = "Medical Claim #204 - Inpatient Treatment") -> Path:
    """Creates a digital PDF containing selectable native text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def create_scanned_pdf(path: Path) -> Path:
    """Creates a scanned PDF containing a raster image without selectable text."""
    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()

    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_image(page.rect, stream=img_bytes)
    doc.save(path)
    doc.close()
    return path


def create_sample_image(path: Path, ext: str = "png") -> Path:
    """Creates a sample raster image file."""
    img = Image.new("RGB", (150, 150), color=(240, 240, 240))
    img.save(path, format=ext.upper())
    return path


def test_digital_pdf_inspection_routes_to_text_extraction(temp_dir):
    """Digital PDF with selectable text should route to 'text_extraction'."""
    pdf_path = temp_dir / "discharge_summary.pdf"
    create_digital_pdf(pdf_path, "Discharge Summary: Patient admitted on 2026-09-10.")

    result = inspect_document(pdf_path, document_id=101)

    assert isinstance(result, DocumentInspectionResult)
    assert result.document_id == 101
    assert result.file_name == "discharge_summary.pdf"
    assert result.file_type == "pdf"
    assert result.total_pages == 1
    assert result.has_embedded_text is True
    assert result.is_text_based is True
    assert result.is_scanned is False
    assert result.ocr_required is False
    assert result.processing_path == "text_extraction"
    assert len(result.pages) == 1
    assert result.pages[0].has_text is True


def test_scanned_pdf_inspection_routes_to_ocr(temp_dir):
    """Scanned PDF without selectable text should route to 'ocr'."""
    pdf_path = temp_dir / "scanned_invoice.pdf"
    create_scanned_pdf(pdf_path)

    result = inspect_document(pdf_path, document_id=102)

    assert isinstance(result, DocumentInspectionResult)
    assert result.document_id == 102
    assert result.file_name == "scanned_invoice.pdf"
    assert result.file_type == "pdf"
    assert result.total_pages == 1
    assert result.has_embedded_text is False
    assert result.is_text_based is False
    assert result.is_scanned is True
    assert result.ocr_required is True
    assert result.processing_path == "ocr"
    assert len(result.pages) == 1
    assert result.pages[0].has_text is False


def test_image_inspection_routes_to_ocr(temp_dir):
    """Image input (.png, .jpg) should route to 'ocr'."""
    img_path = temp_dir / "receipt.png"
    create_sample_image(img_path, ext="png")

    result = inspect_document(img_path, document_id=103)

    assert isinstance(result, DocumentInspectionResult)
    assert result.document_id == 103
    assert result.file_name == "receipt.png"
    assert result.file_type == "image"
    assert result.total_pages == 1
    assert result.has_embedded_text is False
    assert result.is_text_based is False
    assert result.is_scanned is True
    assert result.ocr_required is True
    assert result.processing_path == "ocr"


def test_unsupported_file_extension_raises_error(temp_dir):
    """Unsupported file types should raise UnsupportedDocumentTypeError."""
    csv_path = temp_dir / "data.csv"
    csv_path.write_text("a,b,c\n1,2,3")

    with pytest.raises(UnsupportedDocumentTypeError) as exc_info:
        inspect_document(csv_path)

    assert "Unsupported" in str(exc_info.value)


def test_corrupt_pdf_raises_processing_error(temp_dir):
    """Corrupted PDF should raise DocumentProcessingError."""
    corrupt_path = temp_dir / "broken.pdf"
    corrupt_path.write_bytes(b"NOT A VALID PDF HEADER CONTENT")

    with pytest.raises(DocumentProcessingError) as exc_info:
        inspect_document(corrupt_path)

    assert "Corrupt or invalid PDF" in str(exc_info.value)

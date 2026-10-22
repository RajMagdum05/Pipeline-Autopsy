import io
from pathlib import Path
import pymupdf as fitz
from PIL import Image, ImageDraw
import pytesseract
import pytest

from app.services.document_processor import (
    DocumentProcessingError,
    OCRLine,
    OCRPage,
    OCRResult,
    PyMuPDFProvider,
    TesseractProvider,
    process_document,
    extract_text_from_document,
)


def create_multi_page_pdf(path: Path):
    """Creates a 2-page text PDF file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    
    p1 = doc.new_page()
    p1.insert_text((50, 50), "Page 1: Medical Invoice Detail\nPatient: Rahul Sharma", fontsize=12)
    
    p2 = doc.new_page()
    p2.insert_text((50, 50), "Page 2: Summary of Charges\nTotal Amount: $75,000.00", fontsize=12)
    
    doc.save(path)
    doc.close()


def create_blank_pdf(path: Path):
    """Creates a PDF page with no embedded text (simulating image/scanned PDF)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()


def create_image(path: Path, fmt: str = "PNG"):
    """Creates a sample test image file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (300, 100), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 10), f"Test {fmt} Content", fill=(0, 0, 0))
    img.save(path, format=fmt)


def test_ocr_schema_models():
    line = OCRLine(text="Claim ID: 101")
    assert line.text == "Claim ID: 101"
    assert line.confidence is None
    assert line.bounding_box is None

    page = OCRPage(page_number=1, raw_text="Line 1\nLine 2", lines=[line])
    assert page.page_number == 1
    assert len(page.lines) == 1

    res = OCRResult(document_id="doc_999", pages=[page], engine="pymupdf", engine_version="1.0.0")
    dump = res.model_dump()
    assert dump["document_id"] == "doc_999"
    assert dump["engine"] == "pymupdf"
    assert dump["pages"][0]["page_number"] == 1


def test_pymupdf_provider_direct(tmp_path: Path):
    multi_pdf = tmp_path / "multi_page.pdf"
    create_multi_page_pdf(multi_pdf)
    
    provider = PyMuPDFProvider()
    result = provider.process(multi_pdf, document_id=123)
    assert result.engine == "pymupdf"
    assert len(result.pages) == 2
    assert result.pages[0].page_number == 1
    assert "Page 1: Medical Invoice Detail" in result.pages[0].raw_text
    assert result.pages[1].page_number == 2
    assert "Page 2: Summary of Charges" in result.pages[1].raw_text
    assert result.processing_metadata["total_pages"] == 2
    assert result.processing_metadata["is_scanned"] is False

    blank_pdf = tmp_path / "blank.pdf"
    create_blank_pdf(blank_pdf)
    blank_res = provider.process(blank_pdf)
    assert len(blank_res.pages) == 0
    assert blank_res.processing_metadata["is_scanned"] is True


def test_process_document_router_full(tmp_path: Path):
    multi_pdf = tmp_path / "multi_page.pdf"
    create_multi_page_pdf(multi_pdf)

    doc_res = process_document(multi_pdf, document_id="claim_456")
    assert doc_res.document_id == "claim_456"
    assert doc_res.engine == "pymupdf"
    assert len(doc_res.pages) == 2


def test_extract_text_from_document_wrapper_full(tmp_path: Path):
    multi_pdf = tmp_path / "multi_page.pdf"
    create_multi_page_pdf(multi_pdf)

    extracted_str = extract_text_from_document(multi_pdf)
    assert "Page 1: Medical Invoice Detail" in extracted_str
    assert "Page 2: Summary of Charges" in extracted_str
    assert "\n\n" in extracted_str


def test_ocr_error_handling_and_edge_cases(tmp_path: Path):
    # Missing File
    with pytest.raises(DocumentProcessingError) as exc1:
        process_document(tmp_path / "non_existent.pdf")
    assert "File not found" in str(exc1.value)

    # Unsupported Extension
    unsupported_file = tmp_path / "data.json"
    unsupported_file.write_text('{"key": "val"}')
    with pytest.raises(DocumentProcessingError) as exc2:
        process_document(unsupported_file)
    assert "Unsupported file format" in str(exc2.value)

    # Corrupt PDF
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"INVALID PDF DATA HEADER")
    with pytest.raises(DocumentProcessingError) as exc3:
        process_document(corrupt_pdf)
    assert "Corrupt or invalid" in str(exc3.value) or "Error processing file" in str(exc3.value)


if __name__ == "__main__":
    pytest.main([__file__])

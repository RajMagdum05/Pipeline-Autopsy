from pathlib import Path
import pytest
import pymupdf as fitz
from PIL import Image, ImageDraw
import pytesseract

from app.services.document_processor import (
    DocumentProcessingError,
    OCRResult,
    extract_text_from_document,
    process_document,
)


def is_tesseract_installed() -> bool:
    """Helper to check if Tesseract OCR binary is installed and operational."""
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def create_text_pdf(path: Path, text: str) -> Path:
    """Helper to generate a single-page text PDF using PyMuPDF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text, fontsize=12)
    doc.save(path)
    doc.close()
    return path


def create_multi_page_pdf(path: Path, p1_text: str, p2_text: str) -> Path:
    """Helper to generate a two-page text PDF using PyMuPDF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    
    page1 = doc.new_page()
    page1.insert_text((50, 50), p1_text, fontsize=12)
    
    page2 = doc.new_page()
    page2.insert_text((50, 50), p2_text, fontsize=12)
    
    doc.save(path)
    doc.close()
    return path


def create_test_image(path: Path, text: str) -> Path:
    """Helper to generate a PNG image with text drawn on it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (400, 100), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((10, 10), text, fill=(0, 0, 0))
    img.save(path, format="PNG")
    return path


def create_scanned_pdf(path: Path, text: str, tmp_dir: Path) -> Path:
    """Helper to generate a PDF containing only an image (scanned PDF)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img_path = tmp_dir / "temp_scanned_img.png"
    create_test_image(img_path, text)

    doc = fitz.open()
    page = doc.new_page(width=400, height=100)
    page.insert_image(page.rect, filename=str(img_path))
    doc.save(path)
    doc.close()
    return path


# -------------------------------------------------------------------
# Required Test 1: Text-based PDF
# -------------------------------------------------------------------
def test_text_based_pdf_processing(tmp_path: Path):
    pdf_path = create_text_pdf(tmp_path / "invoice.pdf", "HEALTH INSURANCE CLAIM #101\nAmount: $500.00")
    
    result = process_document(pdf_path, document_id="claim_101")
    
    assert isinstance(result, OCRResult)
    assert result.status == "success"
    assert result.engine == "pymupdf"
    assert result.processing_duration_ms is not None
    assert len(result.pages) >= 1
    
    page1 = result.pages[0]
    assert page1.page_number == 1
    assert page1.width is not None and page1.width > 0
    assert page1.height is not None and page1.height > 0
    assert "HEALTH INSURANCE CLAIM #101" in page1.raw_text
    assert len(page1.lines) > 0
    
    first_line = page1.lines[0]
    assert first_line.bounding_box is not None
    assert len(first_line.words) > 0
    assert first_line.words[0].text == "HEALTH"
    assert first_line.words[0].bounding_box is not None


# -------------------------------------------------------------------
# Required Test 2: Image OCR
# -------------------------------------------------------------------
def test_image_ocr_processing(tmp_path: Path):
    if not is_tesseract_installed():
        pytest.skip("Tesseract OCR binary not found on system environment")

    img_path = create_test_image(tmp_path / "receipt.png", "RECEIPT #888 Total $50")
    
    result = process_document(img_path)
    
    assert isinstance(result, OCRResult)
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert "RECEIPT" in result.pages[0].raw_text or "888" in result.pages[0].raw_text
    assert result.engine == "tesseract"


# -------------------------------------------------------------------
# Required Test 3: Scanned PDF OCR
# -------------------------------------------------------------------
def test_scanned_pdf_ocr_processing(tmp_path: Path):
    if not is_tesseract_installed():
        pytest.skip("Tesseract OCR binary not found on system environment")

    scanned_pdf = create_scanned_pdf(tmp_path / "scanned.pdf", "SCANNED REPORT #777", tmp_path)
    
    result = process_document(scanned_pdf)
    
    assert isinstance(result, OCRResult)
    assert result.engine == "tesseract"
    assert len(result.pages) >= 1
    assert "SCANNED" in result.pages[0].raw_text or "777" in result.pages[0].raw_text


# -------------------------------------------------------------------
# Required Test 4: Missing File
# -------------------------------------------------------------------
def test_missing_file_handling(tmp_path: Path):
    missing_file = tmp_path / "non_existent_file.pdf"
    
    with pytest.raises(DocumentProcessingError) as exc_info:
        process_document(missing_file)
        
    assert "File not found" in str(exc_info.value)


# -------------------------------------------------------------------
# Required Test 5: Unsupported Format
# -------------------------------------------------------------------
def test_unsupported_format_handling(tmp_path: Path):
    unsupported_file = tmp_path / "document.txt"
    unsupported_file.write_text("Plain text content")
    
    with pytest.raises(DocumentProcessingError) as exc_info:
        process_document(unsupported_file)
        
    assert "Unsupported file format" in str(exc_info.value)


# -------------------------------------------------------------------
# Required Test 6: Corrupt PDF
# -------------------------------------------------------------------
def test_corrupt_pdf_handling(tmp_path: Path):
    corrupt_pdf = tmp_path / "corrupt.pdf"
    corrupt_pdf.write_bytes(b"NOT A VALID PDF FILE HEADER OR CONTENT")
    
    with pytest.raises(DocumentProcessingError):
        process_document(corrupt_pdf)


# -------------------------------------------------------------------
# Required Test 7: Backward Compatibility
# -------------------------------------------------------------------
def test_backward_compatibility_wrapper(tmp_path: Path):
    pdf_path = create_text_pdf(tmp_path / "legacy.pdf", "PATIENT NAME: Rahul Sharma\nDIAGNOSIS: Appendicitis")
    
    text = extract_text_from_document(pdf_path)
    
    assert isinstance(text, str)
    assert "Rahul Sharma" in text
    assert "Appendicitis" in text


# -------------------------------------------------------------------
# Required Test 8: Multi-page PDF
# -------------------------------------------------------------------
def test_multi_page_pdf_processing(tmp_path: Path):
    p1_content = "Page 1: Medical History and Examination Notes"
    p2_content = "Page 2: Final Treatment Summary and Prescription Details"
    pdf_path = create_multi_page_pdf(tmp_path / "multi_page.pdf", p1_content, p2_content)
    
    result = process_document(pdf_path)
    
    assert isinstance(result, OCRResult)
    assert len(result.pages) == 2
    assert [p.page_number for p in result.pages] == [1, 2]
    assert "Medical History" in result.pages[0].raw_text
    assert "Treatment Summary" in result.pages[1].raw_text

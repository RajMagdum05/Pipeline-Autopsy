import hashlib
from pathlib import Path
import pytest
import pymupdf as fitz

from app.services.ocr.pdf_inspector import PDFInspector
from app.services.ocr.evidence_extractor import OCREvidenceExtractor
from app.services.ocr.normalizer import OCRNormalizer
from app.services.ocr.document_loader import load_and_validate_document
from app.schemas import OCRResult, OCRPage


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    h.update(filepath.read_bytes())
    return h.hexdigest()


@pytest.fixture
def digital_pdf_path(tmp_path) -> Path:
    pdf_file = tmp_path / "digital_doc.pdf"
    doc = fitz.open()
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 50), "Page 1 Digital Line Text", fontsize=12)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 50), "Page 2 Digital Line Text", fontsize=12)
    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


@pytest.fixture
def scanned_pdf_path(tmp_path) -> Path:
    pdf_file = tmp_path / "scanned_doc.pdf"
    doc = fitz.open()
    page1 = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.Rect(0, 0, 100, 100), False)
    pix.clear_with(220)
    page1.insert_image(fitz.Rect(50, 50, 250, 250), pixmap=pix)
    
    page2 = doc.new_page(width=595, height=842)
    pix2 = fitz.Pixmap(fitz.csRGB, fitz.Rect(0, 0, 100, 100), False)
    pix2.clear_with(200)
    page2.insert_image(fitz.Rect(50, 50, 250, 250), pixmap=pix2)
    
    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


@pytest.fixture
def mixed_pdf_path(tmp_path) -> Path:
    pdf_file = tmp_path / "mixed_doc.pdf"
    doc = fitz.open()
    
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 50), "Page 1 Digital Text Content", fontsize=12)
    
    page2 = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.Rect(0, 0, 100, 100), False)
    pix.clear_with(200)
    page2.insert_image(fitz.Rect(50, 50, 200, 200), pixmap=pix)
    
    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


def test_digital_pdf_structured_ocr_result(digital_pdf_path):
    sha_before = compute_sha256(digital_pdf_path)
    val_doc = load_and_validate_document(digital_pdf_path)
    
    inspector = PDFInspector()
    insp = inspector.inspect(val_doc, document_id=881)
    
    extractor = OCREvidenceExtractor()
    ev = extractor._extract_pymupdf_evidence(val_doc, insp)
    
    normalizer = OCRNormalizer()
    res: OCRResult = normalizer.normalize_evidence(ev, document_id=881)
    
    assert res.document_id == 881
    assert res.engine == "pymupdf"
    assert len(res.pages) == 2
    
    for page in res.pages:
        assert page.document_id == 881
        assert page.extraction_method == "DIRECT_TEXT"
        assert page.status == "DIRECT_TEXT"
        assert len(page.lines) > 0
        
    sha_after = compute_sha256(digital_pdf_path)
    assert sha_before == sha_after, "Original PDF was mutated!"


def test_scanned_multipage_pdf_structured_ocr_result(scanned_pdf_path):
    sha_before = compute_sha256(scanned_pdf_path)
    val_doc = load_and_validate_document(scanned_pdf_path)
    
    inspector = PDFInspector()
    insp = inspector.inspect(val_doc, document_id=882)
    
    extractor = OCREvidenceExtractor()
    ev = extractor._extract_pymupdf_evidence(val_doc, insp)
    
    normalizer = OCRNormalizer()
    res: OCRResult = normalizer.normalize_evidence(ev, document_id=882)
    
    assert res.document_id == 882
    assert res.engine == "tesseract"
    assert len(res.pages) == 2
    
    assert res.pages[0].page_number == 1
    assert res.pages[0].document_id == 882
    assert res.pages[0].extraction_method == "TESSERACT_OCR"
    
    assert res.pages[1].page_number == 2
    assert res.pages[1].document_id == 882
    assert res.pages[1].extraction_method == "TESSERACT_OCR"
    
    sha_after = compute_sha256(scanned_pdf_path)
    assert sha_before == sha_after, "Original PDF was mutated!"


def test_mixed_pdf_structured_ocr_result(mixed_pdf_path):
    sha_before = compute_sha256(mixed_pdf_path)
    val_doc = load_and_validate_document(mixed_pdf_path)
    
    inspector = PDFInspector()
    insp = inspector.inspect(val_doc, document_id=883)
    
    extractor = OCREvidenceExtractor()
    ev = extractor._extract_pymupdf_evidence(val_doc, insp)
    
    normalizer = OCRNormalizer()
    res: OCRResult = normalizer.normalize_evidence(ev, document_id=883)
    
    assert res.document_id == 883
    assert res.engine == "hybrid"
    assert len(res.pages) == 2
    
    # Page 1: DIRECT_TEXT
    assert res.pages[0].page_number == 1
    assert res.pages[0].document_id == 883
    assert res.pages[0].extraction_method == "DIRECT_TEXT"
    assert res.pages[0].status == "DIRECT_TEXT"
    assert "Page 1 Digital Text Content" in res.pages[0].raw_text
    
    # Page 2: TESSERACT_OCR
    assert res.pages[1].page_number == 2
    assert res.pages[1].document_id == 883
    assert res.pages[1].extraction_method == "TESSERACT_OCR"
    assert res.pages[1].status == "OCR_REQUIRED"
    
    sha_after = compute_sha256(mixed_pdf_path)
    assert sha_before == sha_after, "Original PDF was mutated!"

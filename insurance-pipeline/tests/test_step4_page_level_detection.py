import hashlib
from pathlib import Path
import pytest
import pymupdf as fitz

from app.services.ocr.pdf_inspector import PDFInspector
from app.services.ocr.evidence_extractor import OCREvidenceExtractor
from app.services.ocr.normalizer import OCRNormalizer
from app.services.ocr.document_loader import load_and_validate_document


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    h.update(filepath.read_bytes())
    return h.hexdigest()


@pytest.fixture
def digital_pdf_path(tmp_path) -> Path:
    pdf_file = tmp_path / "digital_test.pdf"
    doc = fitz.open()
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 50), "Header Title for Digital Document", fontsize=12)
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 50), "Second Page Body Content", fontsize=12)
    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


@pytest.fixture
def scanned_pdf_path(tmp_path) -> Path:
    pdf_file = tmp_path / "scanned_test.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.Rect(0, 0, 100, 100), False)
    pix.clear_with(255)
    page.insert_image(fitz.Rect(50, 50, 200, 200), pixmap=pix)
    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


@pytest.fixture
def mixed_pdf_path(tmp_path) -> Path:
    pdf_file = tmp_path / "mixed_test.pdf"
    doc = fitz.open()
    
    # Page 1: Digital
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 50), "Page 1 Digital Text Content", fontsize=12)
    
    # Page 2: Scanned Image (no text)
    page2 = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.Rect(0, 0, 100, 100), False)
    pix.clear_with(200)
    page2.insert_image(fitz.Rect(50, 50, 200, 200), pixmap=pix)
    
    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


def test_digital_pdf_page_level_status(digital_pdf_path):
    sha_before = compute_sha256(digital_pdf_path)
    val_doc = load_and_validate_document(digital_pdf_path)
    
    inspector = PDFInspector()
    insp_res = inspector.inspect(val_doc)
    assert insp_res.total_pages == 2
    assert insp_res.direct_text_pages_count == 2
    assert insp_res.ocr_required_pages_count == 0
    assert insp_res.is_mixed_pdf is False
    
    extractor = OCREvidenceExtractor()
    evidence = extractor._extract_pymupdf_evidence(val_doc, insp_res)
    assert len(evidence.pages) == 2
    assert evidence.pages[0].status == "DIRECT_TEXT"
    assert evidence.pages[1].status == "DIRECT_TEXT"
    
    normalizer = OCRNormalizer()
    normalized = normalizer.normalize_evidence(evidence)
    assert normalized.pages[0].status == "DIRECT_TEXT"
    assert normalized.pages[1].status == "DIRECT_TEXT"
    assert normalized.processing_metadata["is_mixed_pdf"] is False
    
    sha_after = compute_sha256(digital_pdf_path)
    assert sha_before == sha_after, "Original PDF was mutated!"


def test_scanned_pdf_page_level_status(scanned_pdf_path):
    sha_before = compute_sha256(scanned_pdf_path)
    val_doc = load_and_validate_document(scanned_pdf_path)
    
    inspector = PDFInspector()
    insp_res = inspector.inspect(val_doc)
    assert insp_res.total_pages == 1
    assert insp_res.direct_text_pages_count == 0
    assert insp_res.ocr_required_pages_count == 1
    assert insp_res.is_mixed_pdf is False
    
    extractor = OCREvidenceExtractor()
    evidence = extractor._extract_pymupdf_evidence(val_doc, insp_res)
    assert len(evidence.pages) == 1
    assert evidence.pages[0].status == "OCR_REQUIRED"
    assert evidence.pages[0].raw_text == ""
    assert evidence.pages[0].width == 595.0
    assert evidence.pages[0].height == 842.0
    
    normalizer = OCRNormalizer()
    normalized = normalizer.normalize_evidence(evidence)
    assert normalized.pages[0].status == "OCR_REQUIRED"
    
    sha_after = compute_sha256(scanned_pdf_path)
    assert sha_before == sha_after, "Original PDF was mutated!"


def test_mixed_pdf_page_level_status(mixed_pdf_path):
    sha_before = compute_sha256(mixed_pdf_path)
    val_doc = load_and_validate_document(mixed_pdf_path)
    
    inspector = PDFInspector()
    insp_res = inspector.inspect(val_doc)
    assert insp_res.total_pages == 2
    assert insp_res.direct_text_pages_count == 1
    assert insp_res.ocr_required_pages_count == 1
    assert insp_res.is_mixed_pdf is True
    
    extractor = OCREvidenceExtractor()
    evidence = extractor._extract_pymupdf_evidence(val_doc, insp_res)
    assert len(evidence.pages) == 2
    assert evidence.pages[0].status == "DIRECT_TEXT"
    assert "Page 1 Digital Text Content" in evidence.pages[0].raw_text
    
    assert evidence.pages[1].status == "OCR_REQUIRED"
    assert evidence.pages[1].raw_text == ""
    assert evidence.pages[1].width == 595.0
    assert evidence.pages[1].height == 842.0
    
    normalizer = OCRNormalizer()
    normalized = normalizer.normalize_evidence(evidence)
    assert normalized.pages[0].status == "DIRECT_TEXT"
    assert normalized.pages[1].status == "OCR_REQUIRED"
    assert normalized.processing_metadata["is_mixed_pdf"] is True
    assert normalized.processing_metadata["direct_text_pages_count"] == 1
    assert normalized.processing_metadata["ocr_required_pages_count"] == 1
    
    sha_after = compute_sha256(mixed_pdf_path)
    assert sha_before == sha_after, "Original PDF was mutated!"

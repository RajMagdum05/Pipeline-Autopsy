import hashlib
from pathlib import Path
import pytest
from PIL import Image
import pymupdf as fitz

from app.services.ocr.page_renderer import PDFPageRenderer, RenderedPageImage
from app.services.ocr.document_loader import load_and_validate_document


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    h.update(filepath.read_bytes())
    return h.hexdigest()


@pytest.fixture
def scanned_pdf_path(tmp_path) -> Path:
    pdf_file = tmp_path / "scanned_doc.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.Rect(0, 0, 100, 100), False)
    pix.clear_with(240)
    page.insert_image(fitz.Rect(50, 50, 250, 250), pixmap=pix)
    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


@pytest.fixture
def mixed_pdf_path(tmp_path) -> Path:
    pdf_file = tmp_path / "mixed_doc.pdf"
    doc = fitz.open()
    
    # Page 1: Digital
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 50), "Page 1 Digital Text", fontsize=12)
    
    # Page 2: Scanned Image (no text)
    page2 = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.Rect(0, 0, 100, 100), False)
    pix.clear_with(200)
    page2.insert_image(fitz.Rect(50, 50, 200, 200), pixmap=pix)
    
    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


def test_render_scanned_pdf_pages(scanned_pdf_path, tmp_path):
    sha_before = compute_sha256(scanned_pdf_path)
    val_doc = load_and_validate_document(scanned_pdf_path)
    
    output_dir = tmp_path / "ocr_artifacts"
    renderer = PDFPageRenderer(storage_root=output_dir)
    rendered_images = renderer.render_ocr_required_pages(val_doc, document_id=701)
    
    assert len(rendered_images) == 1
    meta = rendered_images[0]
    assert meta.document_id == 701
    assert meta.page_number == 1
    assert meta.dpi == 300
    assert meta.width_px == 2480  # 595 pt @ 300 DPI
    assert meta.height_px == 3509  # 842 pt @ 300 DPI
    
    img_file = Path(meta.image_path)
    assert img_file.exists()
    assert img_file.stat().st_size > 0
    
    with Image.open(img_file) as pil_img:
        assert pil_img.size == (2480, 3509)
        assert pil_img.format == "PNG"
        
    sha_after = compute_sha256(scanned_pdf_path)
    assert sha_before == sha_after, "Original PDF was mutated!"


def test_render_mixed_pdf_pages(mixed_pdf_path, tmp_path):
    sha_before = compute_sha256(mixed_pdf_path)
    val_doc = load_and_validate_document(mixed_pdf_path)
    
    output_dir = tmp_path / "ocr_artifacts"
    renderer = PDFPageRenderer(storage_root=output_dir)
    rendered_images = renderer.render_ocr_required_pages(val_doc, document_id=702)
    
    # Only Page 2 is OCR_REQUIRED, so only 1 image should be rendered
    assert len(rendered_images) == 1
    meta = rendered_images[0]
    assert meta.document_id == 702
    assert meta.page_number == 2
    assert meta.dpi == 300
    
    img_file = Path(meta.image_path)
    assert img_file.exists()
    assert "page_2.png" in img_file.name
    
    sha_after = compute_sha256(mixed_pdf_path)
    assert sha_before == sha_after, "Original PDF was mutated!"

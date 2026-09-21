import hashlib
from pathlib import Path
import pytest
from PIL import Image
import pymupdf as fitz

from app.services.ocr.page_renderer import PDFPageRenderer
from app.services.ocr.image_preprocessor import DocumentImagePreprocessor, PreprocessedImageResult
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
    pix.clear_with(220)
    page.insert_image(fitz.Rect(50, 50, 250, 250), pixmap=pix)
    doc.save(str(pdf_file))
    doc.close()
    return pdf_file


def test_image_preprocessing_pipeline(scanned_pdf_path, tmp_path):
    sha_pdf_before = compute_sha256(scanned_pdf_path)
    val_doc = load_and_validate_document(scanned_pdf_path)
    
    # 1. Render page image
    out_dir = tmp_path / "ocr_artifacts"
    renderer = PDFPageRenderer(storage_root=out_dir)
    rendered_list = renderer.render_ocr_required_pages(val_doc, document_id=801)
    assert len(rendered_list) == 1
    rendered_item = rendered_list[0]
    
    orig_png_file = Path(rendered_item.image_path)
    sha_png_before = compute_sha256(orig_png_file)
    
    # 2. Preprocess page image
    preprocessor = DocumentImagePreprocessor()
    res: PreprocessedImageResult = preprocessor.preprocess_rendered_page(rendered_item)
    
    assert res.status == "success"
    assert res.document_id == 801
    assert res.page_number == 1
    assert res.applied_steps == [
        "grayscale",
        "contrast_enhancement",
        "noise_reduction_sharpening",
        "soft_binarization",
    ]
    
    prep_png_file = Path(res.preprocessed_image_path)
    assert prep_png_file.exists()
    assert prep_png_file != orig_png_file
    assert res.file_size_bytes > 0
    
    # Verify PIL image mode is Grayscale ('L') and dimensions are uncropped
    with Image.open(prep_png_file) as img:
        assert img.mode == "L"
        assert img.size == (res.width_px, res.height_px)
        
    # Verify original PDF and original rendered PNG are completely unchanged
    sha_pdf_after = compute_sha256(scanned_pdf_path)
    sha_png_after = compute_sha256(orig_png_file)
    
    assert sha_pdf_before == sha_pdf_after, "Original PDF was mutated!"
    assert sha_png_before == sha_png_after, "Original rendered PNG was mutated!"

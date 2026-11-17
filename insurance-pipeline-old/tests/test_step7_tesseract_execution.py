import hashlib
from pathlib import Path
import pytest
from PIL import Image
import pymupdf as fitz

from app.services.ocr.page_renderer import PDFPageRenderer
from app.services.ocr.image_preprocessor import DocumentImagePreprocessor
from app.services.ocr.tesseract_provider import (
    TesseractOCRProvider,
    StructuredPageResult,
    StructuredLineResult,
    StructuredWordResult,
    run_tesseract_on_preprocessed_page,
)
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


def test_tesseract_result_structures():
    word = StructuredWordResult(
        text="INVOICE",
        confidence=96.5,
        bounding_box={"x0": 50.0, "y0": 37.0, "x1": 120.0, "y1": 55.0},
    )
    assert word.text == "INVOICE"
    assert word.confidence == 96.5
    assert word.bounding_box == {"x0": 50.0, "y0": 37.0, "x1": 120.0, "y1": 55.0}

    line = StructuredLineResult(
        text="INVOICE #99001",
        confidence=95.0,
        bounding_box={"x0": 50.0, "y0": 37.0, "x1": 250.0, "y1": 55.0},
        words=[word],
    )
    assert line.text == "INVOICE #99001"
    assert line.confidence == 95.0
    assert len(line.words) == 1

    page = StructuredPageResult(
        document_id=901,
        page_number=1,
        image_path="/tmp/preprocessed_page_1.png",
        ocr_text="INVOICE #99001",
        lines=[line],
        words=[word],
    )
    assert page.document_id == 901
    assert page.page_number == 1
    assert page.image_path == "/tmp/preprocessed_page_1.png"
    assert page.ocr_text == "INVOICE #99001"
    assert len(page.words) == 1
    assert page.words[0].text == "INVOICE"


def test_tesseract_execution_on_preprocessed_page(scanned_pdf_path, tmp_path):
    sha_pdf_before = compute_sha256(scanned_pdf_path)
    val_doc = load_and_validate_document(scanned_pdf_path)

    # 1. Render OCR_REQUIRED page
    out_dir = tmp_path / "ocr_artifacts"
    renderer = PDFPageRenderer(storage_root=out_dir)
    rendered_list = renderer.render_ocr_required_pages(val_doc, document_id=902)
    assert len(rendered_list) == 1
    rendered_item = rendered_list[0]

    sha_png_before = compute_sha256(Path(rendered_item.image_path))

    # 2. Preprocess page image
    preprocessor = DocumentImagePreprocessor()
    prep_res = preprocessor.preprocess_rendered_page(rendered_item, document_id=902)
    sha_prep_before = compute_sha256(Path(prep_res.preprocessed_image_path))

    # 3. Execute Tesseract OCR on preprocessed image
    provider = TesseractOCRProvider()
    res: StructuredPageResult = provider.process_preprocessed_image(prep_res)

    assert res.document_id == 902
    assert res.page_number == 1
    assert res.image_path == prep_res.preprocessed_image_path
    assert isinstance(res.ocr_text, str)
    assert isinstance(res.words, list)
    assert isinstance(res.lines, list)

    # Verify original files were left strictly untouched
    sha_pdf_after = compute_sha256(scanned_pdf_path)
    sha_png_after = compute_sha256(Path(rendered_item.image_path))
    sha_prep_after = compute_sha256(Path(prep_res.preprocessed_image_path))

    assert sha_pdf_before == sha_pdf_after, "Original PDF was mutated!"
    assert sha_png_before == sha_png_after, "Original rendered PNG was mutated!"
    assert sha_prep_before == sha_prep_after, "Preprocessed PNG was mutated!"

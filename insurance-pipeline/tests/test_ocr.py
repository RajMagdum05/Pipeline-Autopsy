from pathlib import Path
import pymupdf as fitz
from app.services.document_processor import process_document, extract_text_from_document, OCRResult


def create_sample_pdf(output_path: Path):
    """Generates a simple sample text PDF file for testing text extraction."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    sample_text = (
        "HEALTH INSURANCE CLAIM INVOICE\n"
        "----------------------------------------\n"
        "Claim ID: 101\n"
        "Patient Name: Rahul Sharma\n"
        "Diagnosis: Acute Appendicitis\n"
        "Total Claim Amount: $50,000.00\n"
        "Hospital: City Care Hospital\n"
        "Status: Processing\n"
    )
    page.insert_text((50, 50), sample_text, fontsize=12)
    doc.save(output_path)
    doc.close()


def test_ocr_sample_claim_invoice(tmp_path: Path):
    sample_pdf_path = tmp_path / "sample_claim_invoice.pdf"
    create_sample_pdf(sample_pdf_path)

    ocr_result: OCRResult = process_document(sample_pdf_path, document_id="claim_101")

    assert isinstance(ocr_result, OCRResult)
    assert ocr_result.engine == "pymupdf"
    assert len(ocr_result.pages) == 1
    assert ocr_result.pages[0].page_number == 1
    assert "HEALTH INSURANCE CLAIM INVOICE" in ocr_result.pages[0].raw_text
    assert len(ocr_result.pages[0].lines) > 0

    legacy_text = extract_text_from_document(sample_pdf_path)
    assert "HEALTH INSURANCE CLAIM INVOICE" in legacy_text


if __name__ == "__main__":
    test_pdf = Path("storage") / "sample_claim_invoice.pdf"
    create_sample_pdf(test_pdf)
    res = process_document(test_pdf, document_id="claim_101")
    print(f"Sample PDF processing succeeded: engine={res.engine}, pages={len(res.pages)}")

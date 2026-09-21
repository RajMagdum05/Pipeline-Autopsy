import pytest
from app.schemas import OCRResult, OCRPage, OCRLine, OCRWord
from app.services.ocr.quality_validator import OCRQualityValidator
from app.services.extraction_service import (
    build_claim_extraction_input,
    format_llm_prompt_from_payload,
    extract_claim_from_validated_ocr,
    ClaimOCRInputPayload,
)


def test_build_claim_extraction_input_multi_doc_filtering():
    """
    Test gathering validated OCR results for a claim across multiple documents,
    verifying FAIL pages (empty/unreadable) are omitted while PASS/WARNING pages are included.
    """
    claim_id = 777

    # Document 1: Digital invoice with 1 PASS page and 1 empty FAIL page
    doc1_ocr = OCRResult(
        document_id=101,
        engine="pymupdf",
        pages=[
            OCRPage(
                document_id=101,
                page_number=1,
                raw_text="HEALTH INSURANCE CLAIM INVOICE #INV-8812\nPatient: Anita Roy\nHospital: City General Hospital\nDate: 2026-08-10\nAmount: $45,000.00",
                extraction_method="DIRECT_TEXT",
                status="DIRECT_TEXT",
                lines=[
                    OCRLine(text="HEALTH INSURANCE CLAIM INVOICE #INV-8812", words=[OCRWord(text="HEALTH", bounding_box={"x0": 10, "y0": 10, "x1": 50, "y1": 20})]),
                ],
            ),
            OCRPage(
                document_id=101,
                page_number=2,
                raw_text="",  # Empty page -> FAIL validation
                extraction_method="DIRECT_TEXT",
                status="DIRECT_TEXT",
                lines=[],
            ),
        ],
    )

    # Document 2: Scanned lab report with 1 WARNING page (low confidence text)
    doc2_ocr = OCRResult(
        document_id=102,
        engine="tesseract",
        pages=[
            OCRPage(
                document_id=102,
                page_number=1,
                raw_text="LAB REPORT\nPatient: Anita Roy\nDiagnosis: Acute Gastritis\nTreatment: Intravenous Fluids",
                extraction_method="TESSERACT_OCR",
                status="OCR_REQUIRED",
                lines=[
                    OCRLine(text="LAB REPORT", confidence=55.0, words=[OCRWord(text="LAB", confidence=55.0, bounding_box={"x0": 10, "y0": 10, "x1": 30, "y1": 20})]),
                ],
            )
        ],
    )

    documents = [
        {"id": 101, "claim_id": claim_id, "document_type": "invoice", "file_name": "invoice_8812.pdf", "ocr_result": doc1_ocr},
        {"id": 102, "claim_id": claim_id, "document_type": "lab_report", "file_name": "lab_report.pdf", "ocr_result": doc2_ocr},
    ]

    payload = build_claim_extraction_input(claim_id=claim_id, documents=documents)

    assert isinstance(payload, ClaimOCRInputPayload)
    assert payload.claim_id == claim_id
    assert payload.total_documents == 2
    assert payload.total_validated_pages == 2  # Doc 1 Pg 1 + Doc 2 Pg 1 (Doc 1 Pg 2 empty omitted)

    # Check preserved attributes
    assert payload.validated_pages[0].document_id == 101
    assert payload.validated_pages[0].page_number == 1
    assert payload.validated_pages[0].extraction_method == "DIRECT_TEXT"
    assert "Anita Roy" in payload.validated_pages[0].raw_text

    assert payload.validated_pages[1].document_id == 102
    assert payload.validated_pages[1].page_number == 1
    assert payload.validated_pages[1].extraction_method == "TESSERACT_OCR"


def test_format_llm_prompt_no_bounding_box_clutter():
    """
    Test LLM prompt formatting excludes word-level bounding box coordinates
    while preserving claim, document, and page context.
    """
    claim_id = 888
    doc_ocr = OCRResult(
        document_id=201,
        engine="pymupdf",
        pages=[
            OCRPage(
                document_id=201,
                page_number=1,
                raw_text="INVOICE #12345 Patient: John Doe Amount: $500",
                extraction_method="DIRECT_TEXT",
                status="DIRECT_TEXT",
                lines=[
                    OCRLine(
                        text="INVOICE #12345 Patient: John Doe Amount: $500",
                        words=[OCRWord(text="INVOICE", bounding_box={"x0": 50, "y0": 100, "x1": 150, "y1": 120})],
                    )
                ],
            )
        ],
    )
    documents = [
        {"id": 201, "claim_id": claim_id, "document_type": "bill", "file_name": "bill.pdf", "ocr_result": doc_ocr}
    ]

    payload = build_claim_extraction_input(claim_id=claim_id, documents=documents)
    prompt = format_llm_prompt_from_payload(payload)

    # Must contain document context & raw text
    assert f"Target Claim ID: #{claim_id}" in prompt
    assert "DOCUMENT #201" in prompt
    assert "PAGE #1" in prompt
    assert "INVOICE #12345 Patient: John Doe Amount: $500" in prompt

    # Must NOT contain bounding box details
    assert "bounding_box" not in prompt
    assert "x0" not in prompt
    assert "y0" not in prompt


def test_extract_claim_from_validated_ocr_output_boundary():
    """
    Test full extraction execution produces structured claim result with:
    - Predefined fields
    - Controlled additional_information dictionary
    - Traceable source references with document/page numbers
    """
    claim_id = 999
    doc1_ocr = OCRResult(
        document_id=301,
        engine="pymupdf",
        pages=[
            OCRPage(
                document_id=301,
                page_number=1,
                raw_text="INVOICE #99001\nPatient: Rahul Sharma\nHospital: Metro Hospital\nDate: 2026-09-15\nAmount: $75,000.00",
                extraction_method="DIRECT_TEXT",
                status="DIRECT_TEXT",
                lines=[],
            )
        ],
    )
    doc2_ocr = OCRResult(
        document_id=302,
        engine="tesseract",
        pages=[
            OCRPage(
                document_id=302,
                page_number=1,
                raw_text="CLINICAL SUMMARY\nPatient: Rahul Sharma\nDiagnosis: Acute Appendicitis\nTreatment: Laparoscopic Appendectomy",
                extraction_method="TESSERACT_OCR",
                status="OCR_REQUIRED",
                lines=[],
            )
        ],
    )

    documents = [
        {"id": 301, "claim_id": claim_id, "document_type": "invoice", "file_name": "medical_invoice.pdf", "ocr_result": doc1_ocr},
        {"id": 302, "claim_id": claim_id, "document_type": "clinical_summary", "file_name": "clinical_summary.pdf", "ocr_result": doc2_ocr},
    ]

    res = extract_claim_from_validated_ocr(claim_id=claim_id, documents=documents)

    assert res.claim_id == claim_id
    assert res.patient_name == "Rahul Sharma"
    assert res.hospital == "Metro Hospital"
    assert res.diagnosis == "Acute Appendicitis"
    assert res.treatment == "Laparoscopic Appendectomy"
    assert res.date == "2026-09-15"
    assert float(res.amount) == 75000.0

    # Verify additional information defined place
    assert isinstance(res.additional_information, dict)
    assert "invoice_number" in res.additional_information

    # Verify source context retained
    assert len(res.source_references) >= 5
    for ref in res.source_references:
        assert ref.document_id in (301, 302)
        assert ref.page_number >= 1
        assert ref.field_name in ["patient_name", "hospital", "diagnosis", "treatment", "date", "amount", "invoice_number"]

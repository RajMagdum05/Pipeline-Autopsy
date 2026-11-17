import pytest
from app.schemas import OCRResult, OCRPage, OCRLine, OCRWord
from app.services.ocr.quality_validator import (
    OCRQualityValidator,
    OCRValidationConfig,
    OCRPageValidationResult,
    OCRDocumentValidationResult,
    validate_ocr_quality,
)


def test_scenario_a_good_scanned_page():
    page = OCRPage(
        page_number=1,
        raw_text="HEALTH INSURANCE CLAIM INVOICE #99001 Patient: Test Customer Total Bill: $1,250.00",
        extraction_method="TESSERACT_OCR",
        status="OCR_REQUIRED",
        lines=[
            OCRLine(
                text="HEALTH INSURANCE CLAIM INVOICE #99001",
                confidence=95.0,
                words=[
                    OCRWord(text="HEALTH", confidence=98.0, bounding_box={"x0": 50, "y0": 37, "x1": 97, "y1": 53}),
                    OCRWord(text="INSURANCE", confidence=96.0, bounding_box={"x0": 100, "y0": 37, "x1": 170, "y1": 53}),
                    OCRWord(text="CLAIM", confidence=97.0, bounding_box={"x0": 175, "y0": 37, "x1": 220, "y1": 53}),
                    OCRWord(text="INVOICE", confidence=95.0, bounding_box={"x0": 225, "y0": 37, "x1": 270, "y1": 53}),
                ],
            )
        ],
    )
    doc = OCRResult(document_id=201, engine="tesseract", pages=[page])
    validator = OCRQualityValidator()
    res = validator.validate_document(doc)

    assert res.overall_status == "PASS"
    assert res.passed_pages_count == 1
    assert res.failed_pages_count == 0
    assert res.warning_pages_count == 0
    assert res.avg_document_confidence == 96.5
    assert res.page_validations[0].status == "PASS"


def test_scenario_b_poor_quality_ocr():
    page = OCRPage(
        page_number=1,
        raw_text="H3aLth InsUr4nc3 C1a1m Inv01c3",
        extraction_method="TESSERACT_OCR",
        status="OCR_REQUIRED",
        lines=[
            OCRLine(
                text="H3aLth InsUr4nc3 C1a1m Inv01c3",
                confidence=42.0,
                words=[
                    OCRWord(text="H3aLth", confidence=45.0, bounding_box={"x0": 50, "y0": 37, "x1": 97, "y1": 53}),
                    OCRWord(text="InsUr4nc3", confidence=38.0, bounding_box={"x0": 100, "y0": 37, "x1": 170, "y1": 53}),
                    OCRWord(text="C1a1m", confidence=32.0, bounding_box={"x0": 175, "y0": 37, "x1": 220, "y1": 53}),
                ],
            )
        ],
    )
    doc = OCRResult(document_id=202, engine="tesseract", pages=[page])
    validator = OCRQualityValidator()
    res = validator.validate_document(doc)

    assert res.overall_status == "WARNING"
    assert res.warning_pages_count == 1
    assert res.failed_pages_count == 0
    assert "below pass threshold" in res.page_validations[0].reasons[0]


def test_scenario_c_empty_unreadable_page():
    page = OCRPage(
        page_number=1,
        raw_text="",
        extraction_method="TESSERACT_OCR",
        status="OCR_REQUIRED",
        lines=[],
    )
    doc = OCRResult(document_id=203, engine="tesseract", pages=[page])
    validator = OCRQualityValidator()
    res = validator.validate_document(doc)

    assert res.overall_status == "FAIL"
    assert res.failed_pages_count == 1
    assert res.page_validations[0].status == "FAIL"
    assert "0 extractable words" in res.page_validations[0].reasons[0]


def test_scenario_d_digital_pdf_direct_text():
    page = OCRPage(
        page_number=1,
        raw_text="Medical Invoice Detail Patient: Rahul Sharma Amount: $75,000.00",
        extraction_method="DIRECT_TEXT",
        status="DIRECT_TEXT",
        lines=[
            OCRLine(
                text="Medical Invoice Detail Patient: Rahul Sharma",
                confidence=None,
                words=[
                    OCRWord(text="Medical", confidence=None, bounding_box={"x0": 50, "y0": 37, "x1": 97, "y1": 53}),
                    OCRWord(text="Invoice", confidence=None, bounding_box={"x0": 100, "y0": 37, "x1": 150, "y1": 53}),
                    OCRWord(text="Detail", confidence=None, bounding_box={"x0": 155, "y0": 37, "x1": 200, "y1": 53}),
                ],
            )
        ],
    )
    doc = OCRResult(document_id=204, engine="pymupdf", pages=[page])
    validator = OCRQualityValidator()
    res = validator.validate_document(doc)

    assert res.overall_status == "PASS"
    assert res.passed_pages_count == 1
    assert res.page_validations[0].status == "PASS"
    assert res.page_validations[0].confidence_score == 100.0


def test_scenario_e_multipage_rollup():
    page_pass = OCRPage(
        page_number=1,
        raw_text="HEALTH INSURANCE CLAIM INVOICE #99001 Patient: Test Customer Total Bill: $1,250.00",
        extraction_method="TESSERACT_OCR",
        status="OCR_REQUIRED",
        lines=[
            OCRLine(
                text="HEALTH INSURANCE CLAIM INVOICE",
                confidence=95.0,
                words=[
                    OCRWord(text="HEALTH", confidence=95.0),
                    OCRWord(text="INSURANCE", confidence=95.0),
                    OCRWord(text="CLAIM", confidence=95.0),
                ],
            )
        ],
    )
    page_fail = OCRPage(
        page_number=2,
        raw_text="",
        extraction_method="TESSERACT_OCR",
        status="OCR_REQUIRED",
        lines=[],
    )
    doc = OCRResult(document_id=205, engine="tesseract", pages=[page_pass, page_fail])
    validator = OCRQualityValidator()
    res = validator.validate_document(doc)

    assert res.overall_status == "FAIL"
    assert res.total_pages == 2
    assert res.passed_pages_count == 1
    assert res.failed_pages_count == 1

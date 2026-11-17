"""Unit tests for the reused OCR quality validator; confidence values are engine scores, not probabilities."""
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.document_processing.evidence_extractor import OCREvidenceExtractor
from app.document_processing.quality_validator import OCRQualityValidator, OCRValidationConfig
from app.document_processing.schemas import OCRLine, OCRPage, OCRWord


def _page(text, confidences, *, method="TESSERACT_OCR", status="TESSERACT_OCR"):
    words = [OCRWord(text=word, confidence=confidence) for word, confidence in zip(text.split(), confidences)]
    return OCRPage(page_number=1, raw_text=text, extraction_method=method, status=status,
        lines=[OCRLine(text=text, words=words)])


def test_high_and_low_engine_confidence_are_distinct_from_quality_metrics():
    validator = OCRQualityValidator()
    high = validator.validate_page(_page("CLAIM NUMBER 12345 APPROVED", [95, 92, 98, 90]))
    low = validator.validate_page(_page("CLAIM NUMBER 12345 APPROVED", [25, 30, 22, 28]))
    assert high.confidence_score == 93.75
    assert high.confidence_scale == "0-100 Tesseract score; not a probability"
    assert high.confidence_source.startswith("pytesseract.image_to_data")
    assert high.quality_metrics["character_count"] == len("CLAIM NUMBER 12345 APPROVED")
    assert low.status == "FAIL"
    assert low.disposition == "RETRY_REQUIRED"
    assert low.low_confidence_word_count == 4


def test_native_confidence_is_unavailable_and_never_invented():
    result = OCRQualityValidator().validate_page(_page(
        "HbA1c 6.5 percent", [], method="DIRECT_TEXT", status="DIRECT_TEXT"))
    assert result.confidence_score is None
    assert result.confidence_word_count == 0
    assert result.confidence_source.startswith("unavailable: PyMuPDF")
    assert any("no confidence value was inferred" in reason for reason in result.reasons)


def test_empty_tokens_and_negative_sentinels_are_excluded_from_confidence():
    page = OCRPage(page_number=1, raw_text="CLAIM DATA VALID", extraction_method="TESSERACT_OCR",
        lines=[OCRLine(text="CLAIM DATA VALID", words=[
            OCRWord(text="CLAIM", confidence=90), OCRWord(text="", confidence=-1),
            OCRWord(text="DATA", confidence=-1), OCRWord(text="VALID", confidence=88),
        ])])
    result = OCRQualityValidator().validate_page(page)
    assert result.confidence_word_count == 2
    assert result.confidence_missing_word_count == 1
    assert result.confidence_score == 89
    assert result.confidence_coverage == pytest.approx(2 / 3)


def test_bad_page_is_not_hidden_by_high_document_average():
    from app.document_processing.schemas import OCRResult
    pages = [
        _page("HEALTH INSURANCE CLAIM PATIENT DETAILS", [95, 94, 96, 97, 93]),
        OCRPage(page_number=2, raw_text="CLAIM UNREADABLE", extraction_method="TESSERACT_OCR",
            lines=[OCRLine(text="CLAIM UNREADABLE", words=[OCRWord(text="CLAIM", confidence=20), OCRWord(text="UNREADABLE", confidence=25)])]),
    ]
    report = OCRQualityValidator().validate_document(OCRResult(engine="tesseract", pages=pages))
    assert report.avg_document_confidence is not None and report.avg_document_confidence > 60
    assert report.page_validations[1].status == "FAIL"
    assert report.overall_status == "FAIL"
    assert report.disposition == "RETRY_REQUIRED"


def test_native_garble_is_flagged_but_short_valid_medical_numeric_text_is_not_garbage():
    validator = OCRQualityValidator()
    garbled = validator.validate_page(_page("\ufffd" * 30 + " data", [], method="DIRECT_TEXT", status="DIRECT_TEXT"))
    short_valid = validator.validate_page(_page("HbA1c 6.5%", [], method="DIRECT_TEXT", status="DIRECT_TEXT"))
    assert garbled.status == "FAIL"
    assert any("Suspicious character proportion" in reason for reason in garbled.reasons)
    assert short_valid.status == "WARNING"
    assert short_valid.disposition == "RETRY_REQUIRED"
    assert short_valid.confidence_score is None


def test_blank_and_unreadable_are_distinct_and_threshold_boundaries_are_explicit():
    validator = OCRQualityValidator(OCRValidationConfig(min_character_count=3, min_word_count=1,
        min_avg_confidence_warning=35, min_avg_confidence_pass=60,
        low_confidence_cutoff=0, max_low_confidence_ratio=1))
    blank = validator.validate_page(OCRPage(page_number=1, raw_text="", extraction_method="BLANK", status="BLANK"))
    unreadable = validator.validate_page(OCRPage(page_number=1, raw_text="", extraction_method="TESSERACT_OCR", status="UNREADABLE"))
    at_warning_boundary = validator.validate_page(_page("WORD DATA", [35, 35]))
    at_pass_boundary = validator.validate_page(_page("WORD DATA", [60, 60]))
    assert blank.status == "BLANK" and blank.disposition == "ACCEPTED"
    assert unreadable.status == "FAIL" and unreadable.disposition == "RETRY_REQUIRED"
    assert at_warning_boundary.status == "WARNING"
    assert at_pass_boundary.status == "PASS"


def test_real_tesseract_ground_truth_when_runtime_is_available(tmp_path):
    pytesseract = pytest.importorskip("pytesseract")
    try:
        pytesseract.get_tesseract_version()
        if "eng" not in pytesseract.get_languages(config=""):
            pytest.skip("English Tesseract trained data is unavailable")
    except Exception:
        pytest.skip("Tesseract OCR runtime is unavailable")
    image = Image.new("RGB", (1200, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 90), "GROUNDTRUTH CLAIM 12345", fill="black", font=ImageFont.load_default(size=42))
    result = OCREvidenceExtractor()._ocr_page(image, 1)
    assert "GROUNDTRUTH" in result.raw_text.upper()
    assert "12345" in result.raw_text

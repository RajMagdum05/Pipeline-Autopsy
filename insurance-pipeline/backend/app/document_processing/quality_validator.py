from typing import List, Union, Optional, Dict, Any
import math
from pydantic import BaseModel, Field
import autopsy_sdk as autopsy

from app.document_processing.schemas import OCRResult, OCRPage, OCRLine, OCRWord


class OCRValidationConfig(BaseModel):
    """
    Configurable threshold values for deterministic OCR Quality Validation.
    """
    min_character_count: int = Field(default=15, description="Minimum extracted character threshold per page")
    min_word_count: int = Field(default=3, description="Minimum recognized word threshold per page")
    min_avg_confidence_pass: float = Field(default=60.0, description="Minimum average word confidence for PASS (0-100)")
    min_avg_confidence_warning: float = Field(default=35.0, description="Minimum average word confidence for WARNING (0-100)")
    require_alphanumeric: bool = Field(default=True, description="Require at least one alphanumeric character per page")
    require_page_number: bool = Field(default=True, description="Require page_number metadata")
    low_confidence_cutoff: float = Field(default=60.0)
    max_low_confidence_ratio: float = Field(default=0.5)
    max_suspicious_char_ratio: float = Field(default=0.02)


class OCRPageValidationResult(BaseModel):
    """
    Validation status and metrics for a single page OCR result.
    """
    page_number: int = Field(..., description="1-based page number")
    status: str = Field(..., description="Validation status: 'PASS', 'WARNING', or 'FAIL'")
    confidence_score: Optional[float] = Field(default=None, description="Average word-level confidence score (0-100)")
    word_count: int = Field(..., description="Count of recognized words on page")
    character_count: int = Field(..., description="Count of extracted text characters")
    reasons: List[str] = Field(default_factory=list, description="Human-readable validation decision reasons")
    disposition: str = "ACCEPTED"
    confidence_source: str | None = None
    confidence_scale: str | None = None
    confidence_word_count: int = 0
    confidence_missing_word_count: int = 0
    confidence_coverage: float | None = None
    low_confidence_word_count: int = 0
    low_confidence_word_proportion: float | None = None
    aggregation_method: str | None = None
    quality_metrics: Dict[str, Any] = Field(default_factory=dict)


class OCRDocumentValidationResult(BaseModel):
    """
    Document-level OCR Quality Validation summary.
    """
    document_id: Optional[Union[int, str]] = Field(default=None, description="Document ID")
    overall_status: str = Field(..., description="Document overall status: 'PASS', 'WARNING', or 'FAIL'")
    total_pages: int = Field(..., description="Total pages evaluated")
    passed_pages_count: int = Field(..., description="Count of PASS pages")
    warning_pages_count: int = Field(..., description="Count of WARNING pages")
    failed_pages_count: int = Field(..., description="Count of FAIL pages")
    avg_document_confidence: Optional[float] = Field(default=None, description="Document average OCR confidence")
    page_validations: List[OCRPageValidationResult] = Field(default_factory=list, description="Per-page validations")
    disposition: str = "ACCEPTED"
    confidence_word_count: int = 0
    confidence_missing_word_count: int = 0
    confidence_coverage: float | None = None
    low_confidence_word_count: int = 0
    low_confidence_word_proportion: float | None = None
    aggregation_method: str = "weighted arithmetic mean over valid word confidences"
    validation_reasons: List[str] = Field(default_factory=list)


class OCRQualityValidator:
    """
    Deterministic OCR Quality Validator.
    
    Evaluates page-level and document-level OCR quality against configurable thresholds,
    generating status ratings (PASS, WARNING, FAIL) and explicit explanatory reasons.
    """

    def __init__(self, config: Optional[OCRValidationConfig] = None):
        self.config = config or OCRValidationConfig()

    def validate_page(self, page: Union[OCRPage, Dict[str, Any]]) -> OCRPageValidationResult:
        """
        Validates quality of a single OCRPage result.

        Args:
            page: OCRPage instance or dict representation.

        Returns:
            OCRPageValidationResult: Page validation status, calculated confidence, and reasons.
        """
        if isinstance(page, dict):
            page_obj = OCRPage(**page)
        else:
            page_obj = page

        reasons: List[str] = []
        is_fail = False
        is_warning = False

        # 1. Structure & Metadata Check
        if self.config.require_page_number and (page_obj.page_number is None or page_obj.page_number <= 0):
            reasons.append("Invalid or missing page_number metadata.")
            is_fail = True

        raw_text = (page_obj.raw_text or "").strip()
        char_count = len(raw_text)

        # Extract words from lines
        words: List[OCRWord] = []
        for line in page_obj.lines:
            words.extend(line.words)

        words = [word for word in words if word.text.strip()]
        word_count = len(words) if words else len(raw_text.split())
        valid_confidences = [float(word.confidence) for word in words
            if word.confidence is not None and math.isfinite(float(word.confidence))
            and 0.0 <= float(word.confidence) <= 100.0]

        # 2. Meaningful Text Presence Check
        if char_count == 0 or word_count == 0:
            reasons.append("Page contains 0 extractable words/characters (empty text).")
            is_fail = True

        if self.config.require_alphanumeric and raw_text and not any(c.isalnum() for c in raw_text):
            reasons.append("Page text contains no alphanumeric characters.")
            is_fail = True

        # 3. Minimum Content Threshold Check
        if char_count > 0 and char_count < self.config.min_character_count:
            reasons.append(
                f"Character count ({char_count}) is below minimum threshold ({self.config.min_character_count})."
            )
            is_warning = True

        if word_count > 0 and word_count < self.config.min_word_count:
            reasons.append(
                f"Word count ({word_count}) is below minimum threshold ({self.config.min_word_count})."
            )
            is_warning = True

        # 4. Word-Level Confidence Calculation
        confidences = valid_confidences
        avg_confidence: Optional[float] = None

        if confidences:
            avg_confidence = round(sum(confidences) / len(confidences), 2)
            if avg_confidence < self.config.min_avg_confidence_warning:
                reasons.append(
                    f"Average word confidence ({avg_confidence}%) is below failure threshold ({self.config.min_avg_confidence_warning}%)."
                )
                is_fail = True
            elif avg_confidence < self.config.min_avg_confidence_pass:
                reasons.append(
                    f"Average word confidence ({avg_confidence}%) is below pass threshold ({self.config.min_avg_confidence_pass}%)."
                )
                is_warning = True
        elif page_obj.extraction_method not in {"DIRECT_TEXT", "BLANK"} and word_count:
            reasons.append("OCR engine confidence was unavailable for recognized text.")
            is_warning = True

        low_confidence_count = sum(value < self.config.low_confidence_cutoff for value in confidences)
        low_confidence_ratio = low_confidence_count / len(confidences) if confidences else None
        if low_confidence_ratio is not None and low_confidence_ratio > self.config.max_low_confidence_ratio:
            reasons.append(f"Low-confidence word proportion ({low_confidence_ratio:.3f}) exceeds configured maximum ({self.config.max_low_confidence_ratio:.3f}).")
            is_fail = True

        suspicious_count = sum(1 for char in raw_text if char == "\ufffd" or (not char.isprintable() and not char.isspace()))
        suspicious_ratio = suspicious_count / max(len(raw_text), 1)
        if suspicious_ratio > self.config.max_suspicious_char_ratio:
            reasons.append(f"Suspicious character proportion ({suspicious_ratio:.3f}) exceeds configured maximum ({self.config.max_suspicious_char_ratio:.3f}).")
            is_fail = True

        normalized_lines = [" ".join(line.text.casefold().split()) for line in page_obj.lines if line.text.strip()]
        duplicate_count = len(normalized_lines) - len(set(normalized_lines))
        duplicate_ratio = duplicate_count / max(len(normalized_lines), 1)
        if len(normalized_lines) > 1 and duplicate_ratio > 0.5:
            reasons.append("Repeated identical lines may indicate duplicated extraction output.")
            is_warning = True

        # Determine Status
        if page_obj.status == "BLANK":
            status = "BLANK"
            reasons.append("Page was classified as genuinely blank by the document extractor.")
        elif is_fail:
            status = "FAIL"
        elif is_warning:
            status = "WARNING"
        else:
            status = "PASS"
            reasons.append(f"Text passed configured extraction-quality checks ({char_count} characters, {word_count} words).")

        if status == "PASS":
            disposition = "ACCEPTED"
        elif status == "BLANK":
            disposition = "ACCEPTED"
        elif status in {"WARNING", "FAIL"}:
            retry_markers = (
                "below minimum threshold", "below failure threshold", "below pass threshold",
                "Low-confidence word proportion", "OCR engine confidence was unavailable",
                "Suspicious character proportion",
            )
            retryable = (page_obj.status in {"UNREADABLE", "PARTIAL_FAILURE"}
                or any(any(marker in reason for marker in retry_markers) for reason in reasons))
            disposition = "RETRY_REQUIRED" if retryable else "HUMAN_REVIEW_REQUIRED"
        else:
            disposition = "HUMAN_REVIEW_REQUIRED"
        if page_obj.status in {"UNREADABLE", "PARTIAL_FAILURE"}:
            disposition = "RETRY_REQUIRED"
            reasons.append("Page extraction reported an unreadable or partial OCR failure.")

        confidence_word_count = len(confidences)
        confidence_missing_word_count = max(word_count - confidence_word_count, 0)
        confidence_coverage = confidence_word_count / word_count if word_count else None
        confidence_source = "pytesseract.image_to_data TSV word confidence" if confidence_word_count else None
        if page_obj.extraction_method == "DIRECT_TEXT":
            confidence_source = "unavailable: PyMuPDF native extraction does not provide recognition confidence"
            reasons.append("Recognition confidence is unavailable for native PDF text; no confidence value was inferred.")
        elif not confidence_word_count and word_count:
            confidence_source = "unavailable: no valid word-level OCR confidence returned"

        return OCRPageValidationResult(
            page_number=page_obj.page_number,
            status=status,
            confidence_score=avg_confidence,
            word_count=word_count,
            character_count=char_count,
            reasons=reasons,
            disposition=disposition,
            confidence_source=confidence_source,
            confidence_scale="0-100 Tesseract score; not a probability" if confidence_word_count else None,
            confidence_word_count=confidence_word_count,
            confidence_missing_word_count=confidence_missing_word_count,
            confidence_coverage=confidence_coverage,
            low_confidence_word_count=low_confidence_count,
            low_confidence_word_proportion=low_confidence_ratio,
            aggregation_method="arithmetic mean of valid, nonempty word confidence values" if confidence_word_count else None,
            quality_metrics={"character_count": char_count, "word_count": word_count,
                "suspicious_character_count": suspicious_count, "suspicious_character_ratio": suspicious_ratio,
                "duplicate_line_count": duplicate_count, "duplicate_line_ratio": duplicate_ratio},
        )

    def validate_document(
        self,
        ocr_result: Union[OCRResult, Dict[str, Any]],
        claim_id: Optional[Union[int, str]] = None,
        execution_id: Optional[str] = None,
    ) -> OCRDocumentValidationResult:
        """
        Validates quality of an entire document OCRResult across all pages.

        Args:
            ocr_result: OCRResult instance or dict representation.

        Returns:
            OCRDocumentValidationResult: Document-level validation status and per-page validation breakdown.
        """
        if isinstance(ocr_result, dict):
            res_obj = OCRResult(**ocr_result)
        else:
            res_obj = ocr_result

        with autopsy.operation("ocr_validation.document") as span:

            page_validations: List[OCRPageValidationResult] = []
            conf_scores: List[float] = []
            confidence_words = confidence_missing_words = low_confidence_words = total_words = 0
            pass_count = 0
            warn_count = 0
            fail_count = 0

            for page in res_obj.pages:
                page_res = self.validate_page(page)
                page_validations.append(page_res)

                if page_res.status == "PASS":
                    pass_count += 1
                elif page_res.status == "WARNING":
                    warn_count += 1
                elif page_res.status == "FAIL":
                    fail_count += 1

                if page_res.confidence_score is not None:
                    conf_scores.extend([w.confidence for line in page.lines for w in line.words
                        if w.text.strip() and w.confidence is not None and math.isfinite(float(w.confidence))
                        and 0.0 <= float(w.confidence) <= 100.0])
                confidence_words += page_res.confidence_word_count
                confidence_missing_words += page_res.confidence_missing_word_count
                low_confidence_words += page_res.low_confidence_word_count
                total_words += page_res.word_count

            total_pages = len(res_obj.pages)

            # Rollup overall document status
            content_validations = [page for page in page_validations if page.status != "BLANK"]
            if not content_validations or fail_count > 0:
                overall_status = "FAIL"
            elif warn_count > 0:
                overall_status = "WARNING"
            else:
                overall_status = "PASS"

            avg_doc_conf = round(sum(conf_scores) / len(conf_scores), 2) if conf_scores else None
            confidence_coverage = confidence_words / total_words if total_words else None
            low_confidence_ratio = low_confidence_words / confidence_words if confidence_words else None

            # OCR metrics belong to the result model. The SDK operation deliberately
            # carries no document, claim, or extracted-content values.

            nonblank = [result for result in page_validations if result.status != "BLANK"]
            if not nonblank:
                disposition = "HUMAN_REVIEW_REQUIRED"
            elif any(result.disposition == "RETRY_REQUIRED" for result in nonblank):
                disposition = "RETRY_REQUIRED"
            elif any(result.disposition == "HUMAN_REVIEW_REQUIRED" for result in nonblank):
                disposition = "HUMAN_REVIEW_REQUIRED"
            elif all(result.disposition == "ACCEPTED" for result in nonblank):
                disposition = "ACCEPTED"
            else:
                disposition = "FAILED"
            reasons = [f"Page {result.page_number}: {reason}" for result in page_validations for reason in result.reasons]

            return OCRDocumentValidationResult(
                document_id=res_obj.document_id,
                overall_status=overall_status,
                total_pages=total_pages,
                passed_pages_count=pass_count,
                warning_pages_count=warn_count,
                failed_pages_count=fail_count,
                avg_document_confidence=avg_doc_conf,
                page_validations=page_validations,
                disposition=disposition,
                confidence_word_count=confidence_words,
                confidence_missing_word_count=confidence_missing_words,
                confidence_coverage=confidence_coverage,
                low_confidence_word_count=low_confidence_words,
                low_confidence_word_proportion=low_confidence_ratio,
                validation_reasons=reasons,
            )


def validate_ocr_quality(
    ocr_result: Union[OCRResult, Dict[str, Any]],
    config: Optional[OCRValidationConfig] = None,
) -> OCRDocumentValidationResult:
    """Convenience function to validate document OCR quality."""
    validator = OCRQualityValidator(config=config)
    return validator.validate_document(ocr_result)

from typing import List, Union, Optional, Dict, Any
from pydantic import BaseModel, Field
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from app.telemetry.attributes import (
    EXECUTION_ENTITY_ID,
    EXECUTION_ID,
    ERROR_MESSAGE,
    ERROR_TYPE,
    INPUT_ARTIFACT_IDS,
    OUTPUT_ARTIFACT_IDS,
    STAGE_STATUS,
)
from app.telemetry.span_helpers import stage_span

tracer = trace.get_tracer("enterprise_pipeline.ocr_validation")

from app.schemas import OCRResult, OCRPage, OCRLine, OCRWord


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

        word_count = len(words) if words else len(raw_text.split())

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
        confidences = [w.confidence for w in words if w.confidence is not None]
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
        else:
            # Native PyMuPDF or no confidence available
            if page_obj.extraction_method == "DIRECT_TEXT" and char_count >= self.config.min_character_count:
                avg_confidence = 100.0  # High confidence native digital text

        # Determine Status
        if is_fail:
            status = "FAIL"
        elif is_warning:
            status = "WARNING"
        else:
            status = "PASS"
            reasons.append(
                f"Valid text ({char_count} chars, {word_count} words)"
                + (f" with {avg_confidence}% confidence." if avg_confidence is not None else ".")
            )

        return OCRPageValidationResult(
            page_number=page_obj.page_number,
            status=status,
            confidence_score=avg_confidence,
            word_count=word_count,
            character_count=char_count,
            reasons=reasons,
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

        parent_attrs = getattr(trace.get_current_span(), "attributes", {}) or {}
        resolved_claim_id = claim_id or parent_attrs.get(EXECUTION_ENTITY_ID) or "unknown"
        resolved_execution_id = execution_id or parent_attrs.get(EXECUTION_ID) or "exec_unknown"
        doc_artifact_ids = [f"art_ocr_{res_obj.document_id}"] if res_obj.document_id is not None else []
        with stage_span(
            tracer=tracer,
            stage_name="ocr_validation",
            span_name="ocr_validation.document",
            execution_id=resolved_execution_id,
            entity_id=str(resolved_claim_id),
            input_artifact_ids=doc_artifact_ids,
            extra_attributes={"document_id": res_obj.document_id} if res_obj.document_id is not None else None,
            safe_error_message="OCR document validation failed.",
        ) as span:
            if res_obj.document_id is not None:
                span.set_attribute("document_id", res_obj.document_id)

            page_validations: List[OCRPageValidationResult] = []
            conf_scores: List[float] = []
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
                    conf_scores.append(page_res.confidence_score)

            total_pages = len(res_obj.pages)

            # Rollup overall document status
            if total_pages == 0 or fail_count > 0:
                overall_status = "FAIL"
            elif warn_count > 0:
                overall_status = "WARNING"
            else:
                overall_status = "PASS"

            avg_doc_conf = round(sum(conf_scores) / len(conf_scores), 2) if conf_scores else None

            span.set_attribute("validation.overall_status", overall_status)
            span.set_attribute("validation.total_pages", total_pages)
            span.set_attribute("validation.passed_pages_count", pass_count)
            span.set_attribute("validation.warning_pages_count", warn_count)
            span.set_attribute("validation.failed_pages_count", fail_count)
            span.set_attribute(
                OUTPUT_ARTIFACT_IDS,
                [f"art_ocr_val_{res_obj.document_id}"] if res_obj.document_id is not None else [],
            )
            if avg_doc_conf is not None:
                span.set_attribute("validation.avg_confidence", avg_doc_conf)

            if overall_status == "FAIL":
                span.set_attribute(STAGE_STATUS, "failed")
                span.set_attribute(ERROR_TYPE, "OCRQualityValidationError")
                span.set_attribute(ERROR_MESSAGE, "OCR quality validation failed.")
                span.set_status(Status(StatusCode.ERROR, "OCR quality validation failed."))

            return OCRDocumentValidationResult(
                document_id=res_obj.document_id,
                overall_status=overall_status,
                total_pages=total_pages,
                passed_pages_count=pass_count,
                warning_pages_count=warn_count,
                failed_pages_count=fail_count,
                avg_document_confidence=avg_doc_conf,
                page_validations=page_validations,
            )


def validate_ocr_quality(
    ocr_result: Union[OCRResult, Dict[str, Any]],
    config: Optional[OCRValidationConfig] = None,
) -> OCRDocumentValidationResult:
    """Convenience function to validate document OCR quality."""
    validator = OCRQualityValidator(config=config)
    return validator.validate_document(ocr_result)

"""Deterministic, opt-in fault hooks used by synthetic demos and tests."""

from contextlib import contextmanager
from contextvars import ContextVar
import os

from app.document_processing.exceptions import DocumentProcessingError


FAULTS = frozenset({
    "none", "clean_rejection", "ocr_misread_bill_date", "extraction_wrong_date_uncaught",
    "extraction_hallucinate_caught", "policy_ocr_unreadable", "gemini_unavailable",
    "classification_mismatch", "final_mismatch",
})
_ACTIVE = ContextVar("pipeline_autopsy_fault", default=None)


def enabled():
    return os.getenv("FAULT_INJECTION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def active_fault():
    return _ACTIVE.get()


@contextmanager
def activate(name=None):
    """Scope a requested fault to one request; ignore all faults by default."""
    if not enabled() or not name or name == "none":
        yield None
        return
    if name not in FAULTS:
        raise ValueError(f"Unknown fault injection: {name}")
    token = _ACTIVE.set(name)
    try:
        yield name
    finally:
        _ACTIVE.reset(token)


def before_llm(stage, item, response_schema=None):
    """Return a deterministic fixture response or raise a simulated provider error."""
    fault = active_fault()
    if not fault or stage != "content_classification":
        return None
    if fault == "gemini_unavailable" and item.get("role") == "hospital_bill":
        raise DocumentProcessingError(
            "Gemini request failed with a simulated unavailable response.",
            error_class="infra", code="GENAI_REQUEST_FAILED",
        )
    if fault == "classification_mismatch" and item.get("role") == "hospital_bill":
        from app.information_extraction.schemas import Classification, EvidenceQuote

        quotes = []
        for page in item.get("pages", []):
            text = str(page.get("text", "")).strip()
            if not text:
                continue
            quote = text[: min(80, len(text))]
            quotes.append(EvidenceQuote(page_number=int(page["page_number"]), quote=quote))
            if len(quotes) == 2:
                break
            if len(text) > len(quote):
                quotes.append(EvidenceQuote(
                    page_number=int(page["page_number"]), quote=text[-min(80, len(text)):],
                ))
                if len(quotes) == 2:
                    break
        return Classification(
            detected_type="discharge_summary", subtype="discharge_summary",
            disposition="accepted", evidence=quotes,
        )
    return None


def after_text_extraction(item, pages, metrics):
    """Apply deterministic OCR text/quality faults to mutable normalized results."""
    fault = active_fault()
    role = item.get("role") if isinstance(item, dict) else None
    if fault == "ocr_misread_bill_date" and role == "hospital_bill":
        for page in pages:
            page.raw_text = page.raw_text.replace("2025-03-02", "2024-03-02")
        metrics["low_confidence_word_proportion"] = 0.62
        for quality in metrics.get("page_validations", []):
            quality["low_confidence_word_proportion"] = 0.62
            quality["status"] = "WARNING"
            quality["disposition"] = "ACCEPTED"
            quality.setdefault("reasons", []).append("Synthetic OCR misread quality warning.")
        metrics["overall_status"] = "WARNING"
    elif fault == "policy_ocr_unreadable" and role == "policy_document":
        for page in pages:
            page.raw_text = ""
        metrics["low_confidence_word_proportion"] = 1.0
        metrics["overall_status"] = "FAIL"
        for quality in metrics.get("page_validations", []):
            quality["character_count"] = 0
            quality["word_count"] = 0
            quality["low_confidence_word_proportion"] = 1.0
            quality["status"] = "FAIL"
            quality["disposition"] = "RETRY_REQUIRED"
            quality.setdefault("reasons", []).append("Synthetic unreadable policy fixture.")
    return pages, metrics


def after_extraction(item, facts):
    """Inject a false admission date for the two grounding scenarios."""
    fault = active_fault()
    if fault not in {"extraction_wrong_date_uncaught", "extraction_hallucinate_caught"}:
        return facts
    if item.get("role") != "hospital_bill":
        return facts
    for fact in facts:
        if fact.field_name == "admission_date" and fact.field_status in {"found", "conflicting"}:
            fact.raw_value = "2024-03-02"
            fact.normalized_value = "2024-03-02"
            if fact.evidence:
                fact.evidence[0].quote = "Admission Date: 2024-03-02"
            break
    return facts


def validator_overrides(item):
    """Deliberately simulate a quote-check coverage gap for one named scenario."""
    if (active_fault() == "extraction_wrong_date_uncaught"
            and item.get("role") == "hospital_bill"):
        return {"skip_quote_fields": {"admission_date"}}
    return {}


def after_adjudication(decision):
    """Flip a final decision only for the explicit final-result fault."""
    if active_fault() != "final_mismatch":
        return decision
    verdict = "REJECTED" if decision.decision == "APPROVED" else "APPROVED"
    return decision.model_copy(update={"decision": verdict})


__all__ = [
    "FAULTS", "activate", "active_fault", "after_adjudication",
    "after_extraction", "after_text_extraction", "before_llm", "enabled",
    "validator_overrides",
]

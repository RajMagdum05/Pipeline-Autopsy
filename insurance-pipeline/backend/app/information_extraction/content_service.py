"""Tool-free, document-scoped semantic validation and structured extraction."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
from threading import BoundedSemaphore, Lock
import time
import re

from app.document_processing.exceptions import DocumentProcessingError
from app.telemetry.attributes import (
    MODEL_NAME, OUTPUT_ARTIFACT_IDS, PROMPT_VERSION, STAGE_STATUS,
    VALIDATION_RESULT, VALIDATION_RULE_ID, VALIDATION_STATUS,
)
from app.telemetry.span_helpers import stage_span
from app.information_extraction.schemas import (
    ALLOWED_FIELDS, REPEATABLE_FIELDS, EXTRACTION_SCHEMAS, POLICY_SUBTYPE_SCHEMAS,
    Classification, DocumentExtraction, ExtractionValidationReport, ValidationCheck, ValidationIssue,
)
from opentelemetry import trace

BASE = Path(__file__).resolve().parent
CLASSIFIER_PROMPT_VERSION = "content-classification-v1"
EXTRACTION_PROMPT_VERSION = "document-extraction-v2"
SCHEMA_VERSION = "document-facts-v1"
EXTRACTION_VALIDATOR_VERSION = "basic-extraction-validation-v1"
GEMINI_SCHEMA_ADAPTER_VERSION = "gemini-json-schema-v4"
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
DEFAULT_CURRENCY_TOLERANCES = {"INR": "0.01", "USD": "0.01", "EUR": "0.01", "GBP": "0.01", "JPY": "1"}

DATE_FIELDS = {
    "issue_date", "date_of_birth", "coverage_start", "coverage_end", "first_inception",
    "endorsement_effective_date", "incident_date", "report_date", "invoice_date",
    "admission_date", "discharge_date", "service_date", "specimen_date", "consultation_date",
    "estimate_date", "document_date", "event_date", "treatment_date",
}
MONEY_FIELDS = {
    "sum_insured", "bonus", "additional_cover", "amount", "item_amount", "line_item_amount",
    "subtotal", "taxes", "discount", "credits", "total", "deposits", "balance",
    "rate", "estimated_total",
}


def _now():
    return datetime.now(timezone.utc)


def _normal(text: str) -> str:
    return " ".join((text or "").split())


def _decimal_value(value: str | None) -> Decimal | None:
    if value is None:
        return None
    cleaned = value.strip()
    cleaned = re.sub(r"^(?:INR|USD|EUR|GBP|JPY)\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("₹", "").replace("$", "").replace("€", "").replace("£", "").strip()
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", cleaned):
        return None
    try:
        number = Decimal(cleaned.replace(",", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _iso_date(value: str | None) -> date | None:
    if not value or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_unambiguous_raw_date(value: str | None) -> date | None:
    if not value:
        return None
    iso = _iso_date(value.strip())
    if iso:
        return iso
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", value.strip())
    if not match:
        return None
    first, second, year = map(int, match.groups())
    if first <= 12 and second <= 12:
        return None
    day, month = (first, second) if first > 12 else (second, first)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def page_batches(pages: list[dict], max_chars: int, max_pages: int) -> list[list[dict]]:
    """Bound requests without truncating; every source page is returned once."""
    batches, current, size = [], [], 0
    for page in pages:
        text = page["text"]
        if len(text) > max_chars:
            raise DocumentProcessingError("A single page exceeds CONTENT_MAX_BATCH_CHARS; manual review is required.")
        if current and (len(current) >= max_pages or size + len(text) > max_chars):
            batches.append(current)
            current, size = [], 0
        current.append(page)
        size += len(text)
    if current:
        batches.append(current)
    return batches


class DocumentContentService:
    def __init__(self, model: str | None = None):
        self.model = model or MODEL
        self.max_chars = max(1000, min(int(os.getenv("CONTENT_MAX_BATCH_CHARS", "24000")), 40000))
        self.max_pages = max(1, min(int(os.getenv("CONTENT_MAX_BATCH_PAGES", "4")), 10))
        self._semaphore = BoundedSemaphore(max(1, min(int(os.getenv("GEMINI_MAX_CONCURRENCY", "3")), 8)))
        self._client_lock = Lock()
        self._gemini_client = None
        self._genai_types = None

    def _client(self):
        if self._gemini_client is not None and self._genai_types is not None:
            return self._gemini_client, self._genai_types
        with self._client_lock:
            if self._gemini_client is not None and self._genai_types is not None:
                return self._gemini_client, self._genai_types
            return self._create_client()

    @staticmethod
    def _gemini_response_schema(response_schema) -> dict:
        """Return a Gemini Developer API compatible schema.

        Gemini's legacy response_schema field uses a narrower OpenAPI schema.
        The current response_json_schema accepts JSON Schema but only a subset
        of its keywords. The response is still validated against the original
        strict Pydantic model after generation.
        """
        schema = response_schema.model_json_schema()

        # Gemini rejects the 500-item facts cap. Keep small array bounds, omit
        # larger ones from the remote schema; strict local Pydantic caps remain.
        unsupported = {"additionalProperties", "additional_properties", "default", "minLength", "maxLength", "pattern", "minProperties", "maxProperties"}

        def adapt(node):
            if isinstance(node, dict):
                for key in unsupported:
                    node.pop(key, None)
                if node.get("maxItems", 0) > 20:
                    node.pop("maxItems", None)
                if "const" in node:
                    node["enum"] = [node.pop("const")]
                for value in node.values():
                    adapt(value)
            elif isinstance(node, list):
                for value in node:
                    adapt(value)

        adapt(schema)
        # Gemini rejects this deeply nested optional detail on the classifier's
        # component array. Component page ranges/types still classify mixed
        # documents; top-level evidence remains required and locally verified.
        if schema.get("title") == "Classification":
            component_items = schema.get("$defs", {}).get("DocumentComponent", {})
            component_items.get("properties", {}).pop("evidence", None)
            schema["required"] = list(dict.fromkeys([*schema.get("required", []), "evidence"]))
            schema["properties"]["evidence"]["minItems"] = 2
        else:
            schema["required"] = list(dict.fromkeys([*schema.get("required", []), "facts"]))
            schema["properties"]["facts"]["minItems"] = 1
        extracted_fact = schema.get("$defs", {}).get("ExtractedFact", {})
        if extracted_fact:
            extracted_fact["required"] = list(dict.fromkeys([*extracted_fact.get("required", []), "evidence"]))
            extracted_fact["properties"]["evidence"]["minItems"] = 1
            document_field = response_schema.model_fields.get("document_type")
            document_type = document_field.default if document_field is not None else None
            if document_type in ALLOWED_FIELDS:
                extracted_fact["properties"]["field_name"]["enum"] = sorted(ALLOWED_FIELDS[document_type])
        return schema

    def _create_client(self):
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise DocumentProcessingError("Semantic processing is unavailable: configure GEMINI_API_KEY (or GOOGLE_API_KEY) server-side.")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise DocumentProcessingError("Semantic processing is unavailable: install the google-genai backend dependency.") from exc
        timeout_ms = max(1000, int(float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "45")) * 1000))
        self._gemini_client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=timeout_ms,
            retry_options=types.HttpRetryOptions(attempts=1)))
        self._genai_types = types
        return self._gemini_client, self._genai_types

    def _request(self, prompt: str, response_schema):
        client, types = self._client()
        attempts = max(1, min(int(os.getenv("GEMINI_MAX_ATTEMPTS", "2")), 2))
        if not self._semaphore.acquire(timeout=float(os.getenv("GEMINI_QUEUE_TIMEOUT_SECONDS", "10"))):
            raise DocumentProcessingError("Gemini request capacity is busy; retry the document later.")
        try:
            for attempt in range(attempts):
                try:
                    response = client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_json_schema=self._gemini_response_schema(response_schema),
                            tools=[],
                        ),
                    )
                    candidates = getattr(response, "candidates", None) or []
                    finish = str(getattr(candidates[0], "finish_reason", "") if candidates else "").upper()
                    if "MAX_TOKENS" in finish:
                        raise DocumentProcessingError("Gemini structured response was truncated by the output limit.")
                    if "SAFETY" in finish or "PROHIBITED" in finish:
                        raise DocumentProcessingError("Gemini refused the structured request.")
                    text = getattr(response, "text", None)
                    if not text:
                        raise DocumentProcessingError("Gemini returned an empty structured response.")
                    return response_schema.model_validate_json(text)
                except DocumentProcessingError:
                    raise
                except Exception as exc:
                    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                    status_text = str(status).upper()
                    retryable = (status in (408, 409, 429, 500, 502, 503, 504)
                        or any(token in status_text for token in ("RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL"))
                        or isinstance(exc, (TimeoutError, ConnectionError)))
                    if attempt + 1 >= attempts or not retryable:
                        raise DocumentProcessingError(f"Gemini structured request failed ({type(exc).__name__}).") from exc
                    time.sleep(min(2 ** attempt, 2))
        finally:
            self._semaphore.release()

    @staticmethod
    def _text(pages: list[dict]) -> str:
        # JSON quoting keeps OCR strings from forging page/delimiter boundaries.
        return json.dumps([{"page_number": page["page_number"], "text": page["text"]}
            for page in pages], ensure_ascii=False)

    @staticmethod
    def _check_quotes(payload: dict, pages: list[dict]) -> list[str]:
        source = {int(page["page_number"]): _normal(page["text"]) for page in pages}
        errors = []
        for evidence in payload.get("evidence", []):
            number = int(evidence.get("page_number", -1))
            if number not in source or _normal(evidence.get("quote", "")) not in source.get(number, ""):
                errors.append(f"Unsupported classification quote or page reference: page {number}.")
        for component in payload.get("components", []):
            start, end = int(component.get("page_start", -1)), int(component.get("page_end", -1))
            if start > end or start not in source or end not in source:
                errors.append(f"Unsupported component page range: {start}-{end}.")
            for evidence in component.get("evidence", []):
                number = int(evidence.get("page_number", -1))
                if number not in source or _normal(evidence.get("quote", "")) not in source.get(number, ""):
                    errors.append(f"Unsupported component quote or page reference: page {number}.")
        for fact in payload.get("facts", []):
            for evidence in fact.get("evidence", []):
                number = int(evidence.get("page_number", -1))
                if number not in source or _normal(evidence.get("quote", "")) not in source.get(number, ""):
                    errors.append(f"Unsupported evidence for {fact.get('field_name', 'field')}: page {number}.")
        return errors

    def classify(self, pages: list[dict], declared_type: str) -> tuple[Classification, dict]:
        batches = page_batches(pages, self.max_chars, self.max_pages)
        if not batches:
            return Classification(detected_type="unreadable", disposition="unreadable", reasons=["No usable OCR text was supplied."]), {"processed_pages": []}
        template = (BASE / "prompts" / "classification_v1.txt").read_text(encoding="utf-8")
        results, evidence_errors = [], []
        for batch in batches:
            prompt = f"{template}\nDECLARED_TYPE={declared_type}\nDOCUMENT_TEXT_JSON:\n{self._text(batch)}"
            result = self._request(prompt, Classification)
            errors = self._check_quotes(result.model_dump(), batch)
            evidence_errors.extend(errors)
            results.append(result)
        types_found = {item.detected_type for item in results}
        subtypes_found = {item.subtype for item in results if item.subtype}
        quotes_ok = not evidence_errors
        if len(types_found) > 1 or len(subtypes_found) > 1:
            merged = Classification(detected_type="mixed_document", subtype=None, disposition="review_required",
                reasons=["Page batches produced conflicting document classifications."],
                evidence=[item for result in results for item in result.evidence], ambiguity=["Classification differs between page batches."])
        else:
            merged = results[0].model_copy(deep=True)
            merged.evidence = [item for result in results for item in result.evidence]
            merged.components = [item for result in results for item in result.components]
            merged.reasons = list(dict.fromkeys(reason for result in results for reason in result.reasons))
            merged.ambiguity = list(dict.fromkeys(reason for result in results for reason in result.ambiguity))
            if not quotes_ok:
                merged.disposition = "review_required"
                merged.reasons.extend(evidence_errors)
            if merged.detected_type != declared_type and merged.detected_type not in {"unknown", "unsupported", "mixed_document", "unreadable"}:
                merged.disposition = "mismatch"
                merged.reasons.append("Detected type differs from the declared upload type; explicit correction/review is required.")
            if merged.detected_type in {"unknown", "unsupported", "mixed_document", "unreadable"}:
                merged.disposition = "unsupported" if merged.detected_type == "unsupported" else "review_required" if merged.detected_type in {"unknown", "mixed_document"} else "unreadable"
            if len(merged.components) > 1:
                merged.disposition = "review_required"
                merged.reasons.append("Multiple components were detected; automated segmentation and rerouting are not enabled, so split/review is required.")
            if merged.disposition == "accepted" and len({_normal(item.quote) for item in merged.evidence}) < 2:
                merged.disposition = "review_required"
                merged.reasons.append("Classification did not provide evidence from multiple contextual signals.")
            if declared_type == "policy_document" and merged.subtype in {"brochure", "proposal", "application", "quote", "quotation", "premium_receipt", "payment_receipt", "unrelated"}:
                merged.disposition = "mismatch"
                merged.reasons.append("This document is not an issued policy schedule/certificate, policy wording, or endorsement.")
        return merged, {"processed_pages": [p["page_number"] for p in pages], "batch_count": len(batches), "evidence_errors": evidence_errors}

    def extract(self, pages: list[dict], detected_type: str, subtype: str | None) -> tuple[DocumentExtraction, dict]:
        if detected_type not in EXTRACTION_SCHEMAS:
            raise DocumentProcessingError("The classified document type has no extraction schema; human review is required.")
        if detected_type == "policy_document":
            lowered_subtype = (subtype or "").lower()
            schema = next((candidate for marker, candidate in POLICY_SUBTYPE_SCHEMAS.items() if marker in lowered_subtype), EXTRACTION_SCHEMAS[detected_type])
        else:
            schema = EXTRACTION_SCHEMAS[detected_type]
        template_dir = BASE / "prompts" / "extraction_v2"
        common_instructions = (template_dir / "base.txt").read_text(encoding="utf-8")
        type_instructions = (template_dir / f"{detected_type}.txt").read_text(encoding="utf-8")
        template = f"{common_instructions.strip()}\n\n{type_instructions.strip()}"
        batches = page_batches(pages, self.max_chars, self.max_pages)
        if not batches:
            raise DocumentProcessingError("No source pages are available for extraction.")
        expected_page_numbers = [int(page["page_number"]) for page in pages]
        submitted_page_numbers = [int(page["page_number"]) for batch in batches for page in batch]
        page_coverage_complete = submitted_page_numbers == expected_page_numbers
        all_facts, warnings = [], []
        validation_errors = [] if page_coverage_complete else ["The extraction request did not cover every source page in order."]
        for batch in batches:
            prompt = (f"{template}\nDETECTED_TYPE={detected_type}\nDETECTED_SUBTYPE={subtype or 'unknown'}\n"
                      f"DOCUMENT_TEXT_JSON:\n{self._text(batch)}")
            result = self._request(prompt, schema)
            payload = result.model_dump()
            validation_errors.extend(self._check_quotes(payload, batch))
            for fact in payload["facts"]:
                if fact["field_name"] not in ALLOWED_FIELDS[detected_type]:
                    validation_errors.append(f"Unsupported field name: {fact['field_name']}.")
                if fact["field_status"] in {"found", "conflicting"} and not fact.get("raw_value"):
                    validation_errors.append(f"Found/conflicting field has no raw value: {fact['field_name']}.")
                if fact["field_status"] in {"found", "conflicting"} and not fact.get("evidence"):
                    validation_errors.append(f"Found/conflicting field has no source evidence: {fact['field_name']}.")
                if fact["field_status"] in {"found", "conflicting"} and fact.get("raw_value") and fact.get("evidence"):
                    raw_value = _normal(fact["raw_value"]).casefold()
                    if not any(raw_value in _normal(item.get("quote", "")).casefold() for item in fact["evidence"]):
                        validation_errors.append(f"Raw value is not contained in its quoted evidence: {fact['field_name']}.")
                if fact["field_status"] in {"missing", "not_applicable"} and fact.get("evidence"):
                    validation_errors.append(f"Missing/not-applicable field has source evidence: {fact['field_name']}.")
                if fact["field_status"] in {"missing", "not_applicable", "unreadable"} and (fact.get("raw_value") or fact.get("normalized_value")):
                    validation_errors.append(f"{fact['field_status']} field contains a value: {fact['field_name']}.")
                if fact["field_status"] == "found" and fact.get("normalized_value") and not fact.get("raw_value"):
                    validation_errors.append(f"Normalized value has no source value: {fact['field_name']}.")
                self._validate_normalized(fact, validation_errors)
            all_facts.extend(payload["facts"])
            warnings.extend(payload["warnings"])
        observed = {fact["field_name"] for fact in all_facts}
        all_facts.extend({"field_name": field, "raw_value": None, "normalized_value": None,
            "field_status": "missing", "evidence": [], "warning": None}
            for field in sorted(ALLOWED_FIELDS[detected_type] - observed))
        if not any(fact.get("field_status") in {"found", "conflicting"} for fact in all_facts):
            validation_errors.append("No source-backed information fields were extracted; human review is required.")
        by_name = {}
        for fact in all_facts:
            by_name.setdefault(fact["field_name"], []).append(fact)
        conflicts = []
        consistency_warnings = []
        for name, values in by_name.items():
            distinct = {_normal(item.get("raw_value") or "") for item in values if item.get("field_status") == "found"}
            if name not in REPEATABLE_FIELDS and len(distinct) > 1:
                conflicts.append(name)
            if any(item.get("field_status") == "conflicting" for item in values) and name not in REPEATABLE_FIELDS:
                conflicts.append(name)
        conflicts = list(dict.fromkeys(conflicts))
        if conflicts:
            for fact in all_facts:
                if fact["field_name"] in conflicts and fact["field_status"] == "found":
                    fact["field_status"] = "conflicting"
                    fact["warning"] = "Different values were found in separate pages/batches; no precedence was inferred."
            warnings.append("Conflicting source values: " + ", ".join(conflicts))
            validation_errors.append("Conflicting values require review: " + ", ".join(conflicts))
        # Source totals are not reconciled against line items: invoices may omit
        # components, include deposits/credits, or use a different subtotal basis.
        if detected_type == "hospital_bill":
            subtotals = [fact.get("normalized_value") for fact in all_facts
                if fact.get("field_name") == "subtotal" and fact.get("field_status") == "found"]
            totals = [fact.get("normalized_value") for fact in all_facts
                if fact.get("field_name") == "total" and fact.get("field_status") == "found"]
            taxes = [fact.get("normalized_value") for fact in all_facts
                if fact.get("field_name") == "taxes" and fact.get("field_status") == "found"]
            discounts = [fact.get("normalized_value") for fact in all_facts
                if fact.get("field_name") == "discount" and fact.get("field_status") == "found"]
            credits = [fact.get("normalized_value") for fact in all_facts
                if fact.get("field_name") == "credits" and fact.get("field_status") == "found"]
            if subtotals and totals and (taxes or discounts or credits):
                try:
                    currency_facts = [fact for fact in all_facts if fact.get("field_name") == "currency" and fact.get("field_status") == "found"]
                    currency = currency_facts[0].get("normalized_value") if len(currency_facts) == 1 else None
                    tolerance_raw = os.getenv("EXTRACTION_CURRENCY_TOLERANCE_" + str(currency), DEFAULT_CURRENCY_TOLERANCES.get(currency, "")) if currency else ""
                    try:
                        tolerance = Decimal(tolerance_raw) if tolerance_raw else None
                        if tolerance is not None and (not tolerance.is_finite() or tolerance < 0):
                            tolerance = None
                    except InvalidOperation:
                        tolerance = None
                    expected_total = _decimal_value(subtotals[0])
                    components = [*taxes, *credits]
                    if discounts:
                        components.extend(discounts)
                    parsed_components = [_decimal_value(value) for value in components]
                    actual_total = _decimal_value(totals[0])
                    if tolerance is None or expected_total is None or actual_total is None or any(value is None for value in parsed_components):
                        consistency_warnings.append("Bill arithmetic was not evaluated because currency or component values were ambiguous.")
                    else:
                        for fact in all_facts:
                            if fact.get("field_name") in {"discount", "credits"} and fact.get("field_status") == "found":
                                parsed = _decimal_value(fact.get("normalized_value"))
                                if parsed is not None:
                                    expected_total -= abs(parsed)
                        for fact in all_facts:
                            if fact.get("field_name") == "taxes" and fact.get("field_status") == "found":
                                parsed = _decimal_value(fact.get("normalized_value"))
                                if parsed is not None:
                                    expected_total += parsed
                    if tolerance is not None and abs(expected_total - actual_total) > tolerance:
                        message = "Reported subtotal, taxes, discounts, and total do not reconcile; source amounts were preserved unchanged."
                        consistency_warnings.append(message)
                        validation_errors.append(message)
                except (InvalidOperation, AttributeError):
                    consistency_warnings.append("Reported bill totals could not be reconciled using normalized decimal values.")
        data = {"subtype": subtype or "unknown", "facts": all_facts,
            "warnings": list(dict.fromkeys([*warnings, *consistency_warnings]))}
        if detected_type == "policy_document" and schema is not EXTRACTION_SCHEMAS[detected_type]:
            data["policy_subtype"] = schema.model_fields["policy_subtype"].default
        if detected_type == "other_supporting_document" and (subtype or "").strip().lower() in {"", "unknown", "unsupported", "unrelated"}:
            validation_errors.append("The other supporting document has no meaningful classified subtype.")
        # Date ordering checks run only when both canonical values are present.
        ordering_pairs = [("coverage_start", "coverage_end")] if detected_type == "policy_document" else [("admission_date", "discharge_date")] if detected_type in {"hospital_bill", "discharge_summary"} else []
        for start_name, end_name in ordering_pairs:
            starts = [f for f in all_facts if f.get("field_name") == start_name and f.get("field_status") == "found"]
            ends = [f for f in all_facts if f.get("field_name") == end_name and f.get("field_status") == "found"]
            if len(starts) == len(ends) == 1:
                start_date, end_date = _iso_date(starts[0].get("normalized_value")), _iso_date(ends[0].get("normalized_value"))
                if start_date and end_date and start_date > end_date:
                    validation_errors.append(f"{start_name} is after {end_name}; source values are preserved for review.")
        return schema.model_validate(data), {"status": "passed" if not validation_errors else "review_required",
            "reasons": list(dict.fromkeys(validation_errors)), "processed_pages": [p["page_number"] for p in pages],
            "expected_pages": expected_page_numbers,
            "page_coverage_complete": page_coverage_complete,
            "batch_count": len(batches), "conflicting_fields": conflicts,
            "consistency_warnings": consistency_warnings}

    def process_and_persist(self, db, processed, normalized, *, declared_type: str, checksum: str) -> str:
        """Classify/extract only the persisted pages for this accepted, current OCR attempt."""
        from app.document_processing.models import ProcessedPage, SemanticArtifact
        from app.claim_document_intake.models import ClaimDocument, IntakeClaim, Document

        if processed.status != "COMPLETED" or processed.disposition != "ACCEPTED":
            raise DocumentProcessingError("Semantic extraction requires an OCR attempt that passed its quality gate.")
        if processed.checksum_sha256 != checksum or processed.role != declared_type:
            raise DocumentProcessingError("Semantic extraction attempt does not match the current document version and declared role.")
        intake = db.query(ClaimDocument).filter_by(id=processed.intake_document_id, claim_id=processed.claim_id).one_or_none()
        claim = db.query(IntakeClaim).filter_by(claim_id=processed.claim_id).one_or_none()
        legacy = db.query(Document).filter_by(id=processed.document_id).one_or_none()
        if (intake is None or claim is None or legacy is None or claim.legacy_id != legacy.claim_id
                or intake.checksum_sha256 != checksum or intake.document_type != declared_type
                or intake.id != processed.intake_document_id):
            raise DocumentProcessingError("Semantic extraction document or claim association is stale or invalid.")
        saved_pages = (db.query(ProcessedPage).filter_by(processed_document_id=processed.id)
            .order_by(ProcessedPage.page_number).all())
        if not saved_pages:
            raise DocumentProcessingError("No persisted OCR/native-text pages are available for extraction.")
        if [page.page_number for page in saved_pages] != list(range(1, len(saved_pages) + 1)) or any(page.status not in {"COMPLETED", "SUCCESS", "complete", "success"} for page in saved_pages):
            raise DocumentProcessingError("Persisted OCR page coverage is incomplete; semantic extraction is blocked.")
        pages = [{"page_number": page.page_number, "text": page.raw_text or ""} for page in saved_pages]
        base = {"claim_id": processed.claim_id, "document_id": processed.document_id,
                "declared_type": declared_type, "input_checksum_sha256": checksum,
                "processing_attempt": processed.attempt_number}

        def save(kind, status, payload, prompt_version, error_code=None, started_at=None, *, commit=True):
            now = _now()
            artifact = SemanticArtifact(processed_document_id=processed.id, claim_id=processed.claim_id,
                document_id=processed.document_id, input_checksum_sha256=checksum,
                attempt_number=processed.attempt_number, artifact_kind=kind, status=status,
                payload=payload, model_id=self.model, prompt_version=prompt_version,
                schema_version=SCHEMA_VERSION, started_at=started_at or now, completed_at=now, error_code=error_code)
            db.add(artifact)
            if commit:
                db.commit()
            return artifact

        classification_started = _now()
        processed.status = "CLASSIFYING"
        db.commit()
        try:
            classification, class_meta = self.classify(pages, declared_type)
        except Exception as exc:
            details = {**base, "status": "review_required", "reasons": [f"Classification processing failed ({type(exc).__name__})."]}
            details["disposition"] = "classification_failed"
            save("classification", "classification_failed", details, CLASSIFIER_PROMPT_VERSION, type(exc).__name__, classification_started)
            save("application_validation", "classification_failed", {**base, "status": "classification_failed", "reasons": ["Classification did not complete."]}, "application-validation-v1")
            save("extraction", "not_run", {**base, "status": "extraction_pending", "reason": "Classification did not complete."}, EXTRACTION_PROMPT_VERSION)
            return "classification_failed"

        classification_payload = {**base, **classification.model_dump(), **class_meta,
            "prompt_version": CLASSIFIER_PROMPT_VERSION, "model_id": self.model}
        classification_status = {"mismatch": "content_mismatch", "unsupported": "review_required"}.get(
            classification.disposition, classification.disposition)
        save("classification", classification_status, classification_payload, CLASSIFIER_PROMPT_VERSION, started_at=classification_started)
        if classification.disposition != "accepted":
            reason = "Document classification did not pass the acceptance gate."
            save("application_validation", classification_status, {**base, "status": classification_status, "reasons": [reason]}, "application-validation-v1")
            save("extraction", "not_run", {**base, "status": "extraction_pending", "reason": reason}, EXTRACTION_PROMPT_VERSION)
            return classification_status

        processed.status = "EXTRACTING"
        db.commit()
        extraction_started = _now()
        try:
            extracted, validation = self.extract(pages, classification.detected_type, classification.subtype)
        except Exception as exc:
            prompt_version = f"{EXTRACTION_PROMPT_VERSION}/{classification.detected_type}"
            save("extraction", "failed", {**base, "status": "extraction_failed", "reasons": [f"Structured extraction failed ({type(exc).__name__})."]}, prompt_version, type(exc).__name__, extraction_started)
            save("application_validation", "review_required", {**base, "status": "review_required", "reasons": ["Structured extraction failed validation or did not complete."]}, "application-validation-v1")
            return "review_required"

        processed.status = "VALIDATING"
        db.commit()
        prompt_version = f"{EXTRACTION_PROMPT_VERSION}/{classification.detected_type}"
        invalid_structure = any(reason.startswith(("Unsupported field name", "Found/conflicting field has no raw value", "missing field contains a value", "not_applicable field contains a value", "unreadable field contains a value")) for reason in validation["reasons"])
        app_status = "failed" if invalid_structure else validation["status"]
        disposition = "extraction_failed" if invalid_structure else "accepted" if app_status == "passed" else "review_required"
        extraction_payload = {**base, "detected_type": classification.detected_type,
            "processed_pages": validation["processed_pages"], "model_id": self.model,
            "prompt_version": prompt_version, "schema_version": SCHEMA_VERSION,
            "status": app_status}
        retain_candidate = os.getenv("EXTRACTION_RETAIN_REVIEW_CANDIDATES", "false").strip().lower() in {"1", "true", "yes"}
        if app_status == "passed" or retain_candidate:
            extraction_payload.update(extracted.model_dump())
        else:
            extraction_payload["candidate_retained"] = False
            extraction_payload["candidate_omission_reason"] = "Application validation did not pass; only validation reasons are retained by default."
        extraction_status = "complete" if app_status == "passed" else "failed" if app_status == "failed" else "review_required"
        issue_code_by_reason = {
            "Unsupported field name": "UNKNOWN_FIELD",
            "Found/conflicting field has no raw value": "FIELD_STATE_VALUE_MISSING",
            "Found/conflicting field has no source evidence": "FIELD_EVIDENCE_MISSING",
            "Raw value is not contained": "RAW_VALUE_NOT_IN_EVIDENCE",
            "Unsupported evidence": "EVIDENCE_UNSUPPORTED",
            "Unsupported classification": "EVIDENCE_UNSUPPORTED",
            "Unsupported component": "EVIDENCE_UNSUPPORTED",
            "Conflicting values": "CONFLICTING_VALUES",
            "is after": "DATE_ORDER_INVALID",
            "Ambiguous or invalid normalized date": "DATE_NORMALIZATION_INVALID",
            "Invalid normalized decimal": "DECIMAL_NORMALIZATION_INVALID",
            "Normalized currency": "CURRENCY_NORMALIZATION_INVALID",
            "Reported subtotal": "BILL_ARITHMETIC_MISMATCH",
            "Bill arithmetic": "BILL_ARITHMETIC_NOT_EVALUATED",
            "page": "PAGE_COVERAGE_INVALID",
        }
        issues = []
        for reason in validation["reasons"]:
            code = next((code for prefix, code in issue_code_by_reason.items() if reason.startswith(prefix)), "EXTRACTION_REVIEW_REQUIRED")
            severity = "blocking" if code in {"UNKNOWN_FIELD", "FIELD_STATE_VALUE_MISSING"} else "review"
            issues.append(ValidationIssue(code=code, severity=severity, message=reason[:240]))
        check_ids = ["schema_structure", "allowed_fields", "field_state_consistency", "source_evidence", "page_coverage", "normalized_values", "date_order", "bill_arithmetic"]
        reason_groups = {
            "allowed_fields": ("Unsupported field name",),
            "field_state_consistency": ("field has no raw value", "field has no source evidence", "field contains a value", "Missing/not-applicable field has source evidence", "Normalized value has no source value"),
            "source_evidence": ("Unsupported evidence", "Unsupported classification quote", "Unsupported component", "Raw value is not contained", "Found/conflicting field has no source evidence"),
            "page_coverage": ("page coverage", "request did not cover every source page"),
            "normalized_values": ("Ambiguous or invalid normalized", "Ambiguous source date", "Invalid normalized decimal", "Raw and normalized monetary values differ", "Normalized currency"),
            "date_order": (" is after ",),
        }
        validation_checks = []
        for check_id in check_ids:
            related = [issue for issue in issues if any(token in issue.message for token in reason_groups.get(check_id, ()))]
            outcome = "fail" if related else "pass"
            required = check_id not in {"date_order", "bill_arithmetic"}
            if check_id == "bill_arithmetic":
                bill_warnings = [warning for warning in validation["consistency_warnings"] if "Bill arithmetic" in warning or "bill totals" in warning or "subtotal" in warning]
                if bill_warnings:
                    outcome = "not_evaluated" if "not evaluated" in bill_warnings[0].lower() or "could not" in bill_warnings[0].lower() else "fail"
                else:
                    relevant = {f.get("field_name") for f in extracted.facts if f.field_status == "found"}
                    outcome = "pass" if {"subtotal", "total"}.issubset(relevant) and relevant.intersection({"taxes", "discount", "credits"}) else "not_evaluated"
            if check_id == "bill_arithmetic" and outcome == "fail":
                related = [issue for issue in issues if issue.code == "BILL_ARITHMETIC_MISMATCH"]
            validation_checks.append(ValidationCheck(check_id=check_id, outcome=outcome, required=required,
                issue_codes=[issue.code for issue in related]))
        with stage_span(trace.get_tracer(__name__), "information_extraction_validation", str(processed.run_id), str(processed.intake_document_id),
                input_artifact_ids=[str(processed.id)], stage_version=EXTRACTION_VALIDATOR_VERSION,
                extra_attributes={VALIDATION_STATUS: app_status,
                    VALIDATION_RESULT: disposition,
                    VALIDATION_RULE_ID: check_ids,
                    "validator.version": EXTRACTION_VALIDATOR_VERSION,
                    "extraction.attempt": processed.attempt_number,
                    "input.checksum": checksum}):
            report = ExtractionValidationReport(
            claim_id=str(processed.claim_id), document_id=str(processed.intake_document_id),
            accepted_document_type=classification.detected_type, extraction_attempt=processed.attempt_number,
            input_version=checksum, validator_version=EXTRACTION_VALIDATOR_VERSION,
            configuration_version="application-validation-v1", overall_disposition=disposition,
            status=app_status, checks=validation_checks,
                issues=issues, started_at=extraction_started, completed_at=_now())
        report_payload = report.model_dump(mode="json")
        validation_payload = {**base, **validation, "status": disposition, "classification_disposition": classification.disposition,
            "extraction_disposition": "extraction_complete" if app_status == "passed" else "extraction_failed",
            "policy_set_state": "single_policy_upload_completeness_not_established" if declared_type == "policy_document" else None,
            "model_policy_set_assessment": classification.policy_set_complete if declared_type == "policy_document" else None,
            "model_id": self.model, "prompt_version": "application-validation-v1", "schema_version": SCHEMA_VERSION}
        save("extraction", extraction_status, extraction_payload, prompt_version, started_at=extraction_started, commit=False)
        save("application_validation", app_status, {**validation_payload, "report": report_payload}, "application-validation-v1", started_at=extraction_started, commit=False)
        db.commit()
        return "accepted" if app_status == "passed" else disposition

    @staticmethod
    def _validate_normalized(fact: dict, errors: list[str]) -> None:
        value, name = fact.get("normalized_value"), fact.get("field_name", "")
        if not value:
            return
        if name in DATE_FIELDS:
            try:
                datetime.strptime(value, "%Y-%m-%d")
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError("not canonical")
            except ValueError:
                errors.append(f"Ambiguous or invalid normalized date for {name}; preserve raw value and leave normalized value empty.")
            if fact.get("raw_value") and _parse_unambiguous_raw_date(fact["raw_value"]) is None:
                errors.append(f"Ambiguous source date was normalized for {name}; preserve raw value and leave normalized value empty.")
        if name == "currency" and not re.fullmatch(r"[A-Z]{3}", value):
            errors.append("Normalized currency must be a three-letter uppercase code; preserve raw currency wording.")
        if name in MONEY_FIELDS:
            try:
                parsed = Decimal(value.replace(",", ""))
                if not parsed.is_finite():
                    raise InvalidOperation
            except (InvalidOperation, AttributeError):
                errors.append(f"Invalid normalized decimal for {name}; preserve the source value.")
            raw_number, normalized_number = _decimal_value(fact.get("raw_value")), _decimal_value(value)
            if raw_number is not None and normalized_number is not None and raw_number != normalized_number:
                errors.append(f"Raw and normalized monetary values differ for {name}; preserve the source value.")

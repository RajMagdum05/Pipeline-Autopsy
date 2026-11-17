"""Producer-side selection and redaction for optional E2 evidence uploads."""

import os
import re
from copy import deepcopy

from autopsy_sdk.redact import excerpt, redact


_MASKED = "[REDACTED]"
_VALUE_KEYS = {"raw_value", "normalized_value", "quote"}
_FIELD_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def evidence_level():
    """Return the configured upload ceiling, defaulting to privacy-safe E1."""
    level = os.getenv("AUTOPSY_EVIDENCE_LEVEL", "E1").strip().upper()
    return level if level in {"E0", "E1", "E2"} else "E1"


def evidence_kinds():
    """Return the producer's local allow-list, intersected with the manifest."""
    local = {kind.strip() for kind in os.getenv(
        "AUTOPSY_EVIDENCE_KINDS", "page_text,document_facts,decision").split(",") if kind.strip()}
    manifest = {"page_text", "document_facts", "decision"}
    return local & manifest


def page_text_source(content):
    """Flatten canonical page records into text for line-based excerpting."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    lines = []
    for page in content:
        if not isinstance(page, dict):
            continue
        text = page.get("text")
        if text:
            lines.append(str(text))
    return "\n".join(lines)


def extracted_values(document_facts):
    """Collect source values used to select relevant page-text lines."""
    values = []
    facts = document_facts.get("facts", []) if isinstance(document_facts, dict) else []
    for fact in facts:
        if not isinstance(fact, dict) or fact.get("field_status") not in {"found", "conflicting"}:
            continue
        for key in ("raw_value", "normalized_value"):
            value = fact.get(key)
            if value is not None and str(value).strip() and str(value) not in values:
                values.append(str(value))
    return values


def page_text_excerpt(content, values, radius=80):
    """Return only value-bearing lines, with bounded context and PII masking."""
    return excerpt(page_text_source(content), values, radius=radius)


def redact_document_facts(document_facts, keep_fields=None):
    """Mask values and quotes outside explicitly approved grounding fields."""
    if keep_fields is None:
        keep_fields = os.getenv("AUTOPSY_EVIDENCE_KEEP_FIELDS", "").split(",")
    keep = {field.strip() for field in keep_fields if field and _FIELD_NAME.fullmatch(field.strip())}
    payload = deepcopy(document_facts)

    def scrub_nonvalue(value):
        if isinstance(value, dict):
            return {key: scrub_nonvalue(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub_nonvalue(item) for item in value]
        return redact(value) if isinstance(value, str) else value

    payload = scrub_nonvalue(payload)
    facts = payload.get("facts", []) if isinstance(payload, dict) else []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        keep_value = fact.get("field_name") in keep
        for key in ("raw_value", "normalized_value"):
            if fact.get(key) not in (None, ""):
                fact[key] = redact(str(fact[key])) if keep_value else _MASKED
        for evidence in fact.get("evidence", []):
            if isinstance(evidence, dict) and evidence.get("quote"):
                evidence["quote"] = redact(str(evidence["quote"])) if keep_value else _MASKED
    return payload


__all__ = [
    "evidence_kinds", "evidence_level", "extracted_values", "page_text_excerpt",
    "page_text_source", "redact_document_facts",
]

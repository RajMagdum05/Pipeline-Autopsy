"""
Rule-based triage — Stage 5.

Each rule looks at one step's output (and whatever upstream steps it
depends on) and decides whether that step's output still holds up. This
is deliberately simple and explainable — later stages (an LLM-based Root
Cause Engine, say) can layer on top without changing this contract.

A rule returns None if the step looks fine, or a RuleFinding if it
doesn't. Keeping this pluggable (STEP_RULES is just a dict) is what lets
the framework extend to steps/pipelines beyond this demo later.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleFinding:
    rule: str
    confidence: float
    raw: dict[str, Any] = field(default_factory=dict)


def _first_amount(text: str) -> float | None:
    """Pulls the first ₹-style amount out of free text, e.g. '₹25,000' -> 25000.0"""
    match = re.search(r"[\u20b9$]\s?([\d,]+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def check_extraction_grounding(events_by_step: dict[str, dict]) -> RuleFinding | None:
    """
    The step directly after OCR should agree with what OCR actually read.
    If Extraction's structured field doesn't match the number in the OCR
    text it was built from, Extraction — not whatever consumes it later —
    is where the pipeline first went wrong.
    """
    ocr = events_by_step.get("ocr")
    extraction = events_by_step.get("extraction")
    if not ocr or not extraction:
        return None

    ocr_text = ocr["output"].get("raw_text", "")
    ocr_amount = _first_amount(ocr_text)
    extracted_amount = extraction["output"].get("hospital_bill_total")

    if ocr_amount is None or extracted_amount is None:
        return None

    if ocr_amount == 0:
        return None

    deviation = abs(extracted_amount - ocr_amount) / ocr_amount
    if deviation < 0.01:  # within 1% — treat as agreement, not a failure
        return None

    confidence = round(min(55 + deviation * 36.11, 95), 1)
    return RuleFinding(
        rule="extraction_grounding_mismatch",
        confidence=confidence,
        raw={"ocr_amount": ocr_amount, "extracted_amount": extracted_amount, "deviation": deviation},
    )


def check_step_errored(events_by_step: dict[str, dict], step: str) -> RuleFinding | None:
    """Any step that raised an exception is an unambiguous, high-confidence origin."""
    event = events_by_step.get(step)
    if event and event["status"] == "error":
        return RuleFinding(
            rule="step_raised_exception",
            confidence=99.0,
            raw={"step": step, "error": event.get("error") or "raised an exception"},
        )
    return None


# One rule per step name. Steps with no entry are assumed healthy unless
# they errored outright (checked separately in root_cause.py).
STEP_RULES = {
    "extraction": check_extraction_grounding,
}

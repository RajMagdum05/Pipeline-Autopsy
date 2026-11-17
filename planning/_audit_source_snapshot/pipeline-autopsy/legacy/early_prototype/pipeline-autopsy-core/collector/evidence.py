"""
Evidence Engine — Stage 7.

The Root Cause Engine (stage 6) decides *which step*. This module's only
job is turning that step's raw finding into something a claims engineer
can read without needing to know what a "grounding check" is.
"""
from __future__ import annotations

from .schema import EvidenceItem


def build_evidence(rule: str, raw: dict) -> list[EvidenceItem]:
    if rule == "extraction_grounding_mismatch":
        return [
            EvidenceItem(
                label="Hospital bill amount",
                expected=f"₹{raw['ocr_amount']:,.0f} (per OCR)",
                actual=f"₹{raw['extracted_amount']:,.0f} (per Extraction)",
            )
        ]
    if rule == "step_raised_exception":
        return [
            EvidenceItem(
                label=raw["step"],
                expected="completes normally",
                actual=str(raw["error"]),
            )
        ]
    return []

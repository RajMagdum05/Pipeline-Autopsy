"""
Demo insurance claims pipeline — Stage 2.

Request -> OCR -> Extraction -> Policy Retrieval (RAG) -> Reasoning -> Recommendation

Each step is wrapped with @autopsy.trace_step. Every function below also
runs perfectly well completely undecorated — tracing never changes
behavior, only visibility. That's what lets Section 1 ("before") and
Section 3 ("after") of the earlier demo be the literal same code.

The bug lives in extract(): a real, if silly, parsing mistake — the kind
that ships to production because it doesn't crash, it just quietly
produces the wrong number.
"""
from __future__ import annotations

import re
import time

import pipeline_autopsy as autopsy


@autopsy.trace_step("request")
def receive_claim(claim: dict) -> dict:
    time.sleep(0.05)
    return {"claim_id": claim["claim_id"], "received": True}


@autopsy.trace_step("ocr")
def run_ocr(claim: dict) -> dict:
    time.sleep(0.1)
    return {"raw_text": claim["documents"]["medical_bill_ocr_text"]}


@autopsy.trace_step("extraction")
def extract(ocr_output: dict) -> dict:
    """
    Meant to read the hospital bill total out of the OCR text. The bug:
    this regex captures only the first run of digits before the comma —
    "\u20b925,000" becomes "25" — which then gets multiplied by a
    unit-normalization constant that only makes sense for a different
    document template. On this claim it silently produces \u20b952,000
    instead of \u20b925,000, and nothing here raises an error.
    """
    time.sleep(0.15)
    text = ocr_output["raw_text"]
    match = re.search(r"\u20b9\s?(\d+)", text)  # bug: stops at the first comma
    digits = match.group(1) if match else "0"
    hospital_bill_total = int(digits) * 2080  # bug: template-specific factor, wrong for this doc
    return {"hospital_bill_total": hospital_bill_total, "policy_hint": "hospitalization"}


@autopsy.trace_step("rag")
def retrieve_policy(fields: dict) -> dict:
    time.sleep(0.12)
    return {"policy_clause": "Hospitalization cover up to \u20b91,00,000 per claim; sub-limits apply per room category."}


@autopsy.trace_step("reasoning")
def reason(fields: dict, policy: dict) -> dict:
    time.sleep(0.2)
    within_limit = fields["hospital_bill_total"] <= 100_000
    return {"eligible": within_limit, "basis": policy["policy_clause"]}


@autopsy.trace_step("recommendation", final=True)
def recommend(fields: dict, reasoning: dict) -> dict:
    time.sleep(0.08)
    verdict = "Eligible for further review" if reasoning["eligible"] else "Flagged \u2014 exceeds policy limit"
    return {"recommendation": verdict, "claimed_amount": fields["hospital_bill_total"]}


def run_claim(claim: dict) -> dict:
    """Runs one claim through all six steps in order. This is the pipeline."""
    receive_claim(claim)
    ocr_output = run_ocr(claim)
    fields = extract(ocr_output)
    policy = retrieve_policy(fields)
    reasoning = reason(fields, policy)
    return recommend(fields, reasoning)

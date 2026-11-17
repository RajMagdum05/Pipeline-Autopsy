"""Business outcomes for the documented synthetic fault scenarios."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import faults
from app.adjudication import AdjudicationInputMissing, adjudicate_claim
from app.adjudication.schemas import Decision
from app.document_processing.exceptions import DocumentProcessingError
from app.information_extraction.content_service import DocumentContentService
from app.information_extraction.schemas import ExtractedFact, FieldEvidence


def _fact(field, value):
    return {"field_name": field, "raw_value": value, "normalized_value": value,
            "field_status": "found", "evidence": []}


def _inputs(admission_date="2025-03-02"):
    claim = {"policy_number": "POL-DEMO", "policyholder_name": "Alex Demo",
             "incident_date": "2025-03-05", "claimed_amount": Decimal("1200.00")}
    policy = {"document_id": "policy", "document_type": "policy_document", "facts": [
        _fact("policy_number", "POL-DEMO"), _fact("policyholder_name", "Alex Demo"),
        _fact("coverage_start", "2025-01-01"), _fact("coverage_end", "2025-12-31"),
        _fact("sum_insured", "500000"), _fact("currency", "INR"),
    ]}
    bill = {"document_id": "bill", "document_type": "hospital_bill", "facts": [
        _fact("admission_date", admission_date), _fact("total", "1200.00"),
        _fact("currency", "INR"), _fact("patient_name", "Alex Demo"),
    ]}
    return claim, policy, [bill]


def test_scenarios_1_and_2_use_real_business_facts_without_injection(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    with faults.activate("none"):
        claim, policy, proofs = _inputs()
        assert adjudicate_claim(claim, policy, proofs).decision == "APPROVED"
    with faults.activate("clean_rejection"):
        claim, policy, proofs = _inputs("2024-03-02")
        decision = adjudicate_claim(claim, policy, proofs)
        assert decision.decision == "REJECTED"
        assert any(rule.rule_id == "rule.service_in_coverage" and rule.result == "fail"
                   for rule in decision.rules)


def test_scenario_3_ocr_misread_propagates_to_a_clean_rejection(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    page = SimpleNamespace(raw_text="Admission Date: 2025-03-02")
    metrics = {"page_validations": [{"page_number": 1, "reasons": []}]}
    with faults.activate("ocr_misread_bill_date"):
        faults.after_text_extraction({"role": "hospital_bill"}, [page], metrics)
    assert metrics["page_validations"][0]["status"] == "WARNING"
    claim, policy, proofs = _inputs(page.raw_text.split(": ", 1)[1])
    decision = adjudicate_claim(claim, policy, proofs)
    assert decision.decision == "REJECTED"


def test_scenarios_4_and_5_distinguish_uncaught_from_caught_hallucination(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    page = {"page_number": 1, "text": "Admission Date: 2025-03-02"}
    for name, expected_review in (("extraction_wrong_date_uncaught", False),
                                  ("extraction_hallucinate_caught", True)):
        extracted = ExtractedFact(
            field_name="admission_date", raw_value="2025-03-02", normalized_value="2025-03-02",
            field_status="found", evidence=[FieldEvidence(page_number=1, quote="Admission Date: 2025-03-02")],
        )
        with faults.activate(name):
            faults.after_extraction({"role": "hospital_bill"}, [extracted])
            override = faults.validator_overrides({"role": "hospital_bill"})
        claim, policy, proofs = _inputs(extracted.normalized_value)
        proofs[0]["facts"][0] = _fact("admission_date", extracted.normalized_value)
        unsupported = DocumentContentService._check_quotes(
            {"facts": [extracted.model_dump()]}, [page],
        )
        if expected_review:
            assert unsupported
            assert not override
            with pytest.raises(AdjudicationInputMissing, match="accepted proof"):
                adjudicate_claim(claim, policy, [])
        else:
            assert override == {"skip_quote_fields": {"admission_date"}}
            assert not unsupported or "admission_date" in override["skip_quote_fields"]
            assert adjudicate_claim(claim, policy, proofs).decision == "REJECTED"


def test_scenarios_6_through_8_block_adjudication_at_the_first_detected_gate(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    page = SimpleNamespace(raw_text="Readable policy")
    metrics = {"page_validations": [{"page_number": 1, "reasons": []}]}
    with faults.activate("policy_ocr_unreadable"):
        faults.after_text_extraction({"role": "policy_document"}, [page], metrics)
    assert metrics["overall_status"] == "FAIL"
    with pytest.raises(AdjudicationInputMissing) as missing_policy:
        claim, policy, proofs = _inputs()
        adjudicate_claim(claim, {"facts": []}, proofs)
    assert missing_policy.value.missing_kind == "policy"

    with faults.activate("gemini_unavailable"):
        with pytest.raises(DocumentProcessingError) as unavailable:
            faults.before_llm("content_classification", {"role": "hospital_bill"})
    assert unavailable.value.error_class == "infra"
    with pytest.raises(AdjudicationInputMissing) as missing_proof:
        claim, policy, _ = _inputs()
        adjudicate_claim(claim, policy, [])
    assert missing_proof.value.missing_kind == "proof"

    with faults.activate("classification_mismatch"):
        mismatch = faults.before_llm("content_classification", {
            "role": "hospital_bill", "pages": [{"page_number": 1, "text": "CITY HOSPITAL BILL"}],
        })
    assert mismatch.detected_type == "discharge_summary"
    with pytest.raises(AdjudicationInputMissing) as mismatch_block:
        claim, policy, _ = _inputs()
        adjudicate_claim(claim, policy, [])
    assert mismatch_block.value.missing_kind == "proof"


def test_scenario_9_final_mismatch_flips_the_stored_rule_decision(monkeypatch):
    monkeypatch.setenv("FAULT_INJECTION_ENABLED", "true")
    decision = Decision(decision="APPROVED", rules_version="adjudication-rules-v1", rules=())
    with faults.activate("final_mismatch"):
        final = faults.after_adjudication(decision)
    assert decision.decision == "APPROVED"
    assert final.decision == "REJECTED"

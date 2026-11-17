from copy import deepcopy
from decimal import Decimal

import pytest

from app.adjudication import AdjudicationInputMissing, adjudicate_claim
from app.adjudication.service import aggregate_decision, evaluate_rules


def fact(field, value, *, status="found"):
    return {"field_name": field, "raw_value": str(value) if value is not None else None,
            "normalized_value": str(value) if value is not None else None,
            "field_status": status}


def inputs():
    claim = {"policyholder_name": "Asha Rao", "policy_number": "POL-101",
             "incident_date": "2025-03-05", "claimed_amount": Decimal("100.00")}
    policy = {"document_id": "policy-doc", "document_type": "policy_document", "facts": [
        fact("policy_number", "POL-101"), fact("policyholder_name", "Asha Rao"),
        fact("coverage_start", "2025-01-01"), fact("coverage_end", "2025-12-31"),
        fact("sum_insured", "100000"), fact("currency", "INR"),
    ]}
    bill = {"document_id": "bill-doc", "document_type": "hospital_bill", "facts": [
        fact("admission_date", "2025-03-06"), fact("total", "125.00"),
        fact("currency", "INR"), fact("patient_name", "Asha Rao"),
    ]}
    return claim, policy, [bill]


def by_id(results):
    return {rule.rule_id: rule for rule in results}


def rule_result(rule_id, claim, policy, proofs):
    return by_id(evaluate_rules(claim, policy, proofs))[rule_id]


@pytest.mark.parametrize("rule_id", [
    "rule.policy_number_match", "rule.policyholder_match", "rule.incident_in_coverage",
    "rule.service_in_coverage", "rule.financial_proof_present", "rule.currency_consistent",
    "rule.amount_within_bills", "rule.amount_within_sum_insured", "rule.patient_is_insured",
])
def test_all_rules_pass_for_a_consistent_claim(rule_id):
    claim, policy, proofs = inputs()
    assert rule_result(rule_id, claim, policy, proofs).result == "pass"


@pytest.mark.parametrize("rule_id,mutate,expected_reason", [
    ("rule.policy_number_match", lambda c, p, b: c.update(policy_number="POL-999"), "POLICY_NUMBER_MISMATCH"),
    ("rule.policyholder_match", lambda c, p, b: c.update(policyholder_name="Other Person"), "POLICYHOLDER_MISMATCH"),
    ("rule.incident_in_coverage", lambda c, p, b: c.update(incident_date="2026-01-01"), "INCIDENT_OUTSIDE_COVERAGE"),
    ("rule.service_in_coverage", lambda c, p, b: b[0]["facts"].__setitem__(0, fact("admission_date", "2024-12-31")), "SERVICE_BEFORE_COVERAGE"),
    ("rule.currency_consistent", lambda c, p, b: b[0]["facts"].__setitem__(2, fact("currency", "USD")), "CURRENCY_MISMATCH"),
    ("rule.amount_within_bills", lambda c, p, b: c.update(claimed_amount=Decimal("126.00")), "CLAIMED_AMOUNT_EXCEEDS_BILLS"),
    ("rule.amount_within_sum_insured", lambda c, p, b: c.update(claimed_amount=Decimal("100001")), "CLAIMED_AMOUNT_EXCEEDS_SUM_INSURED"),
    ("rule.patient_is_insured", lambda c, p, b: b[0]["facts"].__setitem__(3, fact("patient_name", "Other Person")), "PATIENT_NOT_INSURED"),
])
def test_rule_failures_use_the_documented_consequence(rule_id, mutate, expected_reason):
    claim, policy, proofs = inputs()
    mutate(claim, policy, proofs)
    result = rule_result(rule_id, claim, policy, proofs)
    assert result.result == "fail"
    assert result.reason_code == expected_reason
    assert result.consequence in {"REJECT", "REFER"}


def test_financial_proof_rule_fails_when_there_is_no_hospital_bill():
    claim, policy, proofs = inputs()
    result = rule_result("rule.financial_proof_present", claim, policy,
                         [{"document_id": "summary-doc", "document_type": "discharge_summary", "facts": [fact("patient_name", "Asha Rao")]}])
    assert result.result == "fail"
    assert result.consequence == "REFER"


@pytest.mark.parametrize("rule_id,mutate", [
    ("rule.policy_number_match", lambda c, p, b: p["facts"].__setitem__(0, fact("policy_number", None, status="missing"))),
    ("rule.policyholder_match", lambda c, p, b: c.update(policyholder_name="")),
    ("rule.incident_in_coverage", lambda c, p, b: c.update(incident_date="March 5, 2025")),
    ("rule.service_in_coverage", lambda c, p, b: b[0]["facts"].__setitem__(0, fact("admission_date", None, status="missing"))),
    ("rule.currency_consistent", lambda c, p, b: b[0]["facts"].__setitem__(2, fact("currency", None, status="missing"))),
    ("rule.amount_within_bills", lambda c, p, b: b[0]["facts"].__setitem__(1, fact("total", None, status="missing"))),
    ("rule.amount_within_sum_insured", lambda c, p, b: p["facts"].__setitem__(4, fact("sum_insured", None, status="missing"))),
    ("rule.patient_is_insured", lambda c, p, b: b[0]["facts"].__setitem__(3, fact("patient_name", None, status="missing"))),
])
def test_rules_with_missing_or_invalid_required_inputs_are_not_evaluable(rule_id, mutate):
    claim, policy, proofs = inputs()
    mutate(claim, policy, proofs)
    assert rule_result(rule_id, claim, policy, proofs).result == "not_evaluable"


def test_conflicting_and_repeated_scalar_facts_are_not_used():
    claim, policy, proofs = inputs()
    policy["facts"].append(fact("policy_number", "POL-999"))
    assert rule_result("rule.policy_number_match", claim, policy, proofs).result == "not_evaluable"

    claim, policy, proofs = inputs()
    policy["facts"][0] = fact("policy_number", "POL-101", status="conflicting")
    assert rule_result("rule.policy_number_match", claim, policy, proofs).result == "not_evaluable"


def test_repeatable_insured_member_facts_are_not_used_by_v1_rules():
    claim, policy, proofs = inputs()
    policy["facts"].append(fact("insured_member_name", "Asha Rao"))
    assert rule_result("rule.policyholder_match", claim, policy, proofs).result == "pass"
    claim["policyholder_name"] = "Asha Rao Jr"
    assert rule_result("rule.policyholder_match", claim, policy, proofs).result == "not_evaluable"
    proofs[0]["facts"][3] = fact("patient_name", "Asha Rao Jr")
    assert rule_result("rule.patient_is_insured", claim, policy, proofs).result == "not_evaluable"


def test_rule_references_include_document_and_field_for_every_source():
    claim, policy, proofs = inputs()
    rule = rule_result("rule.service_in_coverage", claim, policy, proofs)
    refs = {(row.document_id, row.field) for row in rule.inputs}
    assert ("policy-doc", "coverage_start") in refs
    assert ("policy-doc", "coverage_end") in refs
    assert ("bill-doc", "admission_date") in refs


@pytest.mark.parametrize("amount,expected", [("100.01", "pass"), ("100.02", "fail")])
def test_money_comparisons_reuse_currency_tolerance(amount, expected):
    claim, policy, proofs = inputs()
    claim["claimed_amount"] = Decimal(amount)
    proofs[0]["facts"][1] = fact("total", "100.00")
    assert rule_result("rule.amount_within_bills", claim, policy, proofs).result == expected


@pytest.mark.parametrize("results,expected", [
    (["pass"], "APPROVED"),
    (["pass", "fail:REFER"], "MANUAL_REVIEW"),
    (["not_evaluable"], "MANUAL_REVIEW"),
    (["fail:REJECT", "fail:REFER"], "REJECTED"),
])
def test_decision_aggregation(results, expected):
    from app.adjudication.schemas import RuleResult

    rules = []
    for index, outcome in enumerate(results):
        result, _, consequence = outcome.partition(":")
        rules.append(RuleResult(rule_id=f"rule.{index}", result=result, consequence=consequence or None))
    decision = aggregate_decision(rules, Decimal("100.00"))
    assert decision.decision == expected
    assert decision.payable_amount == (Decimal("100.00") if expected == "APPROVED" else None)


def test_adjudication_is_deterministic_and_does_not_mutate_inputs():
    claim, policy, proofs = inputs()
    original = deepcopy((claim, policy, proofs))
    first = adjudicate_claim(claim, policy, proofs)
    second = adjudicate_claim(claim, policy, proofs)
    assert first == second
    assert first.rules_version == "adjudication-rules-v1"
    assert first.decision == "APPROVED"
    assert first.payable_amount == Decimal("100.00")
    assert (claim, policy, proofs) == original


@pytest.mark.parametrize("policy,proofs,missing_kind", [
    ({"document_id": "p", "facts": []}, [{"document_type": "hospital_bill", "facts": [fact("total", "10")]}], "policy"),
    ({"document_id": "p", "facts": [fact("policy_number", "P-1")]}, [], "proof"),
])
def test_preconditions_raise_typed_input_missing(policy, proofs, missing_kind):
    claim, _, _ = inputs()
    with pytest.raises(AdjudicationInputMissing) as error:
        adjudicate_claim(claim, policy, proofs)
    assert error.value.missing_kind == missing_kind

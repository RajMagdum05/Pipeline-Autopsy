"""Pure deterministic v1 decision aggregation for an accepted claim run."""

from decimal import Decimal
from typing import Mapping, Sequence

from app.information_extraction.content_service import DEFAULT_CURRENCY_TOLERANCES
from app.adjudication.rules import (
    FactSet, canonical_date, currency_tolerance, decimal_value, make_result,
    normalize_identifier, normalize_name,
)
from app.adjudication.schemas import AdjudicationInputMissing, Decision, InputReference, RuleResult


RULES_VERSION = "adjudication-rules-v1"
_NOTE = "Deductible/copay not applied in v1"


def _single(source: FactSet, field: str, *, parse=None, reason_prefix: str):
    item = source.one(field)
    if item.value is None:
        return None, item.reference, item.unavailable_reason
    value = parse(item.value) if parse else item.value
    return value, item.reference, None if value is not None else f"{reason_prefix}_INVALID"


def _claim_value(claim: FactSet, field: str, *, parse=None):
    item = claim.one(field)
    if item.value is None:
        return None, item.reference, "missing"
    value = parse(item.value) if parse else item.value
    return value, item.reference, None if value is not None else "invalid"


def _unknown(rule_id: str, consequence: str, refs: Sequence[InputReference], reason: str) -> RuleResult:
    return make_result(rule_id, "not_evaluable", refs, consequence=consequence, reason_code=reason)


def _pass(rule_id: str, refs: Sequence[InputReference]) -> RuleResult:
    return make_result(rule_id, "pass", refs)


def _fail(rule_id: str, consequence: str, refs: Sequence[InputReference], reason: str) -> RuleResult:
    return make_result(rule_id, "fail", refs, consequence=consequence, reason_code=reason)


def _rule_policy_number(claim: FactSet, policy: FactSet) -> RuleResult:
    rule_id = "rule.policy_number_match"
    claim_value, claim_ref, claim_error = _claim_value(claim, "policy_number", parse=normalize_identifier)
    policy_value, policy_ref, policy_error = _single(policy, "policy_number", parse=normalize_identifier, reason_prefix="POLICY_NUMBER")
    refs = [claim_ref, policy_ref]
    if claim_error or policy_error:
        return _unknown(rule_id, "REJECT", refs, "POLICY_NUMBER_MISSING_OR_INVALID")
    return _pass(rule_id, refs) if claim_value == policy_value else _fail(rule_id, "REJECT", refs, "POLICY_NUMBER_MISMATCH")


def _rule_policyholder(claim: FactSet, policy: FactSet) -> RuleResult:
    rule_id = "rule.policyholder_match"
    claim_value, claim_ref, claim_error = _claim_value(claim, "policyholder_name", parse=normalize_name)
    policy_value, policy_ref, policy_error = _single(policy, "policyholder_name", parse=normalize_name, reason_prefix="POLICYHOLDER")
    refs = [claim_ref, policy_ref]
    member_values, member_ref, member_error = policy.many("insured_member_name")
    refs.append(member_ref)
    if claim_error:
        return _unknown(rule_id, "REFER", refs, "POLICYHOLDER_NAME_MISSING_OR_INVALID")
    if policy_value and claim_value == policy_value:
        return _pass(rule_id, refs)
    # insured_member_name is explicitly repeatable and v1 does not adjudicate
    # against repeatable facts; preserve uncertainty rather than fail the rule.
    if member_values or member_error == "conflicting":
        return _unknown(rule_id, "REFER", refs, "REPEATABLE_INSURED_MEMBER_NAME")
    if policy_error:
        return _unknown(rule_id, "REFER", refs, "POLICYHOLDER_NAME_MISSING_OR_INVALID")
    return _fail(rule_id, "REFER", refs, "POLICYHOLDER_MISMATCH")


def _rule_incident_coverage(claim: FactSet, policy: FactSet) -> RuleResult:
    rule_id = "rule.incident_in_coverage"
    incident, incident_ref, incident_error = _claim_value(claim, "incident_date", parse=canonical_date)
    start, start_ref, start_error = _single(policy, "coverage_start", parse=canonical_date, reason_prefix="COVERAGE_START")
    end, end_ref, end_error = _single(policy, "coverage_end", parse=canonical_date, reason_prefix="COVERAGE_END")
    refs = [incident_ref, start_ref, end_ref]
    if incident_error or start_error or end_error:
        return _unknown(rule_id, "REJECT", refs, "COVERAGE_DATE_MISSING_OR_INVALID")
    return _pass(rule_id, refs) if start <= incident <= end else _fail(rule_id, "REJECT", refs, "INCIDENT_OUTSIDE_COVERAGE")


def _rule_service_coverage(policy: FactSet, proofs: Sequence[FactSet]) -> RuleResult:
    rule_id = "rule.service_in_coverage"
    start, start_ref, start_error = _single(policy, "coverage_start", parse=canonical_date, reason_prefix="COVERAGE_START")
    end, end_ref, end_error = _single(policy, "coverage_end", parse=canonical_date, reason_prefix="COVERAGE_END")
    refs = [start_ref, end_ref]
    bills = [proof for proof in proofs if proof.document.get("document_type") == "hospital_bill"]
    if start_error or end_error:
        return _unknown(rule_id, "REJECT", refs, "COVERAGE_DATE_MISSING_OR_INVALID")
    if not bills:
        return _unknown(rule_id, "REJECT", refs, "BILL_SERVICE_DATE_MISSING")
    dates: list[date] = []
    for bill in bills:
        admission, admission_ref, admission_error = _single(bill, "admission_date", parse=canonical_date, reason_prefix="ADMISSION_DATE")
        refs.append(admission_ref)
        if admission_error == "missing":
            invoice, invoice_ref, invoice_error = _single(bill, "invoice_date", parse=canonical_date, reason_prefix="INVOICE_DATE")
            refs.append(invoice_ref)
            if invoice_error:
                return _unknown(rule_id, "REJECT", refs, "BILL_SERVICE_DATE_MISSING_OR_INVALID")
            dates.append(invoice)
        elif admission_error:
            return _unknown(rule_id, "REJECT", refs, "BILL_SERVICE_DATE_MISSING_OR_INVALID")
        else:
            dates.append(admission)
    if all(start <= service_date <= end for service_date in dates):
        return _pass(rule_id, refs)
    return _fail(rule_id, "REJECT", refs, "SERVICE_BEFORE_COVERAGE" if any(d < start for d in dates) else "SERVICE_AFTER_COVERAGE")


def _rule_financial_proof(proofs: Sequence[FactSet]) -> RuleResult:
    rule_id = "rule.financial_proof_present"
    bills = [proof for proof in proofs if proof.document.get("document_type") == "hospital_bill"]
    refs = [InputReference(document_id=proof.document_id, field="document_type") for proof in proofs]
    if bills:
        return _pass(rule_id, refs)
    return _fail(rule_id, "REFER", refs, "FINANCIAL_PROOF_MISSING")


def _rule_currency(policy: FactSet, proofs: Sequence[FactSet]) -> RuleResult:
    rule_id = "rule.currency_consistent"
    policy_currency, policy_ref, policy_error = _single(policy, "currency", parse=lambda value: str(value).strip().upper(), reason_prefix="CURRENCY")
    bills = [proof for proof in proofs if proof.document.get("document_type") == "hospital_bill"]
    refs = [policy_ref]
    if not bills:
        return _unknown(rule_id, "REFER", refs, "CURRENCY_MISSING")
    mismatch = False
    for bill in bills:
        bill_currency, bill_ref, bill_error = _single(bill, "currency", parse=lambda value: str(value).strip().upper(), reason_prefix="CURRENCY")
        refs.append(bill_ref)
        if bill_error:
            return _unknown(rule_id, "REFER", refs, "CURRENCY_MISSING_OR_INVALID")
        mismatch = mismatch or bill_currency != policy_currency
    if policy_error:
        return _unknown(rule_id, "REFER", refs, "CURRENCY_MISSING_OR_INVALID")
    return _fail(rule_id, "REFER", refs, "CURRENCY_MISMATCH") if mismatch else _pass(rule_id, refs)


def _rule_amount_within_bills(claim: FactSet, policy: FactSet, proofs: Sequence[FactSet], tolerances: Mapping[str, str | Decimal]) -> RuleResult:
    rule_id = "rule.amount_within_bills"
    claimed, claim_ref, claim_error = _claim_value(claim, "claimed_amount", parse=decimal_value)
    policy_currency, policy_currency_ref, currency_error = _single(policy, "currency", parse=lambda value: str(value).strip().upper(), reason_prefix="CURRENCY")
    refs = [claim_ref, policy_currency_ref]
    bills = [proof for proof in proofs if proof.document.get("document_type") == "hospital_bill"]
    if not bills:
        return _unknown(rule_id, "REFER", refs, "BILL_TOTAL_MISSING")
    totals, currencies = [], []
    for bill in bills:
        total, total_ref, total_error = _single(bill, "total", parse=decimal_value, reason_prefix="TOTAL")
        currency, currency_ref, bill_currency_error = _single(bill, "currency", parse=lambda value: str(value).strip().upper(), reason_prefix="CURRENCY")
        refs.extend((total_ref, currency_ref))
        if total_error or bill_currency_error:
            return _unknown(rule_id, "REFER", refs, "BILL_TOTAL_OR_CURRENCY_MISSING")
        totals.append(total)
        currencies.append(currency)
    if claim_error or currency_error or any(currency != policy_currency for currency in currencies):
        return _unknown(rule_id, "REFER", refs, "AMOUNT_CURRENCY_UNRESOLVED")
    tolerance = currency_tolerance(policy_currency, tolerances)
    if tolerance is None:
        return _unknown(rule_id, "REFER", refs, "CURRENCY_TOLERANCE_UNAVAILABLE")
    return _pass(rule_id, refs) if claimed <= sum(totals, Decimal("0")) + tolerance else _fail(rule_id, "REFER", refs, "CLAIMED_AMOUNT_EXCEEDS_BILLS")


def _rule_amount_within_sum_insured(claim: FactSet, policy: FactSet, tolerances: Mapping[str, str | Decimal]) -> RuleResult:
    rule_id = "rule.amount_within_sum_insured"
    claimed, claim_ref, claim_error = _claim_value(claim, "claimed_amount", parse=decimal_value)
    insured, insured_ref, insured_error = _single(policy, "sum_insured", parse=decimal_value, reason_prefix="SUM_INSURED")
    currency, currency_ref, currency_error = _single(policy, "currency", parse=lambda value: str(value).strip().upper(), reason_prefix="CURRENCY")
    refs = [claim_ref, insured_ref, currency_ref]
    if claim_error or insured_error or currency_error:
        return _unknown(rule_id, "REJECT", refs, "SUM_INSURED_OR_AMOUNT_MISSING")
    tolerance = currency_tolerance(currency, tolerances)
    if tolerance is None:
        return _unknown(rule_id, "REJECT", refs, "CURRENCY_TOLERANCE_UNAVAILABLE")
    return _pass(rule_id, refs) if claimed <= insured + tolerance else _fail(rule_id, "REJECT", refs, "CLAIMED_AMOUNT_EXCEEDS_SUM_INSURED")


def _rule_patient_insured(policy: FactSet, proofs: Sequence[FactSet]) -> RuleResult:
    rule_id = "rule.patient_is_insured"
    policyholder, policy_ref, policy_error = _single(policy, "policyholder_name", parse=normalize_name, reason_prefix="POLICYHOLDER")
    members, members_ref, members_error = policy.many("insured_member_name")
    refs = [policy_ref, members_ref]
    bills = [proof for proof in proofs if proof.document.get("document_type") == "hospital_bill"]
    if not bills:
        return _unknown(rule_id, "REFER", refs, "PATIENT_NAME_MISSING")
    for bill in bills:
        patient, patient_ref, patient_error = _single(bill, "patient_name", parse=normalize_name, reason_prefix="PATIENT")
        refs.append(patient_ref)
        if patient_error:
            return _unknown(rule_id, "REFER", refs, "PATIENT_OR_INSURED_NAME_MISSING")
        if policyholder and patient == policyholder:
            continue
        # The v1 rules intentionally avoid using repeatable member facts.
        if members or members_error == "conflicting" or policy_error:
            return _unknown(rule_id, "REFER", refs, "REPEATABLE_OR_CONFLICTING_INSURED_NAME")
        if patient != policyholder:
            return _fail(rule_id, "REFER", refs, "PATIENT_NOT_INSURED")
    return _pass(rule_id, refs)


def evaluate_rules(claim_form: Mapping[str, Any], policy_facts: Mapping[str, Any], proof_facts: Sequence[Mapping[str, Any]], *,
                   tolerances: Mapping[str, str | Decimal] = DEFAULT_CURRENCY_TOLERANCES) -> tuple[RuleResult, ...]:
    """Evaluate all v1 rules without I/O, persistence, or mutation of caller inputs."""
    claim = FactSet(claim_form, document_id=str(claim_form.get("document_id") or "claim_form"))
    policy = FactSet(policy_facts)
    proofs = tuple(FactSet(proof) for proof in proof_facts)
    return (
        _rule_policy_number(claim, policy),
        _rule_policyholder(claim, policy),
        _rule_incident_coverage(claim, policy),
        _rule_service_coverage(policy, proofs),
        _rule_financial_proof(proofs),
        _rule_currency(policy, proofs),
        _rule_amount_within_bills(claim, policy, proofs, tolerances),
        _rule_amount_within_sum_insured(claim, policy, tolerances),
        _rule_patient_insured(policy, proofs),
    )


def aggregate_decision(rules: Sequence[RuleResult], claimed_amount: Decimal | None) -> Decision:
    if any(rule.result == "fail" and rule.consequence == "REJECT" for rule in rules):
        outcome, payable = "REJECTED", None
    elif any(rule.result != "pass" for rule in rules):
        outcome, payable = "MANUAL_REVIEW", None
    else:
        outcome, payable = "APPROVED", claimed_amount
    return Decision(decision=outcome, rules_version=RULES_VERSION, payable_amount=payable,
                    rules=tuple(rules), note=_NOTE)


def adjudicate_claim(claim_form: Mapping[str, Any], policy_facts: Mapping[str, Any], proof_facts: Sequence[Mapping[str, Any]], *,
                     tolerances: Mapping[str, str | Decimal] = DEFAULT_CURRENCY_TOLERANCES) -> Decision:
    """Apply conservative preconditions, evaluate the rule table, and aggregate."""
    if not _has_accepted_facts(policy_facts):
        raise AdjudicationInputMissing("policy", "Accepted policy facts are required before adjudication.")
    if not proof_facts or not any(_has_accepted_facts(proof) for proof in proof_facts):
        raise AdjudicationInputMissing("proof", "At least one accepted proof is required before adjudication.")
    rules = evaluate_rules(claim_form, policy_facts, proof_facts, tolerances=tolerances)
    claimed_amount = decimal_value(claim_form.get("claimed_amount"))
    return aggregate_decision(rules, claimed_amount)


def _has_accepted_facts(document: Mapping[str, Any]) -> bool:
    facts = document.get("facts")
    if isinstance(facts, list):
        return any(isinstance(row, Mapping) and row.get("field_status") == "found" for row in facts)
    return any(value is not None and value != "" for key, value in document.items() if key not in {"document_id", "id", "document_type"})

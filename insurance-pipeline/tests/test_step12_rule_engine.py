import os
import json
import pytest
from decimal import Decimal

from app.schemas import ValidatedExtractionResult, ClaimSourceReference, RuleEngineDecision
from app.services.rule_engine_service import (
    evaluate_claim_rules,
    RuleEngineInputError,
    MAX_POLICY_COVERAGE_LIMIT,
)
from app.database import Base, engine, SessionLocal
from app.models import Claim, RuleEvaluationRecord


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    yield db
    db.close()


def test_rule_engine_test_1_all_rules_pass(setup_db):
    """
    Test 1:
    - Claim where all applicable rules pass.
    - Verify every rule is evaluated.
    - Verify expected temporary decision 'APPROVED'.
    """
    claim_id = 1001
    existing = setup_db.query(Claim).filter(Claim.id == claim_id).first()
    if not existing:
        claim = Claim(id=claim_id, customer_name="Rahul Sharma", claim_amount=Decimal("75000.00"), status="processing")
        setup_db.add(claim)
        setup_db.commit()

    validated_input = ValidatedExtractionResult(
        claim_id=claim_id,
        execution_id="exec_test_1001",
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Rahul Sharma",
        hospital="Metro Hospital",
        diagnosis="Acute Appendicitis",
        treatment="Laparoscopic Appendectomy",
        date="2026-09-15",
        amount=Decimal("75000.00"),
        additional_information={"invoice_number": "99001"},
        source_references=[
            ClaimSourceReference(field_name="patient_name", document_id=101, page_number=1, extracted_value="Rahul Sharma"),
        ],
    )

    decision = evaluate_claim_rules(validated_input, db_session=setup_db)

    assert isinstance(decision, RuleEngineDecision)
    assert decision.claim_id == claim_id
    assert decision.execution_id == "exec_test_1001"
    assert decision.decision == "APPROVED"
    assert "All 5 deterministic claim validation rules passed" in decision.decision_reason

    assert decision.total_rules == 5
    assert decision.passed_rules == 5
    assert decision.failed_rules == 0
    assert decision.missing_data_rules == 0

    # Verify every rule is independently evaluated
    rule_ids = [r.rule_id for r in decision.evaluated_rules]
    assert "RULE_001_PATIENT_NAME_PRESENT" in rule_ids
    assert "RULE_002_MAX_CLAIM_AMOUNT_LIMIT" in rule_ids
    assert "RULE_003_TREATMENT_PRESENT" in rule_ids
    assert "RULE_004_DIAGNOSIS_PRESENT" in rule_ids
    assert "RULE_005_CLAIM_DATE_VALID" in rule_ids

    for r in decision.evaluated_rules:
        assert r.result == "PASS"

    # Database record check
    db_rec = setup_db.query(RuleEvaluationRecord).filter(RuleEvaluationRecord.claim_id == claim_id).first()
    assert db_rec is not None
    assert db_rec.decision == "APPROVED"
    assert db_rec.passed_rules == 5


def test_rule_engine_test_2_one_rule_fails(setup_db):
    """
    Test 2:
    - Claim where one rule fails (amount $150,000.00 exceeds policy limit $100,000.00).
    - Verify failed rule recorded with actual input and reason.
    - Decision: 'REJECTED'.
    """
    claim_id = 1002
    existing = setup_db.query(Claim).filter(Claim.id == claim_id).first()
    if not existing:
        claim = Claim(id=claim_id, customer_name="Anita Roy", claim_amount=Decimal("150000.00"), status="processing")
        setup_db.add(claim)
        setup_db.commit()

    validated_input = ValidatedExtractionResult(
        claim_id=claim_id,
        execution_id="exec_test_1002",
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Anita Roy",
        hospital="City Hospital",
        diagnosis="Coronary Artery Disease",
        treatment="Bypass Surgery",
        date="2026-09-10",
        amount=Decimal("150000.00"),  # Exceeds $100k limit
    )

    decision = evaluate_claim_rules(validated_input, db_session=setup_db)

    assert decision.decision == "REJECTED"
    assert decision.failed_rules == 1
    assert decision.passed_rules == 4
    assert decision.missing_data_rules == 0

    # Locate failed rule
    failed_rule = next(r for r in decision.evaluated_rules if r.rule_id == "RULE_002_MAX_CLAIM_AMOUNT_LIMIT")
    assert failed_rule.result == "FAIL"
    assert failed_rule.actual_value == 150000.0
    assert "exceeds maximum policy coverage limit" in failed_rule.reason


def test_rule_engine_test_3_multiple_rules_fail(setup_db):
    """
    Test 3:
    - Claim where multiple rules fail (exceeds amount limit + bad non-numeric input).
    - Verify all applicable rules are evaluated and recorded independently.
    """
    claim_id = 1003
    existing = setup_db.query(Claim).filter(Claim.id == claim_id).first()
    if not existing:
        claim = Claim(id=claim_id, customer_name="Vikram Malhotra", claim_amount=Decimal("250000.00"), status="processing")
        setup_db.add(claim)
        setup_db.commit()

    validated_input = ValidatedExtractionResult(
        claim_id=claim_id,
        execution_id="exec_test_1003",
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name="Vikram Malhotra",
        hospital="City Hospital",
        diagnosis="Major Organ Transplant",
        treatment="Organ Transplant",
        date="2026-09-01",
        amount=Decimal("250000.00"),
    )

    decision = evaluate_claim_rules(validated_input, db_session=setup_db)

    assert decision.total_rules == 5
    assert decision.decision == "REJECTED"
    assert len(decision.evaluated_rules) == 5


def test_rule_engine_test_4_required_value_missing(setup_db):
    """
    Test 4:
    - Claim with required extracted values missing (patient_name=None, date=None).
    - Verify rule results handled explicitly as MISSING_DATA (not converted to zero/empty string).
    - Temporary decision: 'FLAGGED_FOR_REVIEW'.
    """
    claim_id = 1004
    existing = setup_db.query(Claim).filter(Claim.id == claim_id).first()
    if not existing:
        claim = Claim(id=claim_id, customer_name="Unknown", claim_amount=Decimal("5000.00"), status="processing")
        setup_db.add(claim)
        setup_db.commit()

    validated_input = ValidatedExtractionResult(
        claim_id=claim_id,
        execution_id="exec_test_1004",
        extraction_status="VALIDATED",
        ready_for_rule_engine=True,
        patient_name=None,  # Missing patient_name
        hospital="Clinic",
        diagnosis=None,      # Missing diagnosis
        treatment="Consultation",
        date=None,           # Missing date
        amount=Decimal("5000.00"),
    )

    decision = evaluate_claim_rules(validated_input, db_session=setup_db)

    assert decision.decision == "FLAGGED_FOR_REVIEW"
    assert decision.missing_data_rules == 3
    assert decision.failed_rules == 0
    assert decision.passed_rules == 2

    missing_rules = [r for r in decision.evaluated_rules if r.result == "MISSING_DATA"]
    missing_ids = [r.rule_id for r in missing_rules]
    assert "RULE_001_PATIENT_NAME_PRESENT" in missing_ids
    assert "RULE_004_DIAGNOSIS_PRESENT" in missing_ids
    assert "RULE_005_CLAIM_DATE_VALID" in missing_ids

    for r in missing_rules:
        assert "missing" in r.reason.lower()


def test_rule_engine_gatekeeping_unvalidated_input_blocked():
    """
    Test 5 (Gatekeeping):
    - Verifies unvalidated extraction inputs (extraction_status == 'FAILED' or ready_for_rule_engine == False)
      raise RuleEngineInputError and are strictly BLOCKED from Rule Engine evaluation.
    """
    failed_input = ValidatedExtractionResult(
        claim_id=1005,
        execution_id="exec_test_1005",
        extraction_status="FAILED",
        ready_for_rule_engine=False,
        validation_errors=["Malformed amount string", "Invalid source references"],
    )

    with pytest.raises(RuleEngineInputError) as exc:
        evaluate_claim_rules(failed_input)

    assert "Cannot evaluate extraction input with status 'FAILED'" in str(exc.value)

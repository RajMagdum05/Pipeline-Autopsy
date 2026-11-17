from decimal import Decimal

import pytest

from app.adjudication.schemas import Decision, InputReference, RuleResult
from app.final_result.service import build_final_result


@pytest.mark.parametrize("decision,status,message_code", [
    ("APPROVED", "APPROVED", "CLAIM_APPROVED"),
    ("REJECTED", "REJECTED", "CLAIM_REJECTED"),
    ("MANUAL_REVIEW", "MANUAL_REVIEW", "CLAIM_REQUIRES_REVIEW"),
])
def test_final_result_maps_decision_to_claim_status_and_safe_message(decision, status, message_code):
    result = build_final_result(Decision(decision=decision, rules_version="adjudication-rules-v1",
        payable_amount=Decimal("42.50") if decision == "APPROVED" else None, rules=()),
        claim_id="CLM-SYNTHETIC", run_id="synthetic-run")
    assert result.claim_status == status
    assert result.message_code == message_code
    assert result.run_id == "synthetic-run"
    assert result.payable_amount == (Decimal("42.50") if decision == "APPROVED" else None)


def test_rule_reasons_use_safe_rule_messages_and_never_echo_input_values():
    decision = Decision(decision="REJECTED", rules_version="adjudication-rules-v1", rules=(
        RuleResult(rule_id="rule.service_in_coverage", result="fail", consequence="REJECT",
            inputs=(InputReference(document_id="synthetic-bill", field="admission_date"),),
            reason_code="SERVICE_BEFORE_COVERAGE"),
    ))
    result = build_final_result(decision, claim_id="CLM-SYNTHETIC", run_id="synthetic-run")
    assert len(result.reasons) == 1
    assert result.reasons[0].rule_id == "rule.service_in_coverage"
    assert "coverage period" in result.reasons[0].message
    assert "SERVICE_BEFORE_COVERAGE" not in result.reasons[0].message

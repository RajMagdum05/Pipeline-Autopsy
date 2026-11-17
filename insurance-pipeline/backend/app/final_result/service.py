"""Map an adjudication into a customer-safe, persisted claim status."""

from sqlalchemy.orm import Session

from app.adjudication.schemas import Decision
from app.claim_document_intake.models import IntakeClaim
from app.final_result.schemas import ClaimResult, ClaimResultReason


_STATUS_BY_DECISION = {
    "APPROVED": "APPROVED",
    "REJECTED": "REJECTED",
    "MANUAL_REVIEW": "MANUAL_REVIEW",
}
_MESSAGE_BY_DECISION = {
    "APPROVED": ("CLAIM_APPROVED", "The claim met the v1 adjudication rules."),
    "REJECTED": ("CLAIM_REJECTED", "The claim did not meet one or more coverage rules."),
    "MANUAL_REVIEW": ("CLAIM_REQUIRES_REVIEW", "The claim needs additional review before a final outcome."),
}
_MESSAGE_BY_RULE = {
    "rule.policy_number_match": "The policy number could not be verified against the policy document.",
    "rule.policyholder_match": "The policyholder name could not be verified against the policy document.",
    "rule.incident_in_coverage": "The incident date could not be confirmed within the policy coverage period.",
    "rule.service_in_coverage": "The bill service date could not be confirmed within the policy coverage period.",
    "rule.financial_proof_present": "An accepted hospital bill is needed to verify the claimed amount.",
    "rule.currency_consistent": "The policy and bill currencies could not be verified as consistent.",
    "rule.amount_within_bills": "The claimed amount could not be verified against accepted bill totals.",
    "rule.amount_within_sum_insured": "The claimed amount could not be verified against the policy sum insured.",
    "rule.patient_is_insured": "The bill patient could not be verified as an insured person.",
}


def build_final_result(decision: Decision, *, claim_id: str, run_id: str) -> ClaimResult:
    status = _STATUS_BY_DECISION[decision.decision]
    message_code, message = _MESSAGE_BY_DECISION[decision.decision]
    reasons = [
        ClaimResultReason(
            rule_id=rule.rule_id,
            result=rule.result,
            message=_MESSAGE_BY_RULE.get(rule.rule_id, "A claim rule needs additional review."),
        )
        for rule in decision.rules
        if rule.result in {"fail", "not_evaluable"}
    ]
    return ClaimResult(
        claim_id=claim_id,
        run_id=run_id,
        decision=decision.decision,
        claim_status=status,
        payable_amount=decision.payable_amount,
        message_code=message_code,
        message=message,
        reasons=reasons,
    )


def apply_final_result(db: Session, claim: IntakeClaim, decision: Decision, *, run_id: str) -> ClaimResult:
    result = build_final_result(decision, claim_id=claim.claim_id, run_id=run_id)
    claim.claim_status = result.claim_status
    db.commit()
    return result

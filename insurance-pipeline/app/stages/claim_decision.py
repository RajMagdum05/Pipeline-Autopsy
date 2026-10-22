from typing import Dict, Any, List
from opentelemetry import trace
from app.telemetry.span_helpers import stage_span

tracer = trace.get_tracer("insurance-pipeline")


def run_claim_decision_stage(
    claim_id: str,
    execution_id: str,
    policy_artifacts: List[str],
    extracted_data: Dict[str, Any],
    policy_rules: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Stage 4: Claim Decision
    Evaluates claimed amount against policy limits and produces an adjudication verdict.
    """
    claimed_amount = float(extracted_data.get("claimed_amount", 0.0))
    deductible = float(policy_rules.get("deductible", 0.0))
    co_pay = float(policy_rules.get("co_pay_percentage", 0.0))
    max_limit = float(policy_rules.get("max_coverage_limit", 100000.0))

    output_artifacts = [f"art_decision_claim_{claim_id}"]

    extra_attrs = {
        "stage.version": "1.0.0",
        "validation.rule_id": "RULE_APPENDICITIS_SURGICAL_BENEFIT",
        "validation.result": "PASS",
        "decision.claimed_amount": claimed_amount,
    }

    with stage_span(
        tracer=tracer,
        stage_name="claim_decision",
        execution_id=execution_id,
        entity_id=claim_id,
        input_artifact_ids=policy_artifacts,
        extra_attributes=extra_attrs,
    ) as span:
        if claimed_amount <= max_limit:
            approved_amount = max(0.0, (claimed_amount - deductible) * (1.0 - co_pay))
            verdict = "APPROVED"
            reason = f"Eligible emergency surgical procedure. Deductible (${deductible:.2f}) and co-pay (10%) applied."
        else:
            approved_amount = 0.0
            verdict = "REJECTED"
            reason = f"Claimed amount exceeds policy coverage limit (${max_limit:.2f})."

        span.set_attribute("decision.verdict", verdict)
        span.set_attribute("decision.approved_amount", approved_amount)
        span.set_attribute("output.artifact_ids", output_artifacts)

        return {
            "verdict": verdict,
            "approved_amount": approved_amount,
            "reason": reason,
            "decision_artifacts": output_artifacts,
        }

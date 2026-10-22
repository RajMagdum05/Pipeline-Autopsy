from typing import Dict, Any, List
from opentelemetry import trace
from app.telemetry.span_helpers import stage_span

tracer = trace.get_tracer("insurance-pipeline")


def run_policy_retrieval_stage(
    claim_id: str,
    execution_id: str,
    entity_artifacts: List[str],
    extracted_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Stage 3: Policy Retrieval
    Retrieves policy coverage rules, waiting periods, and limits.
    """
    policy_number = extracted_data.get("policy_number", "UNKNOWN")
    diagnosis = extracted_data.get("diagnosis", "")
    query = f"coverage and room rent limits for {diagnosis} under policy {policy_number}"

    retrieved_chunk_ids = ["chunk_pol_sec_4_surgery", "chunk_pol_sec_12_limits"]
    output_artifacts = [f"art_policy_context_claim_{claim_id}"]

    extra_attrs = {
        "stage.version": "1.0.0",
        "retrieval.query": query,
        "retrieval.chunk_ids": retrieved_chunk_ids,
        "policy.number": policy_number,
    }

    with stage_span(
        tracer=tracer,
        stage_name="policy_retrieval",
        execution_id=execution_id,
        entity_id=claim_id,
        input_artifact_ids=entity_artifacts,
        extra_attributes=extra_attrs,
    ) as span:
        policy_rules = {
            "max_coverage_limit": 10000.00,
            "deductible": 250.00,
            "co_pay_percentage": 0.10,
            "covered_treatments": ["acute appendicitis", "appendectomy", "emergency room"],
            "pre_existing_waiting_period_days": 30,
        }

        span.set_attribute("output.artifact_ids", output_artifacts)
        return {
            "status": "success",
            "policy_rules": policy_rules,
            "retrieved_chunks": retrieved_chunk_ids,
            "policy_artifacts": output_artifacts,
        }

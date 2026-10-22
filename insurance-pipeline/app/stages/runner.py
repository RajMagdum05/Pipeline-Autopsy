import uuid
from typing import Dict, Any, List, Optional
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.telemetry.tracer import get_tracer, flush_telemetry
from app.telemetry.attributes import (
    DEFAULT_PIPELINE_NAME,
    DEFAULT_PIPELINE_VERSION,
    EXECUTION_ENTITY_ID,
    EXECUTION_ID,
    INPUT_ARTIFACT_IDS,
    OUTPUT_ARTIFACT_IDS,
    PIPELINE_NAME,
    PIPELINE_VERSION,
    STAGE_NAME,
    STAGE_STATUS,
)
from app.stages.document_processing import run_document_processing_stage
from app.stages.information_extraction import run_information_extraction_stage
from app.stages.policy_retrieval import run_policy_retrieval_stage
from app.stages.claim_decision import run_claim_decision_stage
from app.stages.decision_validation import run_decision_validation_stage

tracer = get_tracer("insurance-pipeline")


def execute_claim_pipeline(
    claim_id: str,
    raw_document_ids: Optional[List[str]] = None,
    execution_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes the full 5-stage insurance claim pipeline under a single root trace:
    'insurance_claim_execution', emitting strictly compliant OpenTelemetry spans
    as defined by TRACE_CONTRACT.md.
    """
    if not execution_id:
        execution_id = f"EXEC-{uuid.uuid4().hex[:12].upper()}"

    raw_doc_ids = raw_document_ids or ["DOC-001", "DOC-002"]
    root_input_artifacts = [f"doc_{d}" for d in raw_doc_ids]

    # Create exactly ONE root span for the entire execution
    with tracer.start_as_current_span("insurance_claim_execution") as root_span:
        root_span.set_attribute(PIPELINE_NAME, DEFAULT_PIPELINE_NAME)
        root_span.set_attribute(PIPELINE_VERSION, DEFAULT_PIPELINE_VERSION)
        root_span.set_attribute(EXECUTION_ID, execution_id)
        root_span.set_attribute(EXECUTION_ENTITY_ID, str(claim_id))
        root_span.set_attribute(STAGE_NAME, "insurance_claim_execution")
        root_span.set_attribute(STAGE_STATUS, "running")
        root_span.set_attribute(INPUT_ARTIFACT_IDS, root_input_artifacts)
        root_span.set_attribute(OUTPUT_ARTIFACT_IDS, [])

        try:
            # Stage 1: Document Processing
            stage1_res = run_document_processing_stage(
                claim_id=claim_id,
                execution_id=execution_id,
                raw_document_ids=raw_doc_ids,
            )

            # Stage 2: Information Extraction
            stage2_res = run_information_extraction_stage(
                claim_id=claim_id,
                execution_id=execution_id,
                ocr_artifacts=stage1_res["ocr_artifacts"],
                extracted_text=stage1_res["extracted_text"],
            )

            # Stage 3: Policy Retrieval
            stage3_res = run_policy_retrieval_stage(
                claim_id=claim_id,
                execution_id=execution_id,
                entity_artifacts=stage2_res["entity_artifacts"],
                extracted_data=stage2_res["extracted_data"],
            )

            # Stage 4: Claim Decision
            stage4_res = run_claim_decision_stage(
                claim_id=claim_id,
                execution_id=execution_id,
                policy_artifacts=stage3_res["policy_artifacts"],
                extracted_data=stage2_res["extracted_data"],
                policy_rules=stage3_res["policy_rules"],
            )

            # Stage 5: Decision Validation
            stage5_res = run_decision_validation_stage(
                claim_id=claim_id,
                execution_id=execution_id,
                decision_artifacts=stage4_res["decision_artifacts"],
                decision_result=stage4_res,
            )

            final_output_artifacts = (
                stage1_res["ocr_artifacts"]
                + stage2_res["entity_artifacts"]
                + stage3_res["policy_artifacts"]
                + stage4_res["decision_artifacts"]
                + stage5_res["validation_artifacts"]
            )

            root_span.set_attribute(OUTPUT_ARTIFACT_IDS, final_output_artifacts)
            root_span.set_attribute(STAGE_STATUS, "success")
            root_span.set_attribute("decision.verdict", stage4_res["verdict"])
            root_span.set_attribute("decision.payout", stage5_res["final_payout"])
            root_span.set_status(Status(StatusCode.OK))

            result = {
                "claim_id": claim_id,
                "execution_id": execution_id,
                "status": "COMPLETED",
                "verdict": stage4_res["verdict"],
                "approved_amount": stage5_res["final_payout"],
                "reason": stage4_res["reason"],
                "artifacts": final_output_artifacts,
                "stages": {
                    "document_processing": stage1_res["status"],
                    "information_extraction": stage2_res["status"],
                    "policy_retrieval": stage3_res["status"],
                    "claim_decision": stage4_res["verdict"],
                    "decision_validation": "VALIDATED" if stage5_res["is_valid"] else "INVALID",
                },
            }

            return result

        except Exception as exc:
            root_span.set_attribute(STAGE_STATUS, "failed")
            root_span.set_attribute("error.type", type(exc).__name__)
            root_span.set_attribute("error.message", str(exc))
            root_span.set_status(Status(StatusCode.ERROR, description=str(exc)))
            root_span.record_exception(exc)
            raise
        finally:
            flush_telemetry(timeout_millis=2000)

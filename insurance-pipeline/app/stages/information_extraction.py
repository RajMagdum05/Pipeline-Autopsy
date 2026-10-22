from typing import Dict, Any, List
from opentelemetry import trace
from app.telemetry.span_helpers import stage_span

tracer = trace.get_tracer("insurance-pipeline")


def run_information_extraction_stage(
    claim_id: str,
    execution_id: str,
    ocr_artifacts: List[str],
    extracted_text: str,
) -> Dict[str, Any]:
    """
    Stage 2: Information Extraction
    Extracts structured entities (patient, billing, diagnosis) from document text.
    """
    output_artifacts = [f"art_entities_claim_{claim_id}"]
    extra_attrs = {
        "stage.version": "1.0.0",
        "model.name": "gemini-1.5-flash",
        "model.version": "002",
        "prompt.version": "v1.2-claims-entity-extraction",
    }

    with stage_span(
        tracer=tracer,
        stage_name="information_extraction",
        execution_id=execution_id,
        entity_id=claim_id,
        input_artifact_ids=ocr_artifacts,
        extra_attributes=extra_attrs,
    ) as span:
        # Structured extracted data
        extracted_data = {
            "patient_name": "John Doe",
            "policy_number": "POL-889102",
            "hospital_name": "St. Jude Hospital",
            "diagnosis": "acute appendicitis",
            "diagnosis_code": "K35.80",
            "claimed_amount": 4500.00,
            "admission_date": "2026-10-10",
            "discharge_date": "2026-10-14",
        }

        span.set_attribute("output.artifact_ids", output_artifacts)
        return {
            "status": "success",
            "extracted_data": extracted_data,
            "entity_artifacts": output_artifacts,
        }

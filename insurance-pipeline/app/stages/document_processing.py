from typing import Dict, Any, List
from opentelemetry import trace
from app.telemetry.span_helpers import stage_span

tracer = trace.get_tracer("insurance-pipeline")


def run_document_processing_stage(
    claim_id: str,
    execution_id: str,
    raw_document_ids: List[str],
) -> Dict[str, Any]:
    """
    Stage 1: Document Processing
    Stages, inspects, and extracts text/OCR from raw claim files.
    """
    input_artifacts = [f"doc_{doc_id}" for doc_id in raw_document_ids]
    output_artifacts = [f"art_ocr_{doc_id}" for doc_id in raw_document_ids]

    extra_attrs = {
        "stage.version": "1.0.0",
        "document.count": len(raw_document_ids),
        "ocr.engine": "PyMuPDF_Tesseract",
        "ocr.page_count": len(raw_document_ids) or 1,
    }

    with stage_span(
        tracer=tracer,
        stage_name="document_processing",
        execution_id=execution_id,
        entity_id=claim_id,
        input_artifact_ids=input_artifacts,
        extra_attributes=extra_attrs,
    ) as span:
        # Simulate processing / linking
        extracted_text = (
            f"Patient John Doe admitted on 2026-10-10 for acute appendicitis. "
            f"Discharged 2026-10-14. Total bill: $4,500.00. Hospital: St. Jude Hospital. "
            f"Policy: POL-889102."
        )

        span.set_attribute("output.artifact_ids", output_artifacts)
        return {
            "status": "success",
            "document_ids": raw_document_ids,
            "ocr_artifacts": output_artifacts,
            "extracted_text": extracted_text,
        }

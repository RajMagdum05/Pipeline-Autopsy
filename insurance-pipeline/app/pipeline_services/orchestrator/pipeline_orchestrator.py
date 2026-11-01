import logging
import uuid
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.models.claim import Claim
from app.models.document import Document
from app.pipeline_services.ocr import (
    OCRApplicationService,
    OCRQualityValidator,
)
from app.pipeline_services.extraction import extract_claim_from_validated_ocr
from app.pipeline_services.rule_engine import evaluate_claim_rules
from app.schemas import RuleEngineDecision, ValidatedExtractionResult, OCRResult
from app.telemetry.span_helpers import stage_span
from app.telemetry.attributes import (
    INPUT_ARTIFACT_IDS,
    OUTPUT_ARTIFACT_IDS,
    STAGE_STATUS,
    DECISION_RESULT,
    VALIDATION_STATUS,
    DOCUMENTS_TOTAL_COUNT,
    CLAIM_AMOUNT,
)

tracer = trace.get_tracer("enterprise_pipeline.orchestrator")
logger = logging.getLogger("enterprise_pipeline.orchestrator")


class PipelineExecutionError(Exception):
    """Raised when an unrecoverable failure occurs during claim pipeline execution."""
    pass


def run_claim_pipeline(
    claim_id: int,
    db: Session,
    allow_extraction_fallback: bool = False,
    execution_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes the end-to-end enterprise claim processing pipeline under a unified
    OpenTelemetry trace tree rooted at `claim_processing`.
    """
    if not execution_id:
        execution_id = f"EXEC-{uuid.uuid4().hex[:12].upper()}"

    try:
        with stage_span(
            tracer=tracer,
            stage_name="claim_processing",
            execution_id=execution_id,
            entity_id=str(claim_id),
            input_artifact_ids=[],
            safe_error_message="Claim processing failed.",
        ) as root_span:
            # 1. Fetch Claim
            claim = db.query(Claim).filter(Claim.id == claim_id).first()
            if not claim:
                err_msg = f"Claim #{claim_id} not found in database."
                raise PipelineExecutionError(err_msg)

            root_span.set_attribute("claim.amount", float(claim.claim_amount) if claim.claim_amount is not None else 0.0)

            # PHASE 2: Stage: claim_input boundary span
            documents: List[Document] = []
            doc_ids: List[int] = []
            input_artifact_ids: List[str] = []

            with stage_span(
                tracer=tracer,
                stage_name="claim_input",
                execution_id=execution_id,
                entity_id=str(claim_id),
                input_artifact_ids=[],
                safe_error_message="Claim input processing failed.",
            ) as input_span:
                input_span.set_attribute(CLAIM_AMOUNT, float(claim.claim_amount) if claim.claim_amount is not None else 0.0)

                # Query & discover input documents
                documents = db.query(Document).filter(Document.claim_id == claim_id).order_by(Document.id.asc()).all()
                doc_ids = [doc.id for doc in documents]
                input_artifact_ids = [f"doc_{d_id}" for d_id in doc_ids]

                input_span.set_attribute(INPUT_ARTIFACT_IDS, input_artifact_ids)
                input_span.set_attribute(DOCUMENTS_TOTAL_COUNT, len(documents))

                if not documents:
                    input_span.set_attribute(VALIDATION_STATUS, "FAILED")
                    input_span.set_attribute(OUTPUT_ARTIFACT_IDS, [])
                    err_msg = f"No documents found for Claim #{claim_id}."
                    raise PipelineExecutionError(err_msg)

                input_span.set_attribute(VALIDATION_STATUS, "VALIDATED")
                input_span.set_attribute(OUTPUT_ARTIFACT_IDS, input_artifact_ids)

            root_span.set_attribute(INPUT_ARTIFACT_IDS, input_artifact_ids)

            # Stage: Document Processing
            ocr_artifacts: List[str] = []
            total_pages_processed = 0

            with stage_span(
                tracer=tracer,
                stage_name="document_processing",
                execution_id=execution_id,
                entity_id=str(claim_id),
                input_artifact_ids=input_artifact_ids,
                safe_error_message="Document processing failed.",
            ) as doc_span:
                doc_span.set_attribute(DOCUMENTS_TOTAL_COUNT, len(documents))

                # Stage: OCR Extraction
                ocr_app_service = OCRApplicationService()
                with stage_span(
                    tracer=tracer,
                    stage_name="ocr",
                    execution_id=execution_id,
                    entity_id=str(claim_id),
                    input_artifact_ids=input_artifact_ids,
                    extra_attributes={"claim_id": claim_id},
                    safe_error_message="OCR processing failed.",
                ) as ocr_span:
                    ocr_span.set_attribute("ocr.total_documents", len(documents))

                    for doc in documents:
                        if not doc.ocr_result:
                            ocr_res = ocr_app_service.process_document(
                                document_id=doc.id,
                                db=db,
                                claim_id=claim_id,
                                execution_id=execution_id,
                            )
                            doc.ocr_result = ocr_res.model_dump()
                            db.commit()
                            db.refresh(doc)

                        pages = doc.ocr_result.get("pages", []) if isinstance(doc.ocr_result, dict) else getattr(doc.ocr_result, "pages", [])
                        total_pages_processed += len(pages)

                    ocr_artifacts = [f"art_ocr_{doc.id}" for doc in documents]
                    ocr_span.set_attribute(OUTPUT_ARTIFACT_IDS, ocr_artifacts)
                    ocr_span.set_attribute("ocr.total_pages", total_pages_processed)
                    root_span.set_attribute(OUTPUT_ARTIFACT_IDS, ocr_artifacts)

                doc_span.set_attribute(OUTPUT_ARTIFACT_IDS, ocr_artifacts)
                doc_span.set_attribute("ocr.total_pages", total_pages_processed)

                # Stage: OCR Validation
                validator = OCRQualityValidator()
                overall_status = "PASS"
                with stage_span(
                    tracer=tracer,
                    stage_name="ocr_validation",
                    execution_id=execution_id,
                    entity_id=str(claim_id),
                    input_artifact_ids=ocr_artifacts,
                    extra_attributes={"claim_id": claim_id},
                    safe_error_message="OCR quality validation failed.",
                ) as val_span:

                    total_pages = 0
                    passed_pages = 0
                    warning_pages = 0
                    failed_pages = 0

                    for doc in documents:
                        if not doc.ocr_result:
                            continue
                        from app.schemas import OCRResult
                        ocr_obj = OCRResult(**doc.ocr_result) if isinstance(doc.ocr_result, dict) else doc.ocr_result
                        if ocr_obj.document_id is None:
                            ocr_obj = ocr_obj.model_copy(update={"document_id": doc.id})
                        val_res = validator.validate_document(
                            ocr_obj,
                            claim_id=claim_id,
                            execution_id=execution_id,
                        )
                        total_pages += val_res.total_pages
                        passed_pages += val_res.passed_pages_count
                        warning_pages += val_res.warning_pages_count
                        failed_pages += val_res.failed_pages_count

                    overall_status = "FAIL" if failed_pages > 0 else ("WARNING" if warning_pages > 0 else "PASS")
                    val_span.set_attribute("ocr_validation.overall_status", overall_status)
                    val_span.set_attribute("ocr_validation.total_pages", total_pages)
                    val_span.set_attribute("ocr_validation.passed_pages_count", passed_pages)
                    val_span.set_attribute("ocr_validation.warning_pages_count", warning_pages)
                    val_span.set_attribute("ocr_validation.failed_pages_count", failed_pages)
                    val_span.set_attribute(OUTPUT_ARTIFACT_IDS, [f"art_ocr_val_{doc.id}" for doc in documents])
                    if overall_status == "FAIL":
                        val_span.set_attribute(STAGE_STATUS, "failed")
                        val_span.set_attribute("error.type", "OCRQualityValidationError")
                        val_span.set_attribute("error.message", "OCR quality validation failed.")
                        val_span.set_status(Status(StatusCode.ERROR, "OCR quality validation failed."))

                val_status = "VALIDATED" if overall_status in ("PASS", "WARNING") else "FAILED"
                doc_span.set_attribute(VALIDATION_STATUS, val_status)
                doc_span.set_attribute(OUTPUT_ARTIFACT_IDS, ocr_artifacts)
                if overall_status == "FAIL":
                    doc_span.set_attribute(STAGE_STATUS, "partial")
                    doc_span.set_attribute("error.type", "OCRQualityValidationError")
                    doc_span.set_attribute("error.message", "OCR quality validation failed.")
                    doc_span.set_status(Status(StatusCode.ERROR, "OCR quality validation failed."))

            root_span.set_attribute("documents.total_count", len(documents))

            # Stage: Gemini Information Extraction & Validation
            extraction_result = extract_claim_from_validated_ocr(
                claim_id=claim_id,
                documents=documents,
                db_session=db,
                allow_fallback=allow_extraction_fallback,
                execution_id=execution_id,
                input_artifact_ids=ocr_artifacts,
            )
            root_span.set_attribute(OUTPUT_ARTIFACT_IDS, ocr_artifacts + [f"art_entities_claim_{claim_id}"])

            # Stage: Deterministic Rule Engine
            decision_result = evaluate_claim_rules(
                extraction_input=extraction_result,
                db_session=db,
            )

            # Stage: Temporary Business Decision
            with stage_span(
                tracer=tracer,
                stage_name="temporary_business_decision",
                execution_id=execution_id,
                entity_id=str(claim_id),
                input_artifact_ids=[f"art_decision_claim_{claim_id}"],
                extra_attributes={"claim_id": claim_id},
                safe_error_message="Business decision update failed.",
            ) as dec_span:
                dec_span.set_attribute("decision.result", decision_result.decision)
                dec_span.set_attribute("decision.total_rules_evaluated", decision_result.total_rules)
                dec_span.set_attribute("decision.passed_rules", decision_result.passed_rules)
                dec_span.set_attribute("decision.failed_rules", decision_result.failed_rules)
                dec_span.set_attribute("decision.missing_data_rules", decision_result.missing_data_rules)

                # Update Claim Status in DB
                claim.status = decision_result.decision
                db.commit()
                db.refresh(claim)
                dec_span.set_attribute(OUTPUT_ARTIFACT_IDS, [f"art_decision_claim_{claim_id}"])

            # PHASE 7: final_result boundary span
            final_output_artifacts = [
                f"art_ocr_claim_{claim_id}",
                f"art_entities_claim_{claim_id}",
                f"art_decision_claim_{claim_id}",
            ]
            with stage_span(
                tracer=tracer,
                stage_name="final_result",
                execution_id=execution_id,
                entity_id=str(claim_id),
                input_artifact_ids=[f"art_decision_claim_{claim_id}"],
                extra_attributes={"claim_id": claim_id},
                safe_error_message="Final result construction failed.",
            ) as final_span:
                final_span.set_attribute("final.decision", decision_result.decision)
                final_span.set_attribute("final.result", decision_result.decision_reason)
                final_span.set_attribute("validation.status", "VALIDATED" if decision_result.decision in ("APPROVED", "REJECTED") else "FLAGGED")
                final_span.set_attribute(OUTPUT_ARTIFACT_IDS, final_output_artifacts)

            # Final Root Span Attributes
            root_span.set_attribute(DECISION_RESULT, decision_result.decision)
            root_span.set_attribute(OUTPUT_ARTIFACT_IDS, final_output_artifacts)

            return {
                "claim_id": claim_id,
                "customer_name": claim.customer_name,
                "status": claim.status,
                "total_documents": len(documents),
                "total_pages": total_pages_processed,
                "extraction": extraction_result.model_dump(),
                "decision": decision_result.model_dump(),
            }

    except Exception as exc:
        logger.error(f"Claim #{claim_id} pipeline execution failed: {exc}", exc_info=True)
        raise

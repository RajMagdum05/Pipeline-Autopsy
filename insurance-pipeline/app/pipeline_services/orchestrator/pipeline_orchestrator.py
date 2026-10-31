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
from app.telemetry.attributes import (
    DEFAULT_PIPELINE_NAME,
    DEFAULT_PIPELINE_VERSION,
    PIPELINE_NAME,
    PIPELINE_VERSION,
    EXECUTION_ID,
    EXECUTION_ENTITY_ID,
    STAGE_NAME,
    STAGE_VERSION,
    STAGE_STATUS,
    INPUT_ARTIFACT_IDS,
    OUTPUT_ARTIFACT_IDS,
    ERROR_TYPE,
    ERROR_MESSAGE,
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

    with tracer.start_as_current_span("claim_processing") as root_span:
        root_span.set_attribute("claim_id", claim_id)
        root_span.set_attribute(EXECUTION_ID, execution_id)
        root_span.set_attribute(EXECUTION_ENTITY_ID, str(claim_id))
        root_span.set_attribute(PIPELINE_NAME, DEFAULT_PIPELINE_NAME)
        root_span.set_attribute(PIPELINE_VERSION, DEFAULT_PIPELINE_VERSION)
        root_span.set_attribute(STAGE_NAME, "claim_processing")
        root_span.set_attribute(STAGE_VERSION, "1.0.0")
        root_span.set_attribute(STAGE_STATUS, "running")

        try:
            # 1. Fetch Claim
            claim = db.query(Claim).filter(Claim.id == claim_id).first()
            if not claim:
                err_msg = f"Claim #{claim_id} not found in database."
                root_span.set_attribute(STAGE_STATUS, "failed")
                root_span.set_attribute(ERROR_TYPE, "PipelineExecutionError")
                root_span.set_attribute(ERROR_MESSAGE, err_msg)
                root_span.set_status(Status(StatusCode.ERROR, err_msg))
                raise PipelineExecutionError(err_msg)

            root_span.set_attribute("claim.amount", float(claim.claim_amount) if claim.claim_amount is not None else 0.0)
            root_span.set_attribute("claim.initial_status", str(claim.status))

            # Query Documents
            documents: List[Document] = db.query(Document).filter(Document.claim_id == claim_id).order_by(Document.id.asc()).all()
            doc_ids = [doc.id for doc in documents]
            input_artifact_ids = [f"doc_{d_id}" for d_id in doc_ids]

            # PHASE 2: Stage: claim_input boundary span
            with tracer.start_as_current_span("claim_input") as input_span:
                input_span.set_attribute("claim_id", claim_id)
                input_span.set_attribute(EXECUTION_ID, execution_id)
                input_span.set_attribute(EXECUTION_ENTITY_ID, str(claim_id))
                input_span.set_attribute(PIPELINE_NAME, DEFAULT_PIPELINE_NAME)
                input_span.set_attribute(PIPELINE_VERSION, DEFAULT_PIPELINE_VERSION)
                input_span.set_attribute(STAGE_NAME, "claim_input")
                input_span.set_attribute(STAGE_VERSION, "1.0.0")
                input_span.set_attribute("input.document_id", str(doc_ids[0]) if len(doc_ids) == 1 else str(doc_ids))
                input_span.set_attribute(INPUT_ARTIFACT_IDS, input_artifact_ids)
                input_span.set_attribute(OUTPUT_ARTIFACT_IDS, input_artifact_ids)

                if not documents:
                    err_msg = f"No documents found for Claim #{claim_id}."
                    input_span.set_attribute(STAGE_STATUS, "failed")
                    input_span.set_attribute(ERROR_TYPE, "PipelineExecutionError")
                    input_span.set_attribute(ERROR_MESSAGE, err_msg)
                    input_span.set_status(Status(StatusCode.ERROR, err_msg))
                    root_span.set_attribute(STAGE_STATUS, "failed")
                    root_span.set_attribute(ERROR_TYPE, "PipelineExecutionError")
                    root_span.set_attribute(ERROR_MESSAGE, err_msg)
                    root_span.set_status(Status(StatusCode.ERROR, err_msg))
                    raise PipelineExecutionError(err_msg)

                input_span.set_attribute(STAGE_STATUS, "success")
                input_span.set_status(Status(StatusCode.OK))

            root_span.set_attribute(INPUT_ARTIFACT_IDS, input_artifact_ids)

            # Stage: Document Processing
            with tracer.start_as_current_span("document_processing") as doc_span:
                doc_span.set_attribute("claim_id", claim_id)
                doc_span.set_attribute(EXECUTION_ID, execution_id)
                doc_span.set_attribute(EXECUTION_ENTITY_ID, str(claim_id))
                doc_span.set_attribute(PIPELINE_NAME, DEFAULT_PIPELINE_NAME)
                doc_span.set_attribute(PIPELINE_VERSION, DEFAULT_PIPELINE_VERSION)
                doc_span.set_attribute(STAGE_NAME, "document_processing")
                doc_span.set_attribute(STAGE_VERSION, "1.0.0")
                doc_span.set_attribute(STAGE_STATUS, "success")
                doc_span.set_attribute(INPUT_ARTIFACT_IDS, input_artifact_ids)
                doc_span.set_attribute(OUTPUT_ARTIFACT_IDS, [f"art_ocr_{d_id}" for d_id in doc_ids])
                doc_span.set_attribute("documents.total_count", len(documents))
                doc_span.set_attribute("documents.ids", str(doc_ids))
                doc_span.set_status(Status(StatusCode.OK))

            root_span.set_attribute("documents.total_count", len(documents))

            # Stage: OCR Extraction
            ocr_app_service = OCRApplicationService()
            total_pages_processed = 0
            with tracer.start_as_current_span("ocr") as ocr_span:
                ocr_span.set_attribute("claim_id", claim_id)
                ocr_span.set_attribute(EXECUTION_ID, execution_id)
                ocr_span.set_attribute(EXECUTION_ENTITY_ID, str(claim_id))
                ocr_span.set_attribute(PIPELINE_NAME, DEFAULT_PIPELINE_NAME)
                ocr_span.set_attribute(PIPELINE_VERSION, DEFAULT_PIPELINE_VERSION)
                ocr_span.set_attribute(STAGE_NAME, "ocr")
                ocr_span.set_attribute(STAGE_VERSION, "1.0.0")
                ocr_span.set_attribute(STAGE_STATUS, "running")
                ocr_span.set_attribute(INPUT_ARTIFACT_IDS, input_artifact_ids)
                ocr_span.set_attribute("ocr.total_documents", len(documents))

                for doc in documents:
                    if not doc.ocr_result:
                        ocr_res = ocr_app_service.process_document(document_id=doc.id, db=db)
                        doc.ocr_result = ocr_res.model_dump()
                        db.commit()
                        db.refresh(doc)
                    
                    pages = doc.ocr_result.get("pages", []) if isinstance(doc.ocr_result, dict) else getattr(doc.ocr_result, "pages", [])
                    total_pages_processed += len(pages)

                ocr_artifacts = [f"art_ocr_{doc.id}" for doc in documents]
                ocr_span.set_attribute(OUTPUT_ARTIFACT_IDS, ocr_artifacts)
                ocr_span.set_attribute("ocr.total_pages", total_pages_processed)
                ocr_span.set_attribute(STAGE_STATUS, "success")
                ocr_span.set_status(Status(StatusCode.OK))

            # Stage: OCR Validation
            validator = OCRQualityValidator()
            with tracer.start_as_current_span("ocr_validation") as val_span:
                val_span.set_attribute("claim_id", claim_id)
                val_span.set_attribute(EXECUTION_ID, execution_id)
                val_span.set_attribute(EXECUTION_ENTITY_ID, str(claim_id))
                val_span.set_attribute(PIPELINE_NAME, DEFAULT_PIPELINE_NAME)
                val_span.set_attribute(PIPELINE_VERSION, DEFAULT_PIPELINE_VERSION)
                val_span.set_attribute(STAGE_NAME, "ocr_validation")
                val_span.set_attribute(STAGE_VERSION, "1.0.0")
                val_span.set_attribute(INPUT_ARTIFACT_IDS, ocr_artifacts)

                total_pages = 0
                passed_pages = 0
                warning_pages = 0
                failed_pages = 0

                for doc in documents:
                    if not doc.ocr_result:
                        continue
                    from app.schemas import OCRResult
                    ocr_obj = OCRResult(**doc.ocr_result) if isinstance(doc.ocr_result, dict) else doc.ocr_result
                    val_res = validator.validate_document(ocr_obj)
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
                val_span.set_attribute(STAGE_STATUS, "success")
                val_span.set_status(Status(StatusCode.OK))

            # Stage: Gemini Information Extraction & Validation
            extraction_result = extract_claim_from_validated_ocr(
                claim_id=claim_id,
                documents=documents,
                db_session=db,
                allow_fallback=allow_extraction_fallback,
                execution_id=execution_id,
            )

            # Stage: Deterministic Rule Engine
            decision_result = evaluate_claim_rules(
                extraction_input=extraction_result,
                db_session=db,
            )

            # Stage: Temporary Business Decision
            with tracer.start_as_current_span("temporary_business_decision") as dec_span:
                dec_span.set_attribute("claim_id", claim_id)
                dec_span.set_attribute(EXECUTION_ID, execution_id)
                dec_span.set_attribute(EXECUTION_ENTITY_ID, str(claim_id))
                dec_span.set_attribute(PIPELINE_NAME, DEFAULT_PIPELINE_NAME)
                dec_span.set_attribute(PIPELINE_VERSION, DEFAULT_PIPELINE_VERSION)
                dec_span.set_attribute(STAGE_NAME, "temporary_business_decision")
                dec_span.set_attribute(STAGE_VERSION, "1.0.0")
                dec_span.set_attribute(INPUT_ARTIFACT_IDS, [f"art_entities_claim_{claim_id}"])
                dec_span.set_attribute(OUTPUT_ARTIFACT_IDS, [f"art_decision_claim_{claim_id}"])
                dec_span.set_attribute("decision.result", decision_result.decision)
                dec_span.set_attribute("decision.reason", decision_result.decision_reason)
                dec_span.set_attribute("decision.total_rules_evaluated", decision_result.total_rules)
                dec_span.set_attribute("decision.passed_rules", decision_result.passed_rules)
                dec_span.set_attribute("decision.failed_rules", decision_result.failed_rules)
                dec_span.set_attribute("decision.missing_data_rules", decision_result.missing_data_rules)
                dec_span.set_attribute(STAGE_STATUS, "success")

                # Update Claim Status in DB
                claim.status = decision_result.decision
                db.commit()
                db.refresh(claim)

                dec_span.set_status(Status(StatusCode.OK))

            # PHASE 7: final_result boundary span
            final_output_artifacts = [
                f"art_ocr_claim_{claim_id}",
                f"art_entities_claim_{claim_id}",
                f"art_decision_claim_{claim_id}",
            ]
            with tracer.start_as_current_span("final_result") as final_span:
                final_span.set_attribute("claim_id", claim_id)
                final_span.set_attribute(EXECUTION_ID, execution_id)
                final_span.set_attribute(EXECUTION_ENTITY_ID, str(claim_id))
                final_span.set_attribute(PIPELINE_NAME, DEFAULT_PIPELINE_NAME)
                final_span.set_attribute(PIPELINE_VERSION, DEFAULT_PIPELINE_VERSION)
                final_span.set_attribute(STAGE_NAME, "final_result")
                final_span.set_attribute(STAGE_VERSION, "1.0.0")
                final_span.set_attribute(STAGE_STATUS, "success")
                final_span.set_attribute("final.decision", decision_result.decision)
                final_span.set_attribute("final.result", decision_result.decision_reason)
                final_span.set_attribute("validation.status", "VALIDATED" if decision_result.decision in ("APPROVED", "REJECTED") else "FLAGGED")
                final_span.set_attribute(INPUT_ARTIFACT_IDS, [f"art_decision_claim_{claim_id}"])
                final_span.set_attribute(OUTPUT_ARTIFACT_IDS, final_output_artifacts)
                final_span.set_status(Status(StatusCode.OK))

            # Final Root Span Attributes
            root_span.set_attribute("execution.status", "SUCCESS")
            root_span.set_attribute("final.decision", decision_result.decision)
            root_span.set_attribute("final_decision", decision_result.decision)
            root_span.set_attribute(OUTPUT_ARTIFACT_IDS, final_output_artifacts)
            root_span.set_attribute(STAGE_STATUS, "success")
            root_span.set_status(Status(StatusCode.OK))

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
            root_span.record_exception(exc)
            root_span.set_attribute("execution.status", "FAILED")
            root_span.set_attribute(STAGE_STATUS, "failed")
            root_span.set_attribute(ERROR_TYPE, type(exc).__name__)
            root_span.set_attribute(ERROR_MESSAGE, str(exc))
            root_span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.error(f"Claim #{claim_id} pipeline execution failed: {exc}", exc_info=True)
            raise

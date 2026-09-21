import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.models.claim import Claim
from app.models.document import Document
from app.services.ocr import (
    OCRApplicationService,
    OCRQualityValidator,
)
from app.services.extraction_service import extract_claim_from_validated_ocr
from app.services.rule_engine_service import evaluate_claim_rules
from app.schemas import RuleEngineDecision, ValidatedExtractionResult, OCRResult

tracer = trace.get_tracer("enterprise_pipeline.orchestrator")
logger = logging.getLogger("enterprise_pipeline.orchestrator")


class PipelineExecutionError(Exception):
    """Raised when an unrecoverable failure occurs during claim pipeline execution."""
    pass


def run_claim_pipeline(
    claim_id: int,
    db: Session,
    allow_extraction_fallback: bool = False,
) -> Dict[str, Any]:
    """
    Executes the end-to-end enterprise claim processing pipeline under a unified
    OpenTelemetry trace tree rooted at `claim_processing`.

    Span hierarchy:
    claim_processing (root span)
    ├── document_processing
    ├── ocr
    │   ├── ocr_page_1
    │   ├── ocr_page_2
    │   └── ...
    ├── ocr_validation
    ├── information_extraction
    ├── extraction_validation
    ├── rule_engine
    └── temporary_business_decision

    Args:
        claim_id: Database ID of the claim to process.
        db: SQLAlchemy database session.
        allow_extraction_fallback: Whether to allow offline extraction if Gemini API is unavailable.

    Returns:
        Dict containing claim details, OCR validation summary, extraction result, and rule decision.
    """
    with tracer.start_as_current_span("claim_processing") as root_span:
        root_span.set_attribute("claim_id", claim_id)

        try:
            # 1. Fetch Claim
            claim = db.query(Claim).filter(Claim.id == claim_id).first()
            if not claim:
                err_msg = f"Claim #{claim_id} not found in database."
                root_span.set_status(Status(StatusCode.ERROR, err_msg))
                raise PipelineExecutionError(err_msg)

            root_span.set_attribute("claim.customer_name", str(claim.customer_name))
            root_span.set_attribute("claim.amount", float(claim.claim_amount) if claim.claim_amount is not None else 0.0)
            root_span.set_attribute("claim.initial_status", str(claim.status))

            # 2. Stage: Document Processing
            documents: List[Document] = []
            with tracer.start_as_current_span("document_processing") as doc_span:
                doc_span.set_attribute("claim_id", claim_id)
                documents = db.query(Document).filter(Document.claim_id == claim_id).order_by(Document.id.asc()).all()

                if not documents:
                    err_msg = f"No documents found for Claim #{claim_id}."
                    doc_span.set_status(Status(StatusCode.ERROR, err_msg))
                    raise PipelineExecutionError(err_msg)

                doc_ids = [doc.id for doc in documents]
                doc_span.set_attribute("documents.total_count", len(documents))
                doc_span.set_attribute("documents.ids", str(doc_ids))
                doc_span.set_status(Status(StatusCode.OK))

            root_span.set_attribute("documents.total_count", len(documents))

            # 3. Stage: OCR Extraction
            ocr_app_service = OCRApplicationService()
            total_pages_processed = 0
            with tracer.start_as_current_span("ocr") as ocr_span:
                ocr_span.set_attribute("claim_id", claim_id)
                ocr_span.set_attribute("ocr.total_documents", len(documents))

                for doc in documents:
                    if not doc.ocr_result:
                        ocr_res = ocr_app_service.process_document(document_id=doc.id, db=db)
                        doc.ocr_result = ocr_res.model_dump()
                        db.commit()
                        db.refresh(doc)
                    
                    pages = doc.ocr_result.get("pages", []) if isinstance(doc.ocr_result, dict) else getattr(doc.ocr_result, "pages", [])
                    total_pages_processed += len(pages)

                ocr_span.set_attribute("ocr.total_pages", total_pages_processed)
                ocr_span.set_status(Status(StatusCode.OK))

            # 4. Stage: OCR Validation
            validator = OCRQualityValidator()
            with tracer.start_as_current_span("ocr_validation") as val_span:
                val_span.set_attribute("claim_id", claim_id)

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
                val_span.set_status(Status(StatusCode.OK))

            # 5. Stage: Gemini Information Extraction & Validation
            # Note: extract_claim_from_validated_ocr runs 'information_extraction' and 'extraction_validation' spans
            extraction_result = extract_claim_from_validated_ocr(
                claim_id=claim_id,
                documents=documents,
                db_session=db,
                allow_fallback=allow_extraction_fallback,
            )

            # 6. Stage: Deterministic Rule Engine
            # Note: evaluate_claim_rules runs 'rule_engine' span
            decision_result = evaluate_claim_rules(
                extraction_input=extraction_result,
                db_session=db,
            )

            # 7. Stage: Temporary Business Decision
            with tracer.start_as_current_span("temporary_business_decision") as dec_span:
                dec_span.set_attribute("claim_id", claim_id)
                dec_span.set_attribute("decision.result", decision_result.decision)
                dec_span.set_attribute("decision.reason", decision_result.decision_reason)
                dec_span.set_attribute("decision.total_rules_evaluated", decision_result.total_rules)
                dec_span.set_attribute("decision.passed_rules", decision_result.passed_rules)
                dec_span.set_attribute("decision.failed_rules", decision_result.failed_rules)
                dec_span.set_attribute("decision.missing_data_rules", decision_result.missing_data_rules)

                # Update Claim Status in DB
                claim.status = decision_result.decision
                db.commit()
                db.refresh(claim)

                dec_span.set_status(Status(StatusCode.OK))

            # Final Root Span Attributes
            root_span.set_attribute("execution.status", "SUCCESS")
            root_span.set_attribute("final_decision", decision_result.decision)
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
            root_span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.error(f"Claim #{claim_id} pipeline execution failed: {exc}", exc_info=True)
            raise

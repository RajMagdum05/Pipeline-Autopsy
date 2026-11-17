import time
from typing import Union
from sqlalchemy.orm import Session
from opentelemetry import trace

from app.schemas import OCRResult
from app.models import Document
from app.pipeline_services.ocr.exceptions import DocumentProcessingError, DocumentNotFoundError
from app.pipeline_services.ocr.document_loader import DocumentLoader
from app.pipeline_services.ocr.evidence_extractor import OCREvidenceExtractor
from app.pipeline_services.ocr.normalizer import OCRNormalizer
from app.pipeline_services.ocr.persistence_service import OCRPersistenceService
from app.telemetry.span_helpers import stage_span
from app.telemetry.attributes import OUTPUT_ARTIFACT_IDS

tracer = trace.get_tracer("enterprise_pipeline.ocr")


class OCRApplicationService:
    """
    End-to-End OCR Application Orchestrator with OpenTelemetry Tracing.

    Coordinates document loading, routing (PyMuPDF vs Tesseract), evidence extraction,
    canonical normalization, and PostgreSQL database persistence within a single trace context.
    """

    def __init__(self):
        self.loader = DocumentLoader()
        self.evidence_extractor = OCREvidenceExtractor()
        self.normalizer = OCRNormalizer()
        self.persistence_service = OCRPersistenceService()

    def process_document(
        self,
        document_id: Union[int, str],
        db: Session,
        claim_id: Optional[Union[int, str]] = None,
        execution_id: Optional[str] = None,
    ) -> OCRResult:
        """
        Executes end-to-end OCR processing for a document record within an OpenTelemetry trace context.

        Args:
            document_id: Database primary key of the Document.
            db: Active SQLAlchemy Session.

        Returns:
            OCRResult: Persisted canonical OCR result.

        Raises:
            DocumentNotFoundError: If Document record or file is missing.
            DocumentProcessingError: If validation or OCR processing fails.
        """
        doc_id_int = int(document_id)
        parent_attrs = getattr(trace.get_current_span(), "attributes", {}) or {}
        resolved_claim_id = claim_id or parent_attrs.get("execution.entity_id") or "unknown"
        resolved_execution_id = execution_id or parent_attrs.get("execution.id") or "exec_unknown"
        doc_artifact_ids = [f"doc_{doc_id_int}"]
        ocr_artifact_ids = [f"art_ocr_{doc_id_int}"]

        with stage_span(
            tracer=tracer,
            stage_name="ocr.process_document",
            execution_id=str(resolved_execution_id),
            entity_id=str(resolved_claim_id),
            input_artifact_ids=doc_artifact_ids,
            extra_attributes={"document_id": doc_id_int},
            safe_error_message="OCR document processing failed.",
        ) as span:
            doc = db.query(Document).filter(Document.id == doc_id_int).first()
            if not doc:
                raise DocumentNotFoundError(f"Document #{document_id} not found in database.")
            if not doc.file_path:
                raise DocumentProcessingError(f"Document #{document_id} has no stored file path.")

            if doc.claim_id:
                span.set_attribute("claim_id", doc.claim_id)
            if doc.document_type:
                span.set_attribute("document_type", doc.document_type)

            with stage_span(
                tracer=tracer,
                stage_name="document.load",
                execution_id=str(resolved_execution_id),
                entity_id=str(resolved_claim_id),
                input_artifact_ids=doc_artifact_ids,
                extra_attributes={"document_id": doc_id_int},
                safe_error_message="Document loading failed.",
            ) as load_span:
                validated_doc = self.loader.load_and_validate(doc.file_path)
                load_span.set_attribute("file_type", validated_doc.extension)
                load_span.set_attribute("file_size_bytes", validated_doc.file_size_bytes)
                span.set_attribute("file_type", validated_doc.extension)

            with stage_span(
                tracer=tracer,
                stage_name="document.inspect",
                execution_id=str(resolved_execution_id),
                entity_id=str(resolved_claim_id),
                input_artifact_ids=doc_artifact_ids,
                extra_attributes={"extension": validated_doc.extension},
                safe_error_message="Document inspection failed.",
            ) as inspect_span:
                inspection = None
                if validated_doc.extension.lower() == ".pdf":
                    inspection = self.evidence_extractor.inspector.inspect(
                        validated_doc,
                        document_id=doc_id_int,
                        claim_id=resolved_claim_id,
                        execution_id=str(resolved_execution_id),
                    )
                    inspect_span.set_attribute("inspection.has_embedded_text", inspection.has_embedded_text)
                    inspect_span.set_attribute("page_count", inspection.total_pages)
                else:
                    inspect_span.set_attribute("inspection.has_embedded_text", False)
                    inspect_span.set_attribute("page_count", 1)

            start_time = time.time()
            with stage_span(
                tracer=tracer,
                stage_name="ocr.extract",
                execution_id=str(resolved_execution_id),
                entity_id=str(resolved_claim_id),
                input_artifact_ids=doc_artifact_ids,
                extra_attributes={"document_id": doc_id_int},
                safe_error_message="OCR evidence extraction failed.",
            ) as extract_span:
                evidence_result = self.evidence_extractor.extract_evidence(
                    validated_doc,
                    inspection=inspection,
                    claim_id=resolved_claim_id,
                    execution_id=str(resolved_execution_id),
                )
                engine_name = evidence_result.engine.lower()
                extract_span.set_attribute("ocr.engine", engine_name)
                extract_span.set_attribute("page_count", evidence_result.total_pages)
                extract_span.set_attribute(OUTPUT_ARTIFACT_IDS, ocr_artifact_ids)
                span.set_attribute("ocr.engine", engine_name)
                span.set_attribute("page_count", evidence_result.total_pages)

            duration_ms = round((time.time() - start_time) * 1000, 2)
            with stage_span(
                tracer=tracer,
                stage_name="ocr.normalize",
                execution_id=str(resolved_execution_id),
                entity_id=str(resolved_claim_id),
                input_artifact_ids=doc_artifact_ids,
                extra_attributes={"document_id": doc_id_int},
                safe_error_message="OCR normalization failed.",
            ) as norm_span:
                canonical_ocr = self.normalizer.normalize_evidence(
                    evidence_result=evidence_result,
                    document_id=doc_id_int,
                    duration_ms=duration_ms,
                )
                total_char_length = sum(len(p.raw_text) for p in canonical_ocr.pages)
                norm_span.set_attribute("ocr.engine", canonical_ocr.engine)
                norm_span.set_attribute("extracted_text_length", total_char_length)
                norm_span.set_attribute(OUTPUT_ARTIFACT_IDS, ocr_artifact_ids)
                span.set_attribute("ocr.engine_version", canonical_ocr.engine_version or "unknown")
                span.set_attribute("extracted_text_length", total_char_length)

            with stage_span(
                tracer=tracer,
                stage_name="ocr.persist",
                execution_id=str(resolved_execution_id),
                entity_id=str(resolved_claim_id),
                input_artifact_ids=ocr_artifact_ids,
                extra_attributes={"document_id": doc_id_int},
                safe_error_message="OCR persistence failed.",
            ) as persist_span:
                self.persistence_service.save_ocr_result(
                    db=db,
                    document_id=doc_id_int,
                    ocr_result=canonical_ocr,
                )
                persist_span.set_attribute(OUTPUT_ARTIFACT_IDS, ocr_artifact_ids)

            span.set_attribute("processing_status", "success")
            span.set_attribute(OUTPUT_ARTIFACT_IDS, ocr_artifact_ids)
            return canonical_ocr


def process_document(
    document_id: Union[int, str],
    db: Session,
) -> OCRResult:
    """
    Application entry point to execute end-to-end OCR processing for a document ID.

    Args:
        document_id: Database document identifier.
        db: Active SQLAlchemy database session.

    Returns:
        OCRResult: Persisted canonical OCR result.
    """
    orchestrator = OCRApplicationService()
    return orchestrator.process_document(document_id=document_id, db=db)

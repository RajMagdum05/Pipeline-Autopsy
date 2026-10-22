import time
from typing import Union
from sqlalchemy.orm import Session
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.schemas import OCRResult
from app.models import Document
from app.services.ocr.exceptions import DocumentProcessingError, DocumentNotFoundError
from app.services.ocr.document_loader import DocumentLoader
from app.services.ocr.evidence_extractor import OCREvidenceExtractor
from app.services.ocr.normalizer import OCRNormalizer
from app.services.ocr.persistence_service import OCRPersistenceService

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

        with tracer.start_as_current_span("ocr.process_document") as span:
            span.set_attribute("document_id", doc_id_int)

            doc = db.query(Document).filter(Document.id == doc_id_int).first()
            if not doc:
                err_msg = f"Document #{document_id} not found in database."
                span.set_status(Status(StatusCode.ERROR, err_msg))
                raise DocumentNotFoundError(err_msg)

            if not doc.file_path:
                err_msg = f"Document #{document_id} has no stored file path."
                span.set_status(Status(StatusCode.ERROR, err_msg))
                raise DocumentProcessingError(err_msg)

            if hasattr(doc, "claim_id") and doc.claim_id:
                span.set_attribute("claim_id", doc.claim_id)
            if hasattr(doc, "document_type") and doc.document_type:
                span.set_attribute("document_type", doc.document_type)

            # 1. Load and validate stored file path
            with tracer.start_as_current_span("document.load") as load_span:
                try:
                    validated_doc = self.loader.load_and_validate(doc.file_path)
                    load_span.set_attribute("file_name", validated_doc.file_name)
                    load_span.set_attribute("file_type", validated_doc.extension)
                    load_span.set_attribute("file_size_bytes", validated_doc.file_size_bytes)
                    span.set_attribute("file_name", validated_doc.file_name)
                    span.set_attribute("file_type", validated_doc.extension)
                except Exception as err:
                    load_span.record_exception(err)
                    load_span.set_status(Status(StatusCode.ERROR, str(err)))
                    span.set_status(Status(StatusCode.ERROR, str(err)))
                    raise

            # 2. Inspect PDF / extract evidence
            with tracer.start_as_current_span("document.inspect") as inspect_span:
                inspect_span.set_attribute("extension", validated_doc.extension)

            start_time = time.time()
            with tracer.start_as_current_span("ocr.extract") as extract_span:
                try:
                    evidence_result = self.evidence_extractor.extract_evidence(validated_doc)
                    engine_name = evidence_result.engine.lower()
                    extract_span.set_attribute("ocr.engine", engine_name)
                    extract_span.set_attribute("page_count", evidence_result.total_pages)

                    span.set_attribute("ocr.engine", engine_name)
                    span.set_attribute("page_count", evidence_result.total_pages)
                except Exception as err:
                    extract_span.record_exception(err)
                    extract_span.set_status(Status(StatusCode.ERROR, str(err)))
                    span.set_status(Status(StatusCode.ERROR, str(err)))
                    raise

            duration_ms = round((time.time() - start_time) * 1000, 2)

            # 3. Normalize evidence into canonical OCRResult model
            with tracer.start_as_current_span("ocr.normalize") as norm_span:
                try:
                    canonical_ocr = self.normalizer.normalize_evidence(
                        evidence_result=evidence_result,
                        document_id=doc_id_int,
                        duration_ms=duration_ms,
                    )
                    total_char_length = sum(len(p.raw_text) for p in canonical_ocr.pages)
                    norm_span.set_attribute("ocr.engine", canonical_ocr.engine)
                    norm_span.set_attribute("extracted_text_length", total_char_length)

                    span.set_attribute("ocr.engine_version", canonical_ocr.engine_version or "unknown")
                    span.set_attribute("extracted_text_length", total_char_length)
                except Exception as err:
                    norm_span.record_exception(err)
                    norm_span.set_status(Status(StatusCode.ERROR, str(err)))
                    span.set_status(Status(StatusCode.ERROR, str(err)))
                    raise

            # 4. Persist normalized result in PostgreSQL
            with tracer.start_as_current_span("ocr.persist") as persist_span:
                try:
                    self.persistence_service.save_ocr_result(
                        db=db,
                        document_id=doc_id_int,
                        ocr_result=canonical_ocr,
                    )
                    persist_span.set_attribute("document_id", doc_id_int)
                    persist_span.set_attribute("status", "success")
                except Exception as err:
                    persist_span.record_exception(err)
                    persist_span.set_status(Status(StatusCode.ERROR, str(err)))
                    span.set_status(Status(StatusCode.ERROR, str(err)))
                    raise

            span.set_attribute("processing_status", "success")
            span.set_status(Status(StatusCode.OK))
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

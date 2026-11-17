"""Application service chaining load, inspection, extraction, validation and persistence."""
import re
import time

from sqlalchemy.orm import Session

from app.document_processing.document_loader import DocumentLoader
from app.document_processing.evidence_extractor import OCREvidenceExtractor
from app.document_processing.exceptions import DocumentNotFoundError, DocumentProcessingError
from app.document_processing.normalizer import OCRNormalizer
from app.document_processing.persistence_service import OCRPersistenceService
from app.document_processing.repository import DocumentProcessingRepository
from app.document_processing.schemas import ProcessDocumentResponse

LOW_QUALITY_WARNING = "OCR quality is low; extraction may be unreliable"


def parse_document_id(value: str | int) -> int:
    match = re.fullmatch(r"(?:doc_)?(\d+)", str(value))
    if not match:
        raise DocumentProcessingError("document_id must be an integer or use the doc_<integer> format.")
    return int(match.group(1))


def calculate_quality_score(status: str, confidence: float | None) -> float:
    if status == "PASS" and confidence is None:
        return 0.95
    confidence = max(0.0, confidence or 0.0)
    if status == "PASS":
        return round(min(1.0, 0.8 + max(0.0, confidence - 60.0) / 40.0 * 0.2), 4)
    if status == "WARNING":
        return round(min(0.79, 0.4 + confidence / 60.0 * 0.4), 4)
    return round(min(confidence / 35.0, 1.0) * 0.39, 4)


class DocumentProcessingService:
    def __init__(self):
        self.repository = DocumentProcessingRepository()
        self.loader = DocumentLoader()
        self.extractor = OCREvidenceExtractor()
        self.normalizer = OCRNormalizer()
        self.persistence = OCRPersistenceService()

    def process_document(self, db: Session, document_id: str | int) -> ProcessDocumentResponse:
        doc_id = parse_document_id(document_id)
        document = self.repository.get_document(db, doc_id)
        if document is None:
            raise DocumentNotFoundError(f"Document #{doc_id} not found.")
        try:
            validated = self.loader.load_and_validate(document.file_path)
            inspection = self.extractor.inspector.inspect(validated, document_id=doc_id) if validated.extension == ".pdf" else None
            started = time.perf_counter()
            evidence = self.extractor.extract_evidence(validated, inspection=inspection)
            duration = round((time.perf_counter() - started) * 1000, 2)
            result = self.normalizer.normalize_evidence(evidence, document_id=doc_id, duration_ms=duration)
            validation = result.processing_metadata["validation"]
            quality_status = validation["overall_status"]
            confidence = validation.get("avg_document_confidence")
            score = calculate_quality_score(quality_status, confidence)
            result.processing_metadata["quality_score"] = score

            if score < 0.4:
                status = "COMPLETED_LOW_QUALITY"
                result.processing_metadata["warning"] = LOW_QUALITY_WARNING
            elif score < 0.7:
                status = "COMPLETED_LOW_QUALITY"
                result.processing_metadata["warning"] = LOW_QUALITY_WARNING
            else:
                status = "COMPLETED"

            record = self.persistence.save_ocr_result(db, doc_id, result, document_status=status)
            methods = {page.extraction_method for page in result.pages}
            if len(methods) > 1:
                method = "hybrid"
            elif methods == {"DIRECT_TEXT"}:
                method = "pymupdf"
            elif methods == {"TESSERACT_OCR"}:
                method = "tesseract"
            else:
                method = "unknown"
            return ProcessDocumentResponse(
                document_id=str(document_id), artifact_id=str(record.id), status=status,
                document_type=validated.extension.lstrip("."), extraction_method=method,
                quality_score=score, quality_status=quality_status, page_count=len(result.pages),
                warning=result.processing_metadata.get("warning"),
            )
        except Exception as exc:
            db.rollback()
            document = self.repository.get_document(db, doc_id)
            if document is not None:
                document.ocr_status = "failed"
                document.ocr_result = {"status": "failed", "errors": [str(exc)]}
                db.commit()
            if isinstance(exc, (DocumentNotFoundError, DocumentProcessingError)):
                raise
            raise DocumentProcessingError(f"Document processing failed: {exc}") from exc


document_processing_service = DocumentProcessingService()

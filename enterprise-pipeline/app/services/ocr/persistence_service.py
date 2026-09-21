from datetime import datetime, timezone
from typing import Union
from sqlalchemy.orm import Session

from app.schemas import OCRResult
from app.models import Document, OCRResultRecord
from app.services.ocr.exceptions import DocumentProcessingError, DocumentNotFoundError


class OCRPersistenceService:
    """
    Production-grade Persistence Service for OCR results.

    Responsible for saving and retrieving canonical OCRResult objects
    in PostgreSQL JSONB via the 1-to-1 OCRResultRecord model.
    """

    def save_ocr_result(
        self,
        db: Session,
        document_id: Union[int, str],
        ocr_result: OCRResult,
    ) -> OCRResultRecord:
        """
        Persists a canonical OCRResult into the database.

        Args:
            db: Active SQLAlchemy database session.
            document_id: Database identifier of the parent Document.
            ocr_result: Normalized OCRResult Pydantic model.

        Returns:
            OCRResultRecord: Saved database record entity.

        Raises:
            DocumentNotFoundError: If the specified document_id does not exist.
            DocumentProcessingError: If database persistence fails.
        """
        doc_id_int = int(document_id)
        doc = db.query(Document).filter(Document.id == doc_id_int).first()
        if not doc:
            raise DocumentNotFoundError(f"Document #{document_id} not found in database.")

        # Serialize Pydantic OCRResult into JSON-compatible Python dictionary
        result_dict = ocr_result.model_dump()
        result_dict["document_id"] = doc_id_int

        now_iso = datetime.now(timezone.utc).isoformat()

        try:
            record = (
                db.query(OCRResultRecord)
                .filter(OCRResultRecord.document_id == doc_id_int)
                .first()
            )

            if record:
                record.engine = ocr_result.engine
                record.engine_version = ocr_result.engine_version
                record.result = result_dict
                record.updated_at = now_iso
            else:
                record = OCRResultRecord(
                    document_id=doc_id_int,
                    engine=ocr_result.engine,
                    engine_version=ocr_result.engine_version,
                    result=result_dict,
                    created_at=now_iso,
                    updated_at=now_iso,
                )
                db.add(record)

            # Synchronize Document metadata fields for backward compatibility
            doc.ocr_status = "completed"
            doc.ocr_result = result_dict

            db.commit()
            db.refresh(record)
            return record
        except Exception as err:
            db.rollback()
            raise DocumentProcessingError(
                f"Failed to persist OCR result for document #{document_id}: {str(err)}"
            ) from err

    def get_ocr_result(
        self,
        db: Session,
        document_id: Union[int, str],
    ) -> OCRResult:
        """
        Retrieves and reconstructs the canonical OCRResult for a document.

        Args:
            db: Active SQLAlchemy database session.
            document_id: Database identifier of the parent Document.

        Returns:
            OCRResult: Reconstructed canonical Pydantic model.

        Raises:
            DocumentNotFoundError: If document or OCR result record is missing.
        """
        doc_id_int = int(document_id)
        doc = db.query(Document).filter(Document.id == doc_id_int).first()
        if not doc:
            raise DocumentNotFoundError(f"Document #{document_id} not found in database.")

        record = (
            db.query(OCRResultRecord)
            .filter(OCRResultRecord.document_id == doc_id_int)
            .first()
        )

        if not record or not record.result:
            raise DocumentNotFoundError(f"OCR result for document #{document_id} not found.")

        try:
            return OCRResult.model_validate(record.result)
        except Exception as err:
            raise DocumentProcessingError(
                f"Failed to parse stored OCR JSON for document #{document_id}: {str(err)}"
            ) from err


def save_ocr_result(
    db: Session,
    document_id: Union[int, str],
    ocr_result: OCRResult,
) -> OCRResultRecord:
    """Convenience function to persist an OCR result."""
    service = OCRPersistenceService()
    return service.save_ocr_result(db, document_id, ocr_result)


def get_ocr_result(
    db: Session,
    document_id: Union[int, str],
) -> OCRResult:
    """Convenience function to fetch an OCR result."""
    service = OCRPersistenceService()
    return service.get_ocr_result(db, document_id)

"""Database adapter for document processing; no claim or policy logic."""
from sqlalchemy.orm import Session

from app.document_processing.models import Document, OCRResultRecord


class DocumentProcessingRepository:
    def get_document(self, db: Session, document_id: int) -> Document | None:
        return db.query(Document).filter(Document.id == document_id).one_or_none()

    def get_artifact(self, db: Session, document_id: int) -> OCRResultRecord | None:
        return db.query(OCRResultRecord).filter(OCRResultRecord.document_id == document_id).one_or_none()

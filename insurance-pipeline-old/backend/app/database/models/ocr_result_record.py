from datetime import datetime, timezone
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON
from app.database import Base


class OCRResultRecord(Base):
    """
    Database model for persisting normalized OCR results in PostgreSQL JSONB.
    Maintains a 1-to-1 relationship with the Document entity.
    """
    __tablename__ = "ocr_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, unique=True, index=True)
    engine = Column(String, nullable=False)
    engine_version = Column(String, nullable=True)
    
    # Uses JSONB on PostgreSQL, falls back to JSON on SQLite for test compatibility
    result = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    
    created_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())
    updated_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())

    document = relationship("Document", back_populates="ocr_result_record")

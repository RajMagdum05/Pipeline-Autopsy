from datetime import datetime, timezone
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from app.database import Base


class ExtractionResultRecord(Base):
    """
    Database model for persisting Information Extraction results.
    Stores claim-level structured extraction records without duplicating full raw OCR text.
    """
    __tablename__ = "extraction_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False, index=True)
    execution_id = Column(String, nullable=False, index=True)
    
    # List of source document IDs used in this extraction
    source_document_ids = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    
    extraction_prompt_version = Column(String, nullable=False, default="v1.0.0")
    extraction_model = Column(String, nullable=False, default="gemini-3-flash-preview")
    extraction_status = Column(String, nullable=False, default="SUCCESS")  # "SUCCESS", "VALIDATION_ERROR", "API_ERROR"
    
    # Validated structured extraction JSON data
    extracted_data = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    
    # List of validation error strings if status is non-SUCCESS
    validation_errors = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    
    created_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())
    updated_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())

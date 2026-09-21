from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON
from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False)
    document_type = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    ocr_status = Column(String, nullable=False, default="pending")
    
    # Backward-compatible inline OCR JSON column
    ocr_result = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)

    # 1-to-1 relationship with dedicated OCRResultRecord entity
    ocr_result_record = relationship(
        "OCRResultRecord",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )

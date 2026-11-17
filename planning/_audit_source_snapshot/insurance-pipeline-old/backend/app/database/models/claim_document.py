from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    BigInteger,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from app.database import Base


class ClaimDocument(Base):
    """Metadata for one stored Stage 1 upload; file bytes stay on disk."""

    __tablename__ = "claim_documents"
    __table_args__ = (
        CheckConstraint("document_slot >= 0 AND document_slot <= 3", name="ck_claim_documents_slot_range"),
        CheckConstraint(
            "document_type IS NULL OR document_type IN "
            "('policy_document', 'hospital_bill', 'fir_accident_report', 'medical_report', "
            "'discharge_summary', 'repair_estimate', 'other_supporting_document')",
            name="ck_claim_documents_document_type",
        ),
        UniqueConstraint("claim_id", "document_slot", name="uq_claim_documents_claim_slot"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    claim_id = Column(String, ForeignKey("claims.claim_id", ondelete="CASCADE"), nullable=False, index=True)
    # Slot 0 is the required policy paper; slots 1-3 are proof documents.
    document_slot = Column(Integer, nullable=False)
    document_type = Column(String, nullable=True)
    original_file_name = Column(String, nullable=True)
    stored_file_name = Column(String, nullable=True)
    storage_path = Column(String, nullable=True)
    mime_type = Column(String, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    checksum_sha256 = Column(String(64), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())

    claim = relationship("IntakeClaim", back_populates="documents")

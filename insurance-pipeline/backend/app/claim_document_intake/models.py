"""Existing public claim/document tables, adapted from insurance-pipeline-old."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON, Uuid

from app.shared.database import Base


class IntakeClaim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint("age >= 0 AND age <= 120", name="ck_claims_age_range"),
        CheckConstraint("claimed_amount > 0", name="ck_claims_claimed_amount_positive"),
        UniqueConstraint("legacy_id", name="uq_claims_legacy_id"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    legacy_id = Column(Integer, nullable=True)
    claim_id = Column(String, nullable=False, unique=True)
    policyholder_name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    policy_number = Column(String, nullable=False)
    incident_date = Column(Date, nullable=False)
    description = Column(String, nullable=False)
    claimed_amount = Column(Numeric(12, 2), nullable=False)
    claim_status = Column(String, nullable=False, default="RECEIVED", server_default="RECEIVED")
    access_token_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    documents = relationship(
        "ClaimDocument", back_populates="claim", cascade="all, delete-orphan",
        order_by="ClaimDocument.document_slot",
    )


class ClaimDocument(Base):
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
    document_slot = Column(Integer, nullable=False)
    document_type = Column(String, nullable=True)
    original_file_name = Column(String, nullable=True)
    stored_file_name = Column(String, nullable=True)
    storage_path = Column(String, nullable=True)
    mime_type = Column(String, nullable=True)
    file_size_bytes = Column(BigInteger, nullable=True)
    checksum_sha256 = Column(String(64), nullable=True)
    version_number = Column(Integer, nullable=False, default=1, server_default="1")
    uploaded_at = Column(DateTime(timezone=True), nullable=True, server_default=func.now())
    claim = relationship("IntakeClaim", back_populates="documents")


class ClaimDocumentVersion(Base):
    __tablename__ = "claim_document_versions"
    __table_args__ = (UniqueConstraint("claim_document_id", "version_number", name="uq_claim_document_version"),)
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    claim_document_id = Column(Uuid(as_uuid=True), ForeignKey("claim_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id = Column(String, ForeignKey("claims.claim_id", ondelete="CASCADE"), nullable=False, index=True)
    document_type = Column(String, nullable=False)
    original_file_name = Column(String)
    stored_file_name = Column(String)
    storage_path = Column(String)
    mime_type = Column(String)
    file_size_bytes = Column(BigInteger)
    checksum_sha256 = Column(String(64))
    version_number = Column(Integer, nullable=False)
    uploaded_at = Column(DateTime(timezone=True))
    archived_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ocr_result = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    ocr_record = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)


class Claim(Base):
    """Established integer-key claim table retained for existing document FK behavior."""
    __tablename__ = "legacy_claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_name = Column(String, nullable=False)
    claim_amount = Column(Numeric(10, 2), nullable=False)
    status = Column(String, nullable=False)


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("legacy_claims.id"), nullable=False)
    document_type = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    ocr_status = Column(String, nullable=False, default="pending")
    ocr_result = Column(JSON().with_variant(JSONB, "postgresql"), nullable=True)
    ocr_result_record = relationship(
        "OCRResultRecord",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )


class OCRResultRecord(Base):
    __tablename__ = "ocr_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, unique=True, index=True)
    engine = Column(String, nullable=False)
    engine_version = Column(String, nullable=True)
    result = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    created_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())
    updated_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())
    document = relationship("Document", back_populates="ocr_result_record")

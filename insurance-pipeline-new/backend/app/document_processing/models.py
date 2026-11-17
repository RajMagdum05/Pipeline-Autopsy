"""Compatibility adapter for the shared document and OCR artifact tables.

The underlying tables are declared with the intake schema for compatibility;
document processing depends only on these generic document/artifact records.
"""
from app.claim_document_intake.models import Document, OCRResultRecord
from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import Uuid
from uuid import uuid4
from sqlalchemy.sql import text
from app.shared.database import Base


class ProcessingRun(Base):
    __tablename__ = "document_processing_runs"
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    claim_id = Column(String, ForeignKey("claims.claim_id", ondelete="CASCADE"), nullable=False, index=True)
    config_version = Column(String, nullable=False)
    status = Column(String, nullable=False, default="RUNNING")
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True))
    error = Column(Text)


Index("uq_active_document_processing_claim", ProcessingRun.claim_id, unique=True,
      postgresql_where=text("status = 'RUNNING'"), sqlite_where=text("status = 'RUNNING'"))


class ProcessedDocument(Base):
    __tablename__ = "processed_documents"
    __table_args__ = (UniqueConstraint("run_id", "document_id", "attempt_number", name="uq_processed_run_document_attempt"),)
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id = Column(Uuid(as_uuid=True), ForeignKey("document_processing_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    intake_document_id = Column(Uuid(as_uuid=True), ForeignKey("claim_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id = Column(String, ForeignKey("claims.claim_id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)
    attempt_number = Column(Integer, nullable=False, default=1)
    checksum_sha256 = Column(String(64), nullable=True)
    status = Column(String, nullable=False, default="PENDING")
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    error = Column(Text)
    quality_status = Column(String)
    disposition = Column(String, nullable=False, default="RUNNING")
    confidence_score = Column(Float)
    confidence_source = Column(Text)
    confidence_scale = Column(String)
    confidence_aggregation_method = Column(Text)
    confidence_word_count = Column(Integer, nullable=False, default=0)
    confidence_missing_word_count = Column(Integer, nullable=False, default=0)
    confidence_coverage = Column(Float)
    low_confidence_word_count = Column(Integer, nullable=False, default=0)
    low_confidence_word_proportion = Column(Float)
    quality_metrics = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    validation_reasons = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    engine = Column(String)
    engine_version = Column(String)
    configuration = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)


class ProcessedPage(Base):
    __tablename__ = "processed_document_pages"
    __table_args__ = (UniqueConstraint("processed_document_id", "page_number", name="uq_processed_page_number"),)
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    processed_document_id = Column(Uuid(as_uuid=True), ForeignKey("processed_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    quality_status = Column(String, nullable=False)
    extraction_method = Column(String, nullable=False)
    engine = Column(String, nullable=False)
    engine_version = Column(String)
    disposition = Column(String, nullable=False)
    confidence_score = Column(Float)
    confidence_source = Column(Text)
    confidence_scale = Column(String)
    confidence_aggregation_method = Column(Text)
    confidence_word_count = Column(Integer, nullable=False, default=0)
    confidence_missing_word_count = Column(Integer, nullable=False, default=0)
    confidence_coverage = Column(Float)
    low_confidence_word_count = Column(Integer, nullable=False, default=0)
    low_confidence_word_proportion = Column(Float)
    quality_metrics = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    validation_reasons = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=False)
    raw_text = Column(Text, nullable=False, default="")
    layout = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    error = Column(Text)


class SemanticArtifact(Base):
    """Versioned per-document classification, extraction, and application validation."""
    __tablename__ = "document_semantic_artifacts"
    __table_args__ = (UniqueConstraint("processed_document_id", "artifact_kind", name="uq_document_semantic_artifact_kind"),)
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    processed_document_id = Column(Uuid(as_uuid=True), ForeignKey("processed_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id = Column(String, ForeignKey("claims.claim_id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    input_checksum_sha256 = Column(String(64), nullable=False)
    attempt_number = Column(Integer, nullable=False)
    artifact_kind = Column(String, nullable=False)
    status = Column(String, nullable=False)
    payload = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict)
    model_id = Column(String)
    prompt_version = Column(String, nullable=False)
    schema_version = Column(String, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=False)
    error_code = Column(String)

__all__ = ["Document", "OCRResultRecord", "ProcessingRun", "ProcessedDocument", "ProcessedPage", "SemanticArtifact"]

"""Persistence record for deterministic run-scoped adjudication."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, JSON, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import Uuid

from app.shared.database import Base


class AdjudicationResult(Base):
    __tablename__ = "adjudication_results"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_adjudication_result_run_id"),
        CheckConstraint(
            "decision IN ('APPROVED', 'REJECTED', 'MANUAL_REVIEW')",
            name="ck_adjudication_result_decision",
        ),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id = Column(Uuid(as_uuid=True), ForeignKey("document_processing_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id = Column(String, ForeignKey("claims.claim_id", ondelete="CASCADE"), nullable=False, index=True)
    rules_version = Column(String, nullable=False)
    decision = Column(String, nullable=False)
    payable_amount = Column(Numeric(12, 2))
    rules = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list)
    inputs_checksum = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), default=lambda: datetime.now(timezone.utc))

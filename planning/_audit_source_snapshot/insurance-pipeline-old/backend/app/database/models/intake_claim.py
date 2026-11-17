from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid

from app.database import Base


class IntakeClaim(Base):
    """UUID-backed claim record created by the Stage 1 intake API."""

    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint("age >= 0 AND age <= 120", name="ck_claims_age_range"),
        CheckConstraint("claimed_amount > 0", name="ck_claims_claimed_amount_positive"),
        UniqueConstraint("legacy_id", name="uq_claims_legacy_id"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    # Reserved mapping for a later, explicit handoff to the integer-ID pipeline.
    legacy_id = Column(Integer, nullable=True)
    claim_id = Column(String, nullable=False, unique=True)
    policyholder_name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    policy_number = Column(String, nullable=False)
    incident_date = Column(Date, nullable=False)
    description = Column(String, nullable=False)
    claimed_amount = Column(Numeric(12, 2), nullable=False)
    claim_status = Column(String, nullable=False, default="submitted", server_default="submitted")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    documents = relationship(
        "ClaimDocument",
        back_populates="claim",
        cascade="all, delete-orphan",
        order_by="ClaimDocument.document_slot",
    )

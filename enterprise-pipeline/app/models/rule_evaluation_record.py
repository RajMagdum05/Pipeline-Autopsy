from datetime import datetime, timezone
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from app.database import Base


class RuleEvaluationRecord(Base):
    """
    Database model for persisting deterministic Rule Engine evaluation results.
    Stores complete claim-level evaluation metrics, individual rule results, and decision data.
    """
    __tablename__ = "rule_evaluations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False, index=True)
    execution_id = Column(String, nullable=False, index=True)

    decision = Column(String, nullable=False)  # "APPROVED", "REJECTED", "FLAGGED_FOR_REVIEW"
    decision_reason = Column(String, nullable=False)

    total_rules = Column(Integer, nullable=False, default=0)
    passed_rules = Column(Integer, nullable=False, default=0)
    failed_rules = Column(Integer, nullable=False, default=0)
    missing_data_rules = Column(Integer, nullable=False, default=0)

    # JSON array storing independent evaluation results for all evaluated rules
    evaluated_rules = Column(JSON().with_variant(JSONB, "postgresql"), nullable=False)

    created_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())
    updated_at = Column(String, nullable=False, default=lambda: datetime.now(timezone.utc).isoformat())

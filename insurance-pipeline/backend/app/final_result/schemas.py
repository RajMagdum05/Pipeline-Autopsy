"""Safe final result response models."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimResultReason(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    result: Literal["fail", "not_evaluable"]
    message: str


class ClaimResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    run_id: str
    decision: Literal["APPROVED", "REJECTED", "MANUAL_REVIEW"]
    claim_status: Literal["APPROVED", "REJECTED", "MANUAL_REVIEW"]
    payable_amount: Decimal | None = None
    message_code: str
    message: str
    reasons: list[ClaimResultReason] = Field(default_factory=list)

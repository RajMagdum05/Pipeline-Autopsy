"""Public, PII-free decision structures for the adjudication boundary."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InputReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1)
    field: str = Field(min_length=1)


class RuleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1)
    result: Literal["pass", "fail", "not_evaluable"]
    consequence: Literal["REJECT", "REFER"] | None = None
    inputs: tuple[InputReference, ...] = ()
    reason_code: str | None = None


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: Literal["APPROVED", "REJECTED", "MANUAL_REVIEW"]
    rules_version: str
    payable_amount: Decimal | None = None
    rules: tuple[RuleResult, ...]
    note: str = "Deductible/copay not applied in v1"


class AdjudicationInputMissing(ValueError):
    """Raised when the policy or supporting evidence cannot enter adjudication."""

    def __init__(self, missing_kind: Literal["policy", "proof"], message: str):
        self.missing_kind = missing_kind
        super().__init__(message)

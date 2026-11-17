"""HTTP response shape for a full claim run."""

from pydantic import BaseModel, Field

from app.adjudication.schemas import Decision


class ClaimRunResponse(BaseModel):
    run_id: str
    claim_id: str
    status: str
    policy_document_id: str | None = None
    proof_document_ids: list[str] = Field(default_factory=list)
    failed_document_ids: list[str] = Field(default_factory=list)
    decision: Decision | None = None
    error: str | None = None

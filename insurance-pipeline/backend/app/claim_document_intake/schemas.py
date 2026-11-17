from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClaimDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: str
    document_slot: int
    document_type: str | None
    original_file_name: str | None
    stored_file_name: str | None
    storage_path: str | None
    mime_type: str | None
    file_size_bytes: int | None
    checksum_sha256: str | None
    uploaded_at: datetime | None
    version_number: int = 1


class ClaimCreatedResponse(BaseModel):
    claim_id: str
    claim_status: str
    document_ids: list[UUID]
    legacy_id: int
    documents: list[ClaimDocumentResponse]
    claim_access_token: str | None = None


class DocumentStatusResponse(BaseModel):
    document_id: UUID
    declared_type: str
    detected_type: str | None = None
    detected_subtype: str | None = None
    status: str
    extraction_status: str = "not_started"
    extraction_subtype: str | None = None
    extracted_facts: list[dict] | None = None
    extraction_warnings: list[str] = Field(default_factory=list)
    validation_reasons: list[str] = Field(default_factory=list)
    validation_issues: list[dict] = Field(default_factory=list)
    input_checksum_sha256: str | None = None
    version_number: int
    can_replace: bool = True


class ClaimDocumentStatusesResponse(BaseModel):
    claim_id: str
    documents: list[DocumentStatusResponse]


class DocumentReplacementResponse(BaseModel):
    document_id: UUID
    declared_type: str
    version_number: int
    checksum_sha256: str
    status: str = "waiting_for_text_processing"


class ClaimResponse(ClaimCreatedResponse):
    id: UUID
    policyholder_name: str
    age: int
    policy_number: str
    incident_date: date
    description: str
    claimed_amount: Decimal
    created_at: datetime


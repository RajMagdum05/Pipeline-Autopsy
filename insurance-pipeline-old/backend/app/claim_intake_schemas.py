from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    legacy_id: int | None
    claim_id: str
    policyholder_name: str
    age: int
    policy_number: str
    incident_date: date
    description: str
    claimed_amount: Decimal
    claim_status: str
    created_at: datetime
    documents: list[ClaimDocumentResponse]


class ClaimCreatedResponse(BaseModel):
    claim_id: str
    claim_status: str
    legacy_id: int
    documents: list[ClaimDocumentResponse]

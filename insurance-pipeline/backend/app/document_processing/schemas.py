from typing import Any

from pydantic import BaseModel, Field


class OCRWord(BaseModel):
    text: str
    confidence: float | None = None
    bounding_box: dict[str, float] | list[float] | None = None


class OCRLine(BaseModel):
    text: str
    confidence: float | None = None
    bounding_box: dict[str, float] | list[float] | None = None
    words: list[OCRWord] = Field(default_factory=list)


class OCRPage(BaseModel):
    document_id: int | str | None = None
    page_number: int
    width: float | None = None
    height: float | None = None
    raw_text: str
    lines: list[OCRLine] = Field(default_factory=list)
    status: str = "DIRECT_TEXT"
    extraction_method: str = "DIRECT_TEXT"
    error: str | None = None


class OCRResult(BaseModel):
    document_id: int | str | None = None
    status: str = "success"
    engine: str
    engine_version: str | None = None
    created_at: str | None = None
    processing_duration_ms: float | None = None
    processing_metadata: dict[str, Any] = Field(default_factory=dict)
    pages: list[OCRPage] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ProcessDocumentRequest(BaseModel):
    document_id: str = Field(..., min_length=1)


class ProcessClaimRequest(BaseModel):
    config_version: str = Field(default="intake-v1", min_length=1, max_length=64)
    fault: str | None = Field(default=None, max_length=64)


class ProcessClaimResponse(BaseModel):
    run_id: str
    claim_id: str
    status: str
    policy_document_id: str | None = None
    proof_document_ids: list[str] = Field(default_factory=list)
    failed_document_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class ProcessDocumentResponse(BaseModel):
    document_id: str
    artifact_id: str | None = None
    status: str
    document_type: str | None = None
    extraction_method: str | None = None
    quality_score: float | None = None
    quality_status: str | None = None
    page_count: int = 0
    warning: str | None = None
    error: str | None = None

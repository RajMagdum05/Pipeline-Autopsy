from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field
import uuid

from .enums import EvidenceType


class Evidence(BaseModel):
    """
    Observable forensic artifacts, snippets, or references supporting a Failure or Autopsy finding.

    Design Principle: Keeps large/raw payloads out of hot telemetry paths by storing
    references, URIs, and digests rather than raw megabyte-sized buffers.
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique evidence record ID")
    execution_id: str = Field(..., description="Related Execution ID")
    trace_id: Optional[str] = Field(default=None, description="Related Trace ID if scoped to a trace")
    span_id: Optional[str] = Field(default=None, description="Related Span ID if scoped to an operation")
    evidence_type: EvidenceType = Field(..., description="Classification of the evidence artifact")
    reference_uri: Optional[str] = Field(
        default=None,
        description="External storage URI, object path (e.g. s3://, blob://, file://), or database pointer",
    )
    digest: Optional[str] = Field(
        default=None,
        description="Cryptographic hash (e.g. SHA-256) of the referenced evidence payload for tamper detection",
    )
    summary: str = Field(..., min_length=1, description="Concise human-readable description of what this evidence proves")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Contextual metadata (e.g., payload_size_bytes, content_type, line_range, redacted: bool)",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp captured")

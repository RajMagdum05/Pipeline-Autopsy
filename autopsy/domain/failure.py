from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
import uuid

from .enums import FailureType, SeverityLevel


class Failure(BaseModel):
    """
    An identified execution problem or anomaly associated with a trace/span and substantiated by evidence.
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique failure record ID")
    execution_id: str = Field(..., description="ID of the failed Execution")
    trace_id: Optional[str] = Field(default=None, description="Related OpenTelemetry trace ID")
    span_id: Optional[str] = Field(default=None, description="Specific span where failure originated, if localized")
    failure_type: FailureType = Field(..., description="Taxonomy classification of failure")
    severity: SeverityLevel = Field(default=SeverityLevel.HIGH, description="Impact severity assessment")
    error_class: Optional[str] = Field(default=None, description="Canonical error name (e.g., 'ResourceExhausted', 'Timeout')")
    description: str = Field(..., min_length=1, description="Clear description of the observed failure behavior")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of Evidence records backing this failure")
    root_cause_hypothesis: Optional[str] = Field(default=None, description="Inferred or verified root cause hypothesis")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Extensible contextual failure metadata")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp detected")

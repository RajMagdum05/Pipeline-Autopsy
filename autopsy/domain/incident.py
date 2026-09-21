from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
import uuid

from .enums import IncidentStatus, SeverityLevel


class Incident(BaseModel):
    """
    A top-level Autopsy case or aggregated issue requiring operational attention, triage, or post-mortem.
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique incident identifier")
    execution_id: str = Field(..., description="ID of the affected Execution")
    title: str = Field(..., min_length=1, description="Concise human-readable incident title")
    status: IncidentStatus = Field(default=IncidentStatus.OPEN, description="Current triage/investigation state")
    severity: SeverityLevel = Field(default=SeverityLevel.HIGH, description="Overall incident severity")
    summary: str = Field(..., min_length=1, description="Executive summary of the failure and systemic impact")
    failure_ids: List[str] = Field(default_factory=list, description="Associated Failure record IDs contributing to incident")
    diagnosis_reference: Optional[str] = Field(
        default=None,
        description="Reference or URI pointing to the full diagnostic autopsy post-mortem report",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Timestamp opened")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Last status update timestamp")
    resolved_at: Optional[datetime] = Field(default=None, description="Timestamp resolved or mitigated")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Generic extensible metadata (tags, assignees, links)")

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field
import uuid

from .enums import ExecutionStatus


class Execution(BaseModel):
    """
    One single concrete execution run of an observed Pipeline.
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique execution run ID")
    pipeline_id: str = Field(..., description="ID of the parent Pipeline")
    status: ExecutionStatus = Field(default=ExecutionStatus.PENDING, description="Current execution state")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Execution start timestamp")
    ended_at: Optional[datetime] = Field(default=None, description="Execution end timestamp")
    duration_ms: Optional[float] = Field(default=None, description="Total execution duration in milliseconds")
    environment: str = Field(default="production", description="Runtime environment (e.g. dev, staging, prod)")
    trigger_type: str = Field(default="manual", description="Trigger mechanism (e.g. api, cron, event, user)")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Generic runtime attributes (sanitized)")

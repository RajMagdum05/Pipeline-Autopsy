from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field
import uuid

from .enums import SpanKind, SpanStatusCode


class Event(BaseModel):
    """
    A timestamped event / log record occurring inside a Span.
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique event identifier")
    span_id: str = Field(..., description="ID of the parent Span")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Event occurrence timestamp")
    name: str = Field(..., min_length=1, description="Event name (e.g. 'model_invoked', 'cache_hit')")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Structured key-value context (sanitized)")


class Span(BaseModel):
    """
    One observable discrete unit of work within a Trace.
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Internal unique record ID")
    span_id: str = Field(..., description="OpenTelemetry 64-bit hex or unique span identifier")
    trace_id: str = Field(..., description="OpenTelemetry 128-bit hex or unique trace identifier")
    parent_span_id: Optional[str] = Field(default=None, description="Parent span identifier for DAG hierarchy")
    service_name: str = Field(..., min_length=1, description="Name of the service emitting the span")
    operation_name: str = Field(..., min_length=1, description="Operation or function name being timed")
    kind: SpanKind = Field(default=SpanKind.INTERNAL, description="Span communication classification")
    start_time: datetime = Field(..., description="Operation start timestamp")
    end_time: Optional[datetime] = Field(default=None, description="Operation end timestamp")
    duration_ms: Optional[float] = Field(default=None, description="Span duration in milliseconds")
    status_code: SpanStatusCode = Field(default=SpanStatusCode.UNSET, description="Operation result status code")
    status_message: Optional[str] = Field(default=None, description="Error or diagnostic status message")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Structured attributes / tags (sanitized)")
    events: List[Event] = Field(default_factory=list, description="Timestamped events recorded within the span")


class Trace(BaseModel):
    """
    The correlated distributed execution trace representing an entire request/workflow execution.
    """
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Internal unique record ID")
    trace_id: str = Field(..., description="OpenTelemetry hex trace identifier")
    execution_id: str = Field(..., description="ID of the parent Execution")
    root_span_id: Optional[str] = Field(default=None, description="Span ID of the entry root span")
    start_time: Optional[datetime] = Field(default=None, description="Trace start timestamp")
    end_time: Optional[datetime] = Field(default=None, description="Trace end timestamp")
    duration_ms: Optional[float] = Field(default=None, description="Overall trace duration in milliseconds")
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Trace-level metadata attributes")

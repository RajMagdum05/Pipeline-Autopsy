from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Text,
    Float,
    DateTime,
    ForeignKey,
    Index,
    JSON,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
import uuid

from autopsy.db.database import Base


def _gen_uuid() -> str:
    return str(uuid.uuid4())


# Extensible JSON type supporting PostgreSQL JSONB natively with generic JSON fallback
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class ProjectModel(Base):
    """
    SQLAlchemy ORM model for Customer Projects / Tenants.
    Table: autopsy_projects
    """
    __tablename__ = "autopsy_projects"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="ACTIVE", nullable=False, index=True)
    metadata_json = Column(JSON_TYPE, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    api_keys = relationship("ApiKeyModel", back_populates="project", cascade="all, delete-orphan")


class ApiKeyModel(Base):
    """
    SQLAlchemy ORM model for Hashed API Key Credentials.
    Table: autopsy_api_keys
    """
    __tablename__ = "autopsy_api_keys"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    project_id = Column(String(36), ForeignKey("autopsy_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), default="default-key", nullable=False)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    key_prefix = Column(String(20), nullable=False)
    status = Column(String(50), default="ACTIVE", nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("ProjectModel", back_populates="api_keys")


class PipelineModel(Base):
    """
    SQLAlchemy ORM model for logical Pipelines in Autopsy.
    Table: autopsy_pipelines
    """
    __tablename__ = "autopsy_pipelines"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    project_id = Column(String(255), default="default", nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=True)
    version = Column(String(50), default="1.0.0", nullable=False)
    tags = Column(JSON_TYPE, default=list, nullable=False)
    metadata_json = Column(JSON_TYPE, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    executions = relationship("ExecutionModel", back_populates="pipeline", cascade="all, delete-orphan")


class ExecutionModel(Base):
    """
    SQLAlchemy ORM model for concrete Execution runs.
    Table: autopsy_executions
    """
    __tablename__ = "autopsy_executions"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    project_id = Column(String(255), default="default", nullable=False, index=True)
    pipeline_id = Column(String(36), ForeignKey("autopsy_pipelines.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), default="PENDING", nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)
    environment = Column(String(50), default="production", nullable=False)
    trigger_type = Column(String(50), default="manual", nullable=False)
    attributes = Column(JSON_TYPE, default=dict, nullable=False)

    pipeline = relationship("PipelineModel", back_populates="executions")
    traces = relationship("TraceModel", back_populates="execution", cascade="all, delete-orphan")
    evidence = relationship("EvidenceModel", back_populates="execution", cascade="all, delete-orphan")
    failures = relationship("FailureModel", back_populates="execution", cascade="all, delete-orphan")
    incidents = relationship("IncidentModel", back_populates="execution", cascade="all, delete-orphan")


class TraceModel(Base):
    """
    SQLAlchemy ORM model for correlated Distributed Traces.
    Table: autopsy_traces
    """
    __tablename__ = "autopsy_traces"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    trace_id = Column(String(64), nullable=False, unique=True, index=True)
    execution_id = Column(String(36), ForeignKey("autopsy_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    root_span_id = Column(String(64), nullable=True)
    start_time = Column(DateTime(timezone=True), nullable=True, index=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)
    attributes = Column(JSON_TYPE, default=dict, nullable=False)

    execution = relationship("ExecutionModel", back_populates="traces")
    spans = relationship("SpanModel", back_populates="trace", cascade="all, delete-orphan")


class SpanModel(Base):
    """
    SQLAlchemy ORM model for individual operation Spans within a Trace.
    Table: autopsy_spans
    """
    __tablename__ = "autopsy_spans"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    span_id = Column(String(64), nullable=False, index=True)
    trace_id = Column(String(64), ForeignKey("autopsy_traces.trace_id", ondelete="CASCADE"), nullable=False, index=True)
    parent_span_id = Column(String(64), nullable=True, index=True)
    service_name = Column(String(255), nullable=False, index=True)
    operation_name = Column(String(255), nullable=False, index=True)
    kind = Column(String(50), default="INTERNAL", nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)
    status_code = Column(String(50), default="UNSET", nullable=False, index=True)
    status_message = Column(Text, nullable=True)
    attributes = Column(JSON_TYPE, default=dict, nullable=False)

    trace = relationship("TraceModel", back_populates="spans")
    events = relationship("EventModel", back_populates="span", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_autopsy_spans_trace_span", "trace_id", "span_id"),
    )


class EventModel(Base):
    """
    SQLAlchemy ORM model for timestamped Events occurring within a Span.
    Table: autopsy_events
    """
    __tablename__ = "autopsy_events"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    span_db_id = Column(String(36), ForeignKey("autopsy_spans.id", ondelete="CASCADE"), nullable=False, index=True)
    span_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    attributes = Column(JSON_TYPE, default=dict, nullable=False)

    span = relationship("SpanModel", back_populates="events")


class EvidenceModel(Base):
    """
    SQLAlchemy ORM model for Evidence records.
    Table: autopsy_evidence
    """
    __tablename__ = "autopsy_evidence"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    execution_id = Column(String(36), ForeignKey("autopsy_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    trace_id = Column(String(64), nullable=True, index=True)
    span_id = Column(String(64), nullable=True, index=True)
    evidence_type = Column(String(50), nullable=False, index=True)
    reference_uri = Column(Text, nullable=True)
    digest = Column(String(128), nullable=True)
    summary = Column(Text, nullable=False)
    metadata_json = Column(JSON_TYPE, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    execution = relationship("ExecutionModel", back_populates="evidence")


class FailureModel(Base):
    """
    SQLAlchemy ORM model for Failure diagnosis records.
    Table: autopsy_failures
    """
    __tablename__ = "autopsy_failures"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    execution_id = Column(String(36), ForeignKey("autopsy_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    trace_id = Column(String(64), nullable=True, index=True)
    span_id = Column(String(64), nullable=True, index=True)
    failure_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(50), default="HIGH", nullable=False, index=True)
    error_class = Column(String(255), nullable=True)
    description = Column(Text, nullable=False)
    evidence_ids = Column(JSON_TYPE, default=list, nullable=False)
    root_cause_hypothesis = Column(Text, nullable=True)
    attributes = Column(JSON_TYPE, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    execution = relationship("ExecutionModel", back_populates="failures")


class IncidentModel(Base):
    """
    SQLAlchemy ORM model for top-level Incident triage cases.
    Table: autopsy_incidents
    """
    __tablename__ = "autopsy_incidents"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    execution_id = Column(String(36), ForeignKey("autopsy_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    status = Column(String(50), default="OPEN", nullable=False, index=True)
    severity = Column(String(50), default="HIGH", nullable=False, index=True)
    summary = Column(Text, nullable=False)
    failure_ids = Column(JSON_TYPE, default=list, nullable=False)
    diagnosis_reference = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSON_TYPE, default=dict, nullable=False)

    execution = relationship("ExecutionModel", back_populates="incidents")

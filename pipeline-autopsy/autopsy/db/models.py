from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Text,
    Float,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
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

    id = Column(String(64), primary_key=True, default=_gen_uuid)
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


# Schema v2 records live beside the legacy tables until A2.6 removes the old API.
class SchemaMigrationModel(Base):
    __tablename__ = "schema_migrations"

    version = Column(String(32), primary_key=True)
    applied_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ProjectRecord(Base):
    __tablename__ = "projects"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class PipelineRecord(Base):
    __tablename__ = "pipelines"

    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    name = Column(String(64), primary_key=True)
    version = Column(String(64), primary_key=True)
    manifest = Column(JSON_TYPE, default=dict, nullable=False)
    evidence_level = Column(String(2), default="E1", nullable=False)
    evidence_kinds_allowed = Column(JSON_TYPE, default=list, nullable=False)
    retention_days = Column(Integer, default=14, nullable=False)
    registered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ExecutionRecord(Base):
    __tablename__ = "executions"

    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline = Column(String(64), nullable=False)
    version = Column(String(64), nullable=False)
    entity_id = Column(String(64), nullable=True, index=True)
    trace_ids = Column(JSON_TYPE, default=list, nullable=False)
    status = Column(String(24), default="receiving", nullable=False, index=True)
    verdict = Column(String(64), nullable=True)
    trace_grade = Column(String(1), nullable=True)
    run_outcome = Column(String(16), nullable=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    diagnosed_at = Column(DateTime(timezone=True), nullable=True)
    previous_execution_id = Column(String(64), ForeignKey("executions.id", ondelete="SET NULL"), nullable=True)


class SpanRecord(Base):
    __tablename__ = "spans"

    trace_id = Column(String(32), primary_key=True)
    span_id = Column(String(16), primary_key=True)
    execution_id = Column(String(64), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_span_id = Column(String(16), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    kind = Column(String(16), default="INTERNAL", nullable=False)
    role = Column(String(16), default="other", nullable=False, index=True)
    stage_name = Column(String(128), nullable=True, index=True)
    item_id = Column(String(128), nullable=True, index=True)
    attempt = Column(Integer, nullable=True)
    status = Column(String(8), default="UNSET", nullable=False, index=True)
    status_message = Column(Text, nullable=True)
    error_type = Column(String(255), nullable=True, index=True)
    error_class = Column(String(32), nullable=True, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    attrs = Column(JSON_TYPE, default=dict, nullable=False)
    events = Column(JSON_TYPE, default=list, nullable=False)
    links = Column(JSON_TYPE, default=list, nullable=False)
    resource = Column(JSON_TYPE, default=dict, nullable=False)
    dropped_attributes = Column(Integer, default=0, nullable=False)
    dropped_events = Column(Integer, default=0, nullable=False)


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    id = Column(String(64), primary_key=True)
    execution_id = Column(String(64), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(String(128), nullable=True)
    item_id = Column(String(128), nullable=True)
    kind = Column(String(64), nullable=False)
    content_type = Column(String(128), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False)
    blob_path = Column(Text, nullable=False)
    redacted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)


class DiagnosisJobRecord(Base):
    __tablename__ = "diagnosis_jobs"

    execution_id = Column(String(64), ForeignKey("executions.id", ondelete="CASCADE"), primary_key=True)
    status = Column(String(16), default="pending", nullable=False, index=True)
    reason = Column(String(16), nullable=True)
    run_after = Column(DateTime(timezone=True), nullable=True, index=True)
    attempt = Column(Integer, default=0, nullable=False)
    error = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class ObservationRecord(Base):
    __tablename__ = "observations"

    execution_id = Column(String(64), ForeignKey("executions.id", ondelete="CASCADE"), primary_key=True)
    id = Column(String(64), primary_key=True)
    family = Column(String(32), nullable=False)
    code = Column(String(128), nullable=False)
    result = Column(String(16), nullable=False)
    stage = Column(String(128), nullable=True)
    span_id = Column(String(16), nullable=True)
    artifact_id = Column(String(64), nullable=True)
    field = Column(String(128), nullable=True)
    reported_by = Column(String(128), nullable=True)
    error_class = Column(String(32), nullable=True)
    source_artifact_id = Column(String(64), nullable=True)
    detail = Column(Text, nullable=False)


class FindingRecord(Base):
    __tablename__ = "findings"

    id = Column(String(64), primary_key=True)
    execution_id = Column(String(64), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(String(128), nullable=True)
    item_id = Column(String(128), nullable=True)
    role = Column(String(16), nullable=False)
    classification = Column(String(64), nullable=True)
    confidence = Column(String(16), nullable=True)
    severity = Column(String(16), nullable=True)
    link = Column(String(16), nullable=True)
    caused_by = Column(JSON_TYPE, default=list, nullable=False)
    evidence = Column(JSON_TYPE, default=list, nullable=False)
    note = Column(Text, nullable=True)
    signature = Column(String(64), nullable=True, index=True)


class ExplanationRecord(Base):
    __tablename__ = "explanations"

    execution_id = Column(String(64), ForeignKey("executions.id", ondelete="CASCADE"), primary_key=True)
    source = Column(String(16), nullable=False)
    summary = Column(Text, nullable=False)
    narrative = Column(JSON_TYPE, default=list, nullable=False)
    remediation = Column(JSON_TYPE, default=list, nullable=False)
    guardrail_log = Column(JSON_TYPE, default=list, nullable=False)
    model = Column(String(128), nullable=True)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)

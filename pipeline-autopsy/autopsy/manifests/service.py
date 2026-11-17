"""Persistence helpers for validated pipeline manifests."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from autopsy.db.models import PipelineRecord, ProjectRecord


def register_manifest(db: Session, project_id: str, manifest: dict):
    """Create a pipeline version, or return the existing identical version."""
    name = manifest["pipeline"]
    version = manifest["version"]
    existing = db.get(PipelineRecord, (project_id, name, version))
    if existing is not None:
        if existing.manifest != manifest:
            return existing, False
        return existing, True

    if db.get(ProjectRecord, project_id) is None:
        db.add(ProjectRecord(id=project_id, name=project_id, created_at=datetime.now(timezone.utc)))
        db.flush()

    evidence = manifest.get("evidence") or {}
    record = PipelineRecord(
        project_id=project_id,
        name=name,
        version=version,
        manifest=manifest,
        evidence_level=evidence.get("level", "E1"),
        evidence_kinds_allowed=evidence.get("kinds_allowed", []),
        retention_days=evidence.get("retention_days", 14),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, True


def list_manifests(db: Session, project_id: str):
    return (
        db.query(PipelineRecord)
        .filter(PipelineRecord.project_id == project_id)
        .order_by(PipelineRecord.name, PipelineRecord.version)
        .all()
    )

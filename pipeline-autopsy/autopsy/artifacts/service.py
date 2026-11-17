"""Validate and persist evidence artifacts in the configured local blob store."""
import base64
import binascii
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from sqlalchemy.orm import Session

from autopsy.core.contract import artifact_id
from autopsy.db.models import ArtifactRecord, ExecutionRecord, PipelineRecord


MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
_ARTIFACT_ID = re.compile(r"^art_[0-9a-f]{16}$")
_EXECUTION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class ArtifactError(Exception):
    def __init__(self, status_code, message):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def decode_payload(payload):
    if not isinstance(payload, dict):
        raise ArtifactError(422, "Artifact request must be an object")
    if "content_b64" in payload:
        if "content" in payload:
            raise ArtifactError(422, "Provide content or content_b64, not both")
        try:
            content = base64.b64decode(payload["content_b64"], validate=True)
        except (binascii.Error, ValueError, TypeError):
            raise ArtifactError(422, "content_b64 must be valid base64") from None
    elif "content" in payload:
        value = payload["content"]
        if isinstance(value, bytes):
            content = value
        elif isinstance(value, str):
            content = value.encode("utf-8")
        else:
            content = json.dumps(value, sort_keys=True, ensure_ascii=False,
                                 separators=(",", ":")).encode("utf-8")
    else:
        raise ArtifactError(422, "Artifact content is required")
    if len(content) > MAX_ARTIFACT_BYTES:
        raise ArtifactError(413, "Artifact content exceeds the 5 MiB limit")
    return content


def _blob_root():
    return Path(os.getenv("AUTOPSY_BLOB_DIR", "./blobs")).expanduser()


def store_artifact(db: Session, project_id: str, payload: dict, content: bytes):
    artifact = payload.get("id")
    if not isinstance(artifact, str) or not _ARTIFACT_ID.fullmatch(artifact):
        raise ArtifactError(422, "Artifact id must match art_ followed by 16 lowercase hex characters")
    execution_id = payload.get("execution_id")
    if not isinstance(execution_id, str) or not _EXECUTION_ID.fullmatch(execution_id) or execution_id in {".", ".."}:
        raise ArtifactError(422, "Invalid execution_id")

    kind = payload.get("kind")
    content_type = payload.get("content_type")
    item_id = payload.get("item_id")
    if item_id is None:
        item_id = ""
    redacted = payload.get("redacted")
    if not isinstance(kind, str) or not kind or not isinstance(content_type, str) or not content_type:
        raise ArtifactError(422, "kind and content_type are required strings")
    if not isinstance(redacted, bool):
        raise ArtifactError(422, "redacted must be a boolean")
    if not isinstance(item_id, str):
        raise ArtifactError(422, "item_id must be a string")

    execution = db.get(ExecutionRecord, execution_id)
    if execution is None or execution.project_id != project_id:
        raise ArtifactError(404, "Execution not found")
    if (payload.get("pipeline"), payload.get("version")) != (execution.pipeline, execution.version):
        raise ArtifactError(404, "Pipeline version does not match the execution")

    pipeline = db.get(PipelineRecord, (project_id, execution.pipeline, execution.version))
    if pipeline is None:
        raise ArtifactError(403, "Pipeline manifest is not registered")
    if pipeline.evidence_level != "E2" or payload.get("kind") not in (pipeline.evidence_kinds_allowed or []):
        raise ArtifactError(403, "Artifact kind is not allowed at this evidence level")

    if not redacted and artifact_id(content, kind, execution_id, item_id) != artifact:
        raise ArtifactError(422, "Artifact id does not match the supplied content")

    existing = db.get(ArtifactRecord, artifact)
    if existing is not None:
        return existing, False

    root = _blob_root()
    # URL-encode the component so fallback IDs such as ``trace:<id>`` are safe
    # directory names on Windows while remaining deterministic.
    directory = root / quote(execution_id, safe="-._~")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / artifact
    try:
        with destination.open("xb") as blob:
            blob.write(content)
    except FileExistsError:
        raise ArtifactError(409, "Artifact blob already exists without metadata") from None

    evidence = pipeline.manifest.get("evidence", {}) if isinstance(pipeline.manifest, dict) else {}
    retention_days = evidence.get("retention_days", pipeline.retention_days or 14)
    now = datetime.now(timezone.utc)
    record = ArtifactRecord(
        id=artifact,
        execution_id=execution_id,
        stage=payload.get("stage"),
        item_id=payload.get("item_id"),
        kind=kind,
        content_type=content_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        blob_path=str(destination),
        redacted=redacted,
        created_at=now,
        expires_at=now + timedelta(days=retention_days),
    )
    try:
        db.add(record)
        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise
    return record, True


def get_artifact(db: Session, project_id: str, artifact_id_value: str):
    record = (
        db.query(ArtifactRecord)
        .join(ExecutionRecord, ExecutionRecord.id == ArtifactRecord.execution_id)
        .filter(ArtifactRecord.id == artifact_id_value, ExecutionRecord.project_id == project_id)
        .one_or_none()
    )
    if record is None:
        raise ArtifactError(404, "Artifact not found")
    try:
        content = Path(record.blob_path).read_bytes()
    except OSError:
        raise ArtifactError(404, "Artifact content is unavailable") from None
    return record, content

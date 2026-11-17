"""Translate persisted records into inputs for the pure diagnosis core."""
import json
from pathlib import Path

from autopsy.core.normalize import normalize
from autopsy.db.models import ArtifactRecord, ExecutionRecord, PipelineRecord, SpanRecord


def _content(record):
    raw = Path(record.blob_path).read_bytes()
    media_type = record.content_type.split(";", 1)[0].lower()
    if media_type == "application/json" or media_type.endswith("+json"):
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return raw
    if media_type.startswith("text/") or media_type in {
        "application/yaml", "application/x-yaml", "application/xml"
    }:
        return raw.decode("utf-8", errors="replace")
    return raw


def build_core_inputs(db, execution: ExecutionRecord, pipeline: PipelineRecord):
    span_records = (
        db.query(SpanRecord)
        .filter(SpanRecord.execution_id == execution.id)
        .order_by(SpanRecord.start_time, SpanRecord.span_id)
        .all()
    )
    spans = []
    for record in span_records:
        spans.append({
            "trace_id": record.trace_id,
            "span_id": record.span_id,
            "parent": record.parent_span_id,
            "name": record.name,
            "kind": record.kind,
            "start": record.start_time,
            "end": record.end_time,
            "status": record.status,
            "status_message": record.status_message,
            "error_type": record.error_type,
            "error_class": record.error_class,
            "attrs": record.attrs or {},
            "resource": record.resource or {},
            "events": [
                {"name": event.get("name"), "attrs": event.get("attrs", event.get("attributes", {})),
                 "timestamp": event.get("timestamp")}
                for event in (record.events or [])
            ],
        })
    spans = normalize(spans)

    artifact_records = db.query(ArtifactRecord).filter_by(execution_id=execution.id).all()
    artifacts = {}
    for record in artifact_records:
        try:
            artifacts[record.id] = {"kind": record.kind, "content": _content(record),
                                    "redacted": record.redacted, "content_type": record.content_type}
        except OSError:
            # Missing blobs remain absent so the core can report artifact_not_found.
            continue

    items = {}
    root = next((span for span in spans if span["attrs"].get("autopsy.role") == "execution"), None)
    encoded_items = root["attrs"].get("pipeline.run.items", []) if root else []
    if isinstance(encoded_items, dict):
        items = {str(item): str(role) for item, role in encoded_items.items()}
    elif isinstance(encoded_items, list):
        for encoded in encoded_items:
            if isinstance(encoded, str) and ":" in encoded:
                item_id, role = encoded.rsplit(":", 1)
                if item_id and role:
                    items[item_id] = role
    if not items:
        for span in spans:
            attrs = span["attrs"]
            item_id = attrs.get("pipeline.stage.item_id") or attrs.get("item.id")
            role = attrs.get("pipeline.stage.item_role") or attrs.get("item.role")
            if item_id is not None and role is not None:
                items[str(item_id)] = str(role)

    return spans, artifacts, pipeline.manifest or {}, items


def missing_referenced_artifacts(spans, artifacts):
    referenced = set()
    for span in spans:
        attrs = span.get("attrs", {})
        for key in ("input.artifact_ids", "output.artifact_ids"):
            values = attrs.get(key) or []
            if isinstance(values, (list, tuple, set)):
                referenced.update(value for value in values if isinstance(value, str))
    return referenced - set(artifacts)

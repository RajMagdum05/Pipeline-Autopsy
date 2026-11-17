"""Schema-v2 execution, diagnosis, graph, and health APIs."""
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from autopsy.api.auth import extract_project_id, verify_api_key
from autopsy.core.normalize import normalize
from autopsy.db.database import get_db
from autopsy.db.models import (
    ArtifactRecord, DiagnosisJobRecord, ExecutionRecord, ExplanationRecord,
    FindingRecord, ObservationRecord, PipelineRecord, SpanRecord,
)


router = APIRouter(dependencies=[Depends(verify_api_key)])
health_router = APIRouter()


def _project_id(request):
    return extract_project_id(request) or "default"


def _execution(db, request, execution_id):
    record = db.query(ExecutionRecord).filter_by(id=execution_id, project_id=_project_id(request)).one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return record


def _cursor_encode(execution):
    raw = f"{execution.started_at.isoformat()}\n{execution.id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_decode(cursor):
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        timestamp, execution_id = base64.urlsafe_b64decode(padded).decode("utf-8").split("\n", 1)
        return datetime.fromisoformat(timestamp), execution_id
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid execution cursor") from None


def _list_row(db, execution):
    origins = db.query(FindingRecord).filter_by(execution_id=execution.id, role="origin").all()
    duration_ms = None
    if execution.started_at and execution.ended_at:
        duration_ms = max(0, int((execution.ended_at - execution.started_at).total_seconds() * 1000))
    return {
        "id": execution.id,
        "entity_id": execution.entity_id,
        "pipeline": execution.pipeline,
        "version": execution.version,
        "started_at": execution.started_at,
        "verdict": execution.verdict,
        "grade": execution.trace_grade,
        "run_outcome": execution.run_outcome,
        "duration_ms": duration_ms,
        "origin_stages": [f"{row.stage}@{row.item_id}" if row.item_id else row.stage for row in origins],
    }


@router.get("/v1/executions", tags=["Executions"])
def list_executions(
    request: Request,
    pipeline: str | None = None,
    verdict: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(ExecutionRecord).filter(ExecutionRecord.project_id == _project_id(request))
    if pipeline:
        query = query.filter(ExecutionRecord.pipeline == pipeline)
    if verdict:
        query = query.filter(ExecutionRecord.verdict == verdict)
    if entity_id:
        query = query.filter(ExecutionRecord.entity_id == entity_id)
    if cursor:
        timestamp, execution_id = _cursor_decode(cursor)
        query = query.filter(or_(ExecutionRecord.started_at < timestamp,
                                 (ExecutionRecord.started_at == timestamp) & (ExecutionRecord.id < execution_id)))
    rows = query.order_by(ExecutionRecord.started_at.desc(), ExecutionRecord.id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    next_cursor = _cursor_encode(page[-1]) if len(rows) > limit else None
    return {"executions": [_list_row(db, row) for row in page], "next_cursor": next_cursor}


@router.get("/v1/executions/{execution_id}", tags=["Executions"])
def get_execution(execution_id: str, request: Request, db: Session = Depends(get_db)):
    execution = _execution(db, request, execution_id)
    jaeger_base = os.getenv("JAEGER_BASE_URL", "").rstrip("/")
    return {
        "id": execution.id,
        "execution_id": execution.id,
        "project_id": execution.project_id,
        "pipeline": execution.pipeline,
        "version": execution.version,
        "entity_id": execution.entity_id,
        "status": execution.status,
        "started_at": execution.started_at,
        "ended_at": execution.ended_at,
        "timings": {"started_at": execution.started_at, "ended_at": execution.ended_at},
        "trace_grade": execution.trace_grade,
        "verdict": execution.verdict,
        "trace_ids": execution.trace_ids or [],
        "jaeger_url": f"{jaeger_base}/trace/{execution.trace_ids[0]}" if jaeger_base and execution.trace_ids else None,
    }


def _items_from_root(root):
    value = (root.attrs or {}).get("pipeline.run.items", []) if root else []
    if isinstance(value, dict):
        return {str(key): str(role) for key, role in value.items()}
    items = {}
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str) and ":" in entry:
                item, role = entry.rsplit(":", 1)
                if item and role:
                    items[item] = role
    return items


def _node_id(stage, item_id=None):
    return f"{stage}@{item_id}" if item_id else stage


@router.get("/v1/executions/{execution_id}/graph", tags=["Executions"])
def get_execution_graph(execution_id: str, request: Request, db: Session = Depends(get_db)):
    execution = _execution(db, request, execution_id)
    pipeline = db.get(PipelineRecord, (execution.project_id, execution.pipeline, execution.version))
    manifest = pipeline.manifest if pipeline and isinstance(pipeline.manifest, dict) else {"stages": []}
    records = db.query(SpanRecord).filter_by(execution_id=execution.id).order_by(SpanRecord.start_time).all()
    findings = db.query(FindingRecord).filter_by(execution_id=execution.id).all()
    role_by_node = {_node_id(row.stage, row.item_id): row.role for row in findings}
    root = next((row for row in records if row.role == "execution"), None)
    items = _items_from_root(root)

    grouped = {}
    for record in records:
        if record.role != "stage" or not record.stage_name:
            continue
        attrs = record.attrs or {}
        stage = attrs.get("pipeline.stage.name") or record.stage_name
        item_id = attrs.get("pipeline.stage.item_id") or record.item_id
        key = _node_id(stage, item_id)
        grouped.setdefault(key, []).append((record, attrs, item_id))

    nodes = []
    node_lookup = {}
    for stage_def in manifest.get("stages", []):
        stage_name = stage_def.get("name")
        stage_items = [
            item for item, role in items.items()
            if stage_def.get("scope") == "item"
            and (not stage_def.get("item_roles") or role in stage_def["item_roles"])
        ]
        keys = ([_node_id(stage_name, item) for item in stage_items]
                if stage_def.get("scope") == "item" else [_node_id(stage_name)])
        for key in keys:
            executions = grouped.get(key, [])
            final = executions[-1] if executions else (None, {}, None)
            record, attrs, item_id = final
            if item_id is None and stage_def.get("scope") == "item":
                item_id = key.split("@", 1)[1]
            role = role_by_node.get(key, "healthy" if record and attrs.get("pipeline.stage.status") == "success"
                                    else ("missing" if not record else "healthy"))
            node = {
                "id": key,
                "stage": stage_name,
                "item_id": item_id,
                "item_role": items.get(item_id) if item_id else None,
                "role": role,
                "status": attrs.get("pipeline.stage.status") if record else "not_executed",
                "attempts": len(executions),
            }
            nodes.append(node)
            node_lookup[key] = {"node": node, "attrs": attrs, "scope": stage_def.get("scope")}

    edges = []
    stage_by_name = {stage.get("name"): stage for stage in manifest.get("stages", [])}
    artifact_records = {record.id: record for record in db.query(ArtifactRecord).filter_by(execution_id=execution.id).all()}
    for consumer in manifest.get("stages", []):
        for kind in consumer.get("consumes", []):
            producer = next((stage for stage in manifest.get("stages", []) if kind in stage.get("produces", [])), None)
            if producer is None:
                continue
            source_nodes = [value for key, value in node_lookup.items() if value["node"]["stage"] == producer["name"]]
            target_nodes = [value for key, value in node_lookup.items() if value["node"]["stage"] == consumer["name"]]
            for source in source_nodes:
                for target in target_nodes:
                    source_item, target_item = source["node"]["item_id"], target["node"]["item_id"]
                    if source_item and target_item and source_item != target_item:
                        continue
                    output_ids = set(source["attrs"].get("pipeline.artifact.output_ids", []))
                    input_ids = set(target["attrs"].get("pipeline.artifact.input_ids", []))
                    linked_ids = sorted(aid for aid in output_ids & input_ids
                                        if aid in artifact_records and artifact_records[aid].kind == kind)
                    edges.append({
                        "from": source["node"]["id"], "to": target["node"]["id"], "kind": kind,
                        "artifact_ids": linked_ids, "type": "data",
                        "tainted": source["node"]["role"] in {"origin", "propagated", "tainted"},
                    })

        for requirement in consumer.get("requires", []):
            required_stage = requirement.get("stage")
            required_role = requirement.get("item_role")
            source_nodes = [value for value in node_lookup.values()
                            if value["node"]["stage"] == required_stage
                            and value["node"].get("item_role") == required_role]
            target_nodes = [value for value in node_lookup.values()
                            if value["node"]["stage"] == consumer.get("name")
                            and value["node"].get("item_role") != required_role]
            for source in source_nodes:
                for target in target_nodes:
                    if source["node"].get("item_id") == target["node"].get("item_id"):
                        continue
                    edges.append({"from": source["node"]["id"], "to": target["node"]["id"],
                                  "kind": f"gate:{required_stage}", "artifact_ids": [], "type": "control",
                                  "tainted": source["node"]["role"] in {"origin", "propagated", "not_executed"}})

    return {"nodes": nodes, "edges": edges}


@router.get("/v1/executions/{execution_id}/diagnosis", tags=["Executions"])
def get_execution_diagnosis(execution_id: str, request: Request, db: Session = Depends(get_db)):
    execution = _execution(db, request, execution_id)
    if execution.status != "diagnosed":
        return JSONResponse(status_code=409, content={"status": execution.status})
    findings = db.query(FindingRecord).filter_by(execution_id=execution.id).all()
    observations = db.query(ObservationRecord).filter_by(execution_id=execution.id).all()
    explanation = db.get(ExplanationRecord, execution.id)
    return {
        "execution_id": execution.id,
        "pipeline": execution.pipeline,
        "version": execution.version,
        "entity_id": execution.entity_id,
        "verdict": execution.verdict,
        "trace_grade": execution.trace_grade,
        "findings": [{
            "id": row.id, "stage": row.stage, "item_id": row.item_id, "role": row.role,
            "classification": row.classification, "confidence": row.confidence, "severity": row.severity,
            "link": row.link, "caused_by": row.caused_by or [], "evidence": row.evidence or [],
            "note": row.note, "seen_before": 0,
        } for row in findings],
        "observations": [{
            "id": row.id, "family": row.family, "code": row.code, "result": row.result,
            "stage": row.stage, "span_id": row.span_id, "artifact_id": row.artifact_id,
            "field": row.field, "detail": row.detail,
        } for row in observations],
        "explanation": ({"source": explanation.source, "summary": explanation.summary,
                         "narrative": explanation.narrative or [], "remediation": explanation.remediation or []}
                        if explanation else None),
    }


@router.get("/v1/executions/{execution_id}/spans", tags=["Executions"])
def get_execution_spans(execution_id: str, request: Request, db: Session = Depends(get_db)):
    _execution(db, request, execution_id)
    rows = db.query(SpanRecord).filter_by(execution_id=execution_id).order_by(SpanRecord.start_time).all()
    spans = normalize([{
        "trace_id": row.trace_id, "span_id": row.span_id, "parent": row.parent_span_id,
        "name": row.name, "kind": row.kind, "start": row.start_time, "end": row.end_time,
        "status": row.status, "status_message": row.status_message, "attrs": row.attrs or {},
        "resource": row.resource or {}, "events": row.events or [], "links": row.links or [],
    } for row in rows])
    return {"spans": spans}


@router.post("/v1/executions/{execution_id}/diagnose", status_code=status.HTTP_202_ACCEPTED, tags=["Executions"])
def queue_diagnosis(execution_id: str, request: Request, db: Session = Depends(get_db)):
    execution = _execution(db, request, execution_id)
    pipeline = db.get(PipelineRecord, (execution.project_id, execution.pipeline, execution.version))
    if pipeline is None or not pipeline.manifest or not pipeline.manifest.get("stages"):
        return JSONResponse(status_code=409, content={"status": "unregistered"})
    now = datetime.now(timezone.utc)
    job = db.get(DiagnosisJobRecord, execution.id)
    if job is None:
        job = DiagnosisJobRecord(execution_id=execution.id, status="pending")
        db.add(job)
    job.status = "pending"
    job.reason = "manual"
    job.run_after = now
    job.attempt = 0
    job.error = None
    job.updated_at = now
    execution.status = "queued"
    db.commit()
    return {"execution_id": execution.id, "status": "queued"}


@router.delete("/v1/executions/{execution_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Executions"])
def delete_execution(execution_id: str, request: Request, db: Session = Depends(get_db)):
    execution = _execution(db, request, execution_id)
    records = db.query(ArtifactRecord).filter_by(execution_id=execution.id).all()
    blob_paths = [Path(record.blob_path) for record in records]
    db.query(SpanRecord).filter_by(execution_id=execution.id).delete(synchronize_session=False)
    db.query(ArtifactRecord).filter_by(execution_id=execution.id).delete(synchronize_session=False)
    db.query(DiagnosisJobRecord).filter_by(execution_id=execution.id).delete(synchronize_session=False)
    db.query(ObservationRecord).filter_by(execution_id=execution.id).delete(synchronize_session=False)
    db.query(FindingRecord).filter_by(execution_id=execution.id).delete(synchronize_session=False)
    db.query(ExplanationRecord).filter_by(execution_id=execution.id).delete(synchronize_session=False)
    db.delete(execution)
    db.commit()
    root = Path(os.getenv("AUTOPSY_BLOB_DIR", "./blobs")).expanduser().resolve()
    for path in blob_paths:
        try:
            resolved = path.resolve()
            if resolved.is_relative_to(root):
                resolved.unlink(missing_ok=True)
                resolved.parent.rmdir()
        except (OSError, RuntimeError):
            pass
    return None


@health_router.get("/health", tags=["Health"])
def health_check(request: Request, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        database_status = "ok"
        queue_depth = db.query(DiagnosisJobRecord).filter(DiagnosisJobRecord.status == "pending").count()
    except Exception:
        db.rollback()
        database_status = "unavailable"
        queue_depth = 0
    worker = getattr(request.app.state, "worker_task", None)
    return {"db": database_status, "worker": "alive" if worker and not worker.done() else "stopped",
            "queue_depth": queue_depth}

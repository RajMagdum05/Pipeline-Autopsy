"""Evidence artifact upload and retrieval endpoints."""
import base64
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from autopsy.api.auth import extract_project_id, verify_api_key
from autopsy.artifacts.privacy import mask_json, mask_text
from autopsy.artifacts.service import ArtifactError, decode_payload, get_artifact, store_artifact
from autopsy.db.database import get_db
from autopsy.recording import record_artifact


router = APIRouter(dependencies=[Depends(verify_api_key)])
_MAX_REQUEST_BYTES = 8 * 1024 * 1024
_ARTIFACT_ID = re.compile(r"^art_[0-9a-f]{16}$")


async def _read_body(request):
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_REQUEST_BYTES:
            raise HTTPException(status_code=413, detail="Artifact request exceeds the request size limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _artifact_response(record, content):
    response = {
        "id": record.id,
        "execution_id": record.execution_id,
        "stage": record.stage,
        "item_id": record.item_id,
        "kind": record.kind,
        "content_type": record.content_type,
        "size_bytes": record.size_bytes,
        "sha256": record.sha256,
        "redacted": record.redacted,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
    }
    media_type = record.content_type.split(";", 1)[0].lower()
    if media_type == "application/json" or media_type.endswith("+json"):
        try:
            parsed = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            response["content_b64"] = base64.b64encode(content).decode("ascii")
        else:
            response["content"] = mask_json(parsed)
    elif media_type.startswith("text/") or media_type in {"application/xml", "application/yaml", "application/x-yaml"}:
        response["content"] = mask_text(content.decode("utf-8", errors="replace"))
    else:
        if record.redacted:
            response["content_b64"] = base64.b64encode(content).decode("ascii")
        else:
            # There is no safe generic masker for binary formats (PDF/images).
            response["content_masked"] = True
    return response


@router.post("/v1/artifacts", tags=["Artifacts"])
async def post_artifact(request: Request, db: Session = Depends(get_db)):
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
        raise HTTPException(status_code=415, detail="Content-Type must be application/json")
    body = await _read_body(request)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Malformed artifact JSON") from None
    try:
        content = decode_payload(payload)
    except ArtifactError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    project_id = extract_project_id(request) or "default"
    try:
        record, created = store_artifact(db, project_id, payload, content)
    except ArtifactError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    if created:
        record_artifact(payload)
    result = _artifact_response(record, content) if created else {
        "id": record.id, "execution_id": record.execution_id, "kind": record.kind,
        "size_bytes": record.size_bytes, "sha256": record.sha256, "duplicate": True,
    }
    return JSONResponse(status_code=201 if created else 200, content=result)


@router.get("/v1/artifacts/{artifact_id_value}", tags=["Artifacts"])
async def get_artifact_route(
    artifact_id_value: str,
    request: Request,
    db: Session = Depends(get_db),
):
    if not _ARTIFACT_ID.fullmatch(artifact_id_value):
        raise HTTPException(status_code=422, detail="Invalid artifact id format")
    project_id = extract_project_id(request) or "default"
    try:
        record, content = get_artifact(db, project_id, artifact_id_value)
    except ArtifactError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    return _artifact_response(record, content)

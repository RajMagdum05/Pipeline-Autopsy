"""Pipeline manifest registration and listing endpoints."""
import json

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from autopsy.api.auth import extract_project_id, verify_api_key
from autopsy.core.manifest import validate_manifest
from autopsy.db.database import get_db
from autopsy.db.models import PipelineRecord
from autopsy.manifests.service import list_manifests, register_manifest


router = APIRouter(dependencies=[Depends(verify_api_key)])


def _parse_manifest(body: bytes, content_type: str):
    media_type = content_type.split(";", 1)[0].strip().lower()
    try:
        if media_type == "application/json" or media_type.endswith("+json"):
            value = json.loads(body.decode("utf-8"))
        elif media_type in {"application/yaml", "text/yaml", "application/x-yaml", "text/plain", ""}:
            value = yaml.safe_load(body.decode("utf-8"))
        else:
            raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                                detail="Manifest must be YAML or JSON")
    except (UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return None, [f"manifest could not be parsed: {type(exc).__name__}"]
    if not isinstance(value, dict):
        return None, ["manifest must be an object"]
    return value, []


@router.put("/v1/pipelines/{name}/versions/{version}", tags=["Pipelines"])
async def put_pipeline_manifest(
    name: str,
    version: str,
    request: Request,
    db: Session = Depends(get_db),
):
    manifest, parse_problems = _parse_manifest(await request.body(), request.headers.get("content-type", ""))
    if parse_problems:
        return JSONResponse(status_code=422, content={"problems": parse_problems})

    problems = validate_manifest(manifest)
    if manifest.get("pipeline") != name:
        problems.append(f"pipeline must match URL name {name!r}")
    if manifest.get("version") != version:
        problems.append(f"version must match URL version {version!r}")
    if problems:
        return JSONResponse(status_code=422, content={"problems": problems})

    project_id = extract_project_id(request) or "default"
    try:
        record, accepted = register_manifest(db, project_id, manifest)
    except IntegrityError:
        db.rollback()
        record = db.get(PipelineRecord, (project_id, name, version))
        accepted = record is not None and record.manifest == manifest
    if not accepted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This pipeline version is already registered with different content")
    return {"pipeline": record.name, "version": record.version,
            "project_id": record.project_id, "registered_at": record.registered_at}


@router.get("/v1/pipelines", tags=["Pipelines"])
async def get_pipelines(request: Request, db: Session = Depends(get_db)):
    project_id = extract_project_id(request) or "default"
    return {"pipelines": [
        {"pipeline": record.name, "version": record.version, "project_id": record.project_id,
         "manifest": record.manifest, "registered_at": record.registered_at}
        for record in list_manifests(db, project_id)
    ]}

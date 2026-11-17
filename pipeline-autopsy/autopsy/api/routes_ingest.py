import gzip
import io
import json
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from autopsy.api.auth import extract_project_id, verify_api_key
from autopsy.db.database import get_db
from autopsy.recording import record_ingest
from autopsy.services.ingestion_service import TelemetryIngestionService

router = APIRouter(dependencies=[Depends(verify_api_key)])
ingestion_service = TelemetryIngestionService()
async def _read_bounded_body(request: Request, max_bytes: int) -> bytes:
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                                detail="OTLP request body exceeds AUTOPSY_MAX_BODY_BYTES")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_otlp_request(body: bytes, media_type: str) -> Dict[str, Any]:
    if media_type == "application/json":
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed OTLP JSON payload")
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTLP JSON payload must be an object")
        return parsed
    try:
        from google.protobuf.json_format import MessageToDict
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

        request_message = ExportTraceServiceRequest()
        request_message.ParseFromString(body)
        return MessageToDict(request_message, preserving_proto_field_name=False)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed OTLP protobuf payload")


def _otlp_response(rejected_spans: int, media_type: str):
    from google.protobuf.json_format import MessageToDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse

    response_message = ExportTraceServiceResponse()
    if rejected_spans:
        response_message.partial_success.rejected_spans = rejected_spans
        response_message.partial_success.error_message = "One or more spans were rejected due to invalid identifiers"
    if media_type == "application/x-protobuf":
        return Response(content=response_message.SerializeToString(), media_type=media_type)
    return JSONResponse(content=MessageToDict(response_message, preserving_proto_field_name=False))


@router.post("/v1/traces", status_code=status.HTTP_200_OK, tags=["Telemetry Ingestion"])
async def ingest_otlp_traces(
    request: Request,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Standard OTLP/HTTP Trace Ingestion Endpoint.
    Receives OpenTelemetry ExportTraceServiceRequest (binary Protobuf or JSON),
    validates, normalizes, and persists traces, spans, and events into PostgreSQL.
    """
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"application/json", "application/x-protobuf"}:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="Content-Type must be application/json or application/x-protobuf")
    content_encoding = request.headers.get("content-encoding", "identity").strip().lower()
    if content_encoding not in {"identity", "gzip"}:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            detail="Content-Encoding must be identity or gzip")
    try:
        max_body_bytes = int(os.getenv("AUTOPSY_MAX_BODY_BYTES", str(10 * 1024 * 1024)))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="AUTOPSY_MAX_BODY_BYTES must be an integer")
    body_bytes = await _read_bounded_body(request, max_body_bytes)
    if not body_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty OTLP trace payload received.",
        )

    if content_encoding == "gzip":
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(body_bytes), mode="rb") as compressed:
                body_bytes = compressed.read(max_body_bytes + 1)
        except (OSError, EOFError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed gzip OTLP payload")
        if len(body_bytes) > max_body_bytes:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                                detail="Decompressed OTLP request exceeds AUTOPSY_MAX_BODY_BYTES")

    body_dict = _decode_otlp_request(body_bytes, media_type)

    auth_project_id = getattr(request.state, "project_id", None) if hasattr(request, "state") else None
    header_project_id = auth_project_id or extract_project_id(request)
    if header_project_id and body_dict:
        res_spans = body_dict.get("resourceSpans") or body_dict.get("resource_spans") or []
        for rs in res_spans:
            res_obj = rs.setdefault("resource", {})
            attrs = res_obj.setdefault("attributes", [])
            # Check if project.id or project_id already in attributes
            has_proj = False
            if isinstance(attrs, list):
                for a in attrs:
                    if isinstance(a, dict) and a.get("key") in ("project.id", "project_id", "autopsy.project_id"):
                        has_proj = True
                        if auth_project_id:
                            # Force override with authenticated project_id
                            a["value"] = {"stringValue": auth_project_id}
                        break
                if not has_proj:
                    attrs.append({"key": "project.id", "value": {"stringValue": header_project_id}})
            elif isinstance(attrs, dict):
                if auth_project_id:
                    attrs["project.id"] = auth_project_id
                elif not any(k in attrs for k in ("project.id", "project_id", "autopsy.project_id")):
                    attrs["project.id"] = header_project_id

    try:
        result = ingestion_service.ingest_otlp_payload(body_dict, db)
        record_ingest(db, body_dict, result.get("trace_ids", []))
        return _otlp_response(result.get("rejected_spans", 0), media_type)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Telemetry ingestion is temporarily unavailable",
                            headers={"Retry-After": "1"})



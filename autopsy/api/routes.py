from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from typing import Any, Dict, List, Optional

from autopsy.db.database import get_db
from autopsy.db.models import ExecutionModel, TraceModel, FailureModel, IncidentModel
from autopsy.services.ingestion_service import TelemetryIngestionService
from autopsy.services.reconstruction_service import PipelineReconstructionEngine
from autopsy.services.failure_detection_service import FailureDetectionService
from autopsy.services.root_cause_service import RootCauseAnalysisEngine
from autopsy.services.diagnosis_service import DiagnosisService
from autopsy.services.agent_service import AutopsyInvestigationAgent, AutopsyInvestigationTools

from autopsy.services.credential_service import CredentialService

from autopsy.api.auth import verify_api_key, extract_project_id
from autopsy.api.schemas import (
    ExecutionResponse,
    ExecutionGraphResponse,
    FailureListResponse,
    FailureItemResponse,
    RootCausesResponse,
    RootCauseCandidateResponse,
    DiagnosisResponse,
    AutopsyReportResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ApiKeyCreateRequest,
    ApiKeyCreatedResponse,
    ApiKeyItemResponse,
    ApiKeyRevokeResponse,
)

router = APIRouter()
ingestion_service = TelemetryIngestionService()
reconstruction_engine = PipelineReconstructionEngine()
failure_service = FailureDetectionService()
rca_engine = RootCauseAnalysisEngine()
diagnosis_service = DiagnosisService()
cred_service = CredentialService()



# =====================================================================
# 1. Standard OpenTelemetry / OTLP Trace Ingestion Endpoint
# =====================================================================
@router.post("/v1/traces", status_code=status.HTTP_200_OK, tags=["Telemetry Ingestion"])
@router.post("/v1/traces/v1/traces", status_code=status.HTTP_200_OK, tags=["Telemetry Ingestion"])
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
    body_bytes = await request.body()
    if not body_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty OTLP trace payload received.",
        )

    body_dict = None

    # 1. Try binary Protobuf if header matches application/x-protobuf
    if "application/x-protobuf" in content_type:
        try:
            from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
            from google.protobuf.json_format import MessageToDict

            req_pb = ExportTraceServiceRequest()
            req_pb.ParseFromString(body_bytes)
            body_dict = MessageToDict(req_pb, preserving_proto_field_name=False)
        except Exception:
            pass

    # 2. Try JSON parsing
    if body_dict is None:
        try:
            import json
            body_dict = json.loads(body_bytes.decode("utf-8"))
        except Exception as err_json:
            try:
                from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
                from google.protobuf.json_format import MessageToDict

                req_pb = ExportTraceServiceRequest()
                req_pb.ParseFromString(body_bytes)
                body_dict = MessageToDict(req_pb, preserving_proto_field_name=False)
            except Exception as err_pb:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Malformed OTLP payload: JSON={err_json}, PB={err_pb}",
                )

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
        return result
    except Exception as err:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest OTLP trace payload: {str(err)}",
        )


# =====================================================================
# 2. Versioned Customer REST API: /api/v1/executions/...
# =====================================================================
@router.get(
    "/api/v1/executions/{execution_id}",
    response_model=ExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get execution details",
    tags=["Executions API"],
)
def get_execution_details(
    execution_id: str,
    request: Request,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Returns execution metadata, timing, duration, and associated trace IDs.
    Enforces project isolation.
    """
    if not execution_id or execution_id.strip() == "":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid execution ID.")

    exec_rec = db.query(ExecutionModel).filter_by(id=execution_id).first()
    if not exec_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    # Project Isolation check
    auth_proj = getattr(request.state, "project_id", None) if hasattr(request, "state") else None
    req_proj = auth_proj or extract_project_id(request)
    if req_proj and exec_rec.project_id != req_proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    traces = db.query(TraceModel).filter_by(execution_id=execution_id).all()
    trace_ids = [t.trace_id for t in traces]

    return ExecutionResponse(
        execution_id=exec_rec.id,
        pipeline_id=exec_rec.pipeline_id,
        status=exec_rec.status,
        started_at=exec_rec.started_at.isoformat() if exec_rec.started_at else None,
        ended_at=exec_rec.ended_at.isoformat() if exec_rec.ended_at else None,
        duration_ms=exec_rec.duration_ms,
        trace_ids=trace_ids,
        reconstruction_status="COMPLETE" if traces else "NO_TRACES",
        analysis_status="ANALYZED" if exec_rec.status != "PENDING" else "PENDING",
        environment=exec_rec.environment,
        trigger_type=exec_rec.trigger_type,
    )


@router.get(
    "/api/v1/executions/{execution_id}/graph",
    response_model=ExecutionGraphResponse,
    status_code=status.HTTP_200_OK,
    summary="Get reconstructed execution DAG graph",
    tags=["Executions API"],
)
def get_execution_graph(
    execution_id: str,
    request: Request,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Returns the deterministic DAG execution graph for the specified execution.
    Frontend components use this to render pipeline visualization.
    """
    if not execution_id or execution_id.strip() == "":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid execution ID.")

    exec_rec = db.query(ExecutionModel).filter_by(id=execution_id).first()
    if not exec_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    auth_proj = getattr(request.state, "project_id", None) if hasattr(request, "state") else None
    req_proj = auth_proj or extract_project_id(request)
    if req_proj and exec_rec.project_id != req_proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    traces = db.query(TraceModel).filter_by(execution_id=execution_id).all()
    if not traces:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No telemetry traces found for execution '{execution_id}'.",
        )

    primary_trace_id = traces[0].trace_id
    graph = reconstruction_engine.reconstruct_from_db(primary_trace_id, db)
    return graph.to_dict()


@router.get(
    "/api/v1/executions/{execution_id}/failures",
    response_model=FailureListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get detected execution failures",
    tags=["Executions API"],
)
def get_execution_failures(
    execution_id: str,
    request: Request,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Returns all detected failures for an execution, including correlated detector evidence references.
    """
    if not execution_id or execution_id.strip() == "":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid execution ID.")

    exec_rec = db.query(ExecutionModel).filter_by(id=execution_id).first()
    if not exec_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    auth_proj = getattr(request.state, "project_id", None) if hasattr(request, "state") else None
    req_proj = auth_proj or extract_project_id(request)
    if req_proj and exec_rec.project_id != req_proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    failures = db.query(FailureModel).filter_by(execution_id=execution_id).all()
    if not failures:
        traces = db.query(TraceModel).filter_by(execution_id=execution_id).all()
        if traces:
            try:
                failure_service.detect_and_persist_from_db(traces[0].trace_id, db)
                failures = db.query(FailureModel).filter_by(execution_id=execution_id).all()
            except Exception:
                pass

    failure_items = []

    for f in failures:
        attrs = f.attributes or {}
        failure_items.append(
            FailureItemResponse(
                failure_id=f.id,
                execution_id=f.execution_id,
                trace_id=f.trace_id,
                span_id=f.span_id,
                service_name=attrs.get("service_name", "unknown_service"),
                operation_name=attrs.get("operation_name", "unknown_operation"),
                failure_type=f.failure_type,
                severity=f.severity,
                error_class=f.error_class,
                description=f.description,
                evidence_ids=f.evidence_ids or [],
                root_cause_hypothesis=f.root_cause_hypothesis,
            )
        )

    return FailureListResponse(
        execution_id=execution_id,
        total_failures=len(failure_items),
        failures=failure_items,
    )


@router.get(
    "/api/v1/executions/{execution_id}/root-causes",
    response_model=RootCausesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get root-cause candidates",
    tags=["Executions API"],
)
def get_execution_root_causes(
    execution_id: str,
    request: Request,
    db: Session = Depends(get_db),
    api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Returns root-cause candidates and downstream impact graphs for an execution.
    """
    if not execution_id or execution_id.strip() == "":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid execution ID.")

    exec_rec = db.query(ExecutionModel).filter_by(id=execution_id).first()
    if not exec_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    auth_proj = getattr(request.state, "project_id", None) if hasattr(request, "state") else None
    req_proj = auth_proj or extract_project_id(request)
    if req_proj and exec_rec.project_id != req_proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    traces = db.query(TraceModel).filter_by(execution_id=execution_id).all()
    if not traces:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No traces found for execution '{execution_id}'.",
        )

    rca_res = rca_engine.analyze_and_persist_from_db(traces[0].trace_id, db)
    candidates_list = []
    for c in rca_res.get("candidates", []):
        candidates_list.append(
            RootCauseCandidateResponse(
                candidate_id=c["candidate_id"],
                service_name=c["service_name"],
                operation_name=c["operation_name"],
                span_id=c["span_id"],
                confidence_state=c["confidence_state"],
                relationship_type=c["relationship_type"],
                reason=c["reason"],
                supporting_evidence=c.get("supporting_evidence", []),
                downstream_impact_spans=c.get("downstream_impact_spans", []),
            )
        )

    return RootCausesResponse(
        execution_id=execution_id,
        trace_id=traces[0].trace_id,
        analysis_status=rca_res.get("analysis_status", "COMPLETED"),
        candidates_count=len(candidates_list),
        candidates=candidates_list,
        unresolved_failures=rca_res.get("unresolved_failures", []),
    )


@router.get(
    "/api/v1/executions/{execution_id}/diagnosis",
    response_model=DiagnosisResponse,
    status_code=status.HTTP_200_OK,
    summary="Get structured diagnosis",
    tags=["Executions API"],
)
def get_execution_diagnosis(
    execution_id: str,
    request: Request,
    use_llm: bool = Query(True, description="Enable LLM reasoning layer over deterministic evidence"),
    db: Session = Depends(get_db),
    api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Returns the structured engineering diagnosis for an execution.
    """
    if not execution_id or execution_id.strip() == "":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid execution ID.")

    exec_rec = db.query(ExecutionModel).filter_by(id=execution_id).first()
    if not exec_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    auth_proj = getattr(request.state, "project_id", None) if hasattr(request, "state") else None
    req_proj = auth_proj or extract_project_id(request)
    if req_proj and exec_rec.project_id != req_proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    traces = db.query(TraceModel).filter_by(execution_id=execution_id).all()
    if not traces:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No traces found for execution '{execution_id}'.",
        )

    diag_dict = diagnosis_service.diagnose_and_persist_from_db(traces[0].trace_id, db, use_llm=use_llm)
    return DiagnosisResponse(**diag_dict)


@router.get(
    "/api/v1/executions/{execution_id}/report",
    response_model=AutopsyReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Get complete Autopsy investigation report",
    tags=["Executions API"],
)
def get_execution_report(
    execution_id: str,
    request: Request,
    max_tool_calls: int = Query(10, description="Maximum tool invocations for investigation agent"),
    use_llm: bool = Query(True, description="Enable LLM diagnosis reasoning"),
    db: Session = Depends(get_db),
    api_key: Optional[str] = Depends(verify_api_key),
):
    """
    Returns the complete investigation report synthesized by the Autopsy Investigation Agent.
    """
    if not execution_id or execution_id.strip() == "":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid execution ID.")

    exec_rec = db.query(ExecutionModel).filter_by(id=execution_id).first()
    if not exec_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    auth_proj = getattr(request.state, "project_id", None) if hasattr(request, "state") else None
    req_proj = auth_proj or extract_project_id(request)
    if req_proj and exec_rec.project_id != req_proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Execution '{execution_id}' not found.",
        )

    tools = AutopsyInvestigationTools(db)
    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=max_tool_calls, use_llm=use_llm)
    report = agent.investigate(execution_id=execution_id)
    return AutopsyReportResponse(**report.to_dict())


# =====================================================================
# 3. Customer Project Onboarding & API Key Provisioning (Step 11)
# =====================================================================
@router.post(
    "/api/v1/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new customer project",
    tags=["Projects & Credentials"],
)
@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_project(
    payload: ProjectCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Creates a new isolated customer project tenant.
    """
    if not payload.project_name or not payload.project_name.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project name cannot be empty.",
        )

    project = cred_service.create_project(
        name=payload.project_name,
        description=payload.description,
        db=db,
    )
    return ProjectResponse(
        project_id=project.id,
        project_name=project.name,
        description=project.description,
        status=project.status,
        created_at=project.created_at.isoformat() if project.created_at else None,
        updated_at=project.updated_at.isoformat() if project.updated_at else None,
    )


@router.get(
    "/api/v1/projects/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Get customer project details",
    tags=["Projects & Credentials"],
)
@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieves project details by project_id.
    """
    project = cred_service.get_project(project_id=project_id, db=db)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )
    return ProjectResponse(
        project_id=project.id,
        project_name=project.name,
        description=project.description,
        status=project.status,
        created_at=project.created_at.isoformat() if project.created_at else None,
        updated_at=project.updated_at.isoformat() if project.updated_at else None,
    )


@router.post(
    "/api/v1/projects/{project_id}/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a new API key for a project",
    tags=["Projects & Credentials"],
)
@router.post(
    "/projects/{project_id}/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_project_api_key(
    project_id: str,
    payload: Optional[ApiKeyCreateRequest] = None,
    db: Session = Depends(get_db),
):
    """
    Generates a secure random API key and stores its SHA-256 hash.
    The raw API key is returned ONLY ONCE in the response body.
    """
    project = cred_service.get_project(project_id=project_id, db=db)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    key_name = payload.name if payload and payload.name else "default-key"
    try:
        key_model, raw_key = cred_service.create_api_key(
            project_id=project_id,
            name=key_name,
            db=db,
        )
        return ApiKeyCreatedResponse(
            credential_id=key_model.id,
            project_id=key_model.project_id,
            name=key_model.name,
            key_prefix=key_model.key_prefix,
            api_key=raw_key,
            status=key_model.status,
            created_at=key_model.created_at.isoformat() if key_model.created_at else None,
        )
    except Exception as err:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to provision API key: {str(err)}",
        )


@router.get(
    "/api/v1/projects/{project_id}/keys",
    response_model=List[ApiKeyItemResponse],
    status_code=status.HTTP_200_OK,
    summary="List API keys for a project",
    tags=["Projects & Credentials"],
)
@router.get(
    "/projects/{project_id}/keys",
    response_model=List[ApiKeyItemResponse],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def list_project_api_keys(
    project_id: str,
    db: Session = Depends(get_db),
):
    """
    Lists API key metadata for a project. Raw keys and hashes are never exposed.
    """
    project = cred_service.get_project(project_id=project_id, db=db)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    keys = cred_service.list_api_keys(project_id=project_id, db=db)
    return [
        ApiKeyItemResponse(
            credential_id=k.id,
            project_id=k.project_id,
            name=k.name,
            key_prefix=k.key_prefix,
            status=k.status,
            created_at=k.created_at.isoformat() if k.created_at else None,
            revoked_at=k.revoked_at.isoformat() if k.revoked_at else None,
        )
        for k in keys
    ]


@router.post(
    "/api/v1/projects/{project_id}/keys/{key_id}/revoke",
    response_model=ApiKeyRevokeResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke an API key",
    tags=["Projects & Credentials"],
)
@router.post(
    "/projects/{project_id}/keys/{key_id}/revoke",
    response_model=ApiKeyRevokeResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def revoke_project_api_key(
    project_id: str,
    key_id: str,
    db: Session = Depends(get_db),
):
    """
    Revokes an API key credential immediately.
    Future telemetry authenticated with this key will be rejected (401).
    Historical telemetry remains accessible.
    """
    project = cred_service.get_project(project_id=project_id, db=db)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )

    revoked_key = cred_service.revoke_api_key(project_id=project_id, key_id=key_id, db=db)
    if not revoked_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API Key '{key_id}' not found for project '{project_id}'.",
        )

    return ApiKeyRevokeResponse(
        credential_id=revoked_key.id,
        project_id=revoked_key.project_id,
        status=revoked_key.status,
        revoked_at=revoked_key.revoked_at.isoformat() if revoked_key.revoked_at else None,
        message="API key successfully revoked. Future telemetry with this key will be rejected.",
    )


# =====================================================================
# 4. Intermediate Internal Pipeline Endpoints (Preserved for compatibility)
# =====================================================================
@router.get("/v1/traces/{trace_id}/reconstruction", status_code=status.HTTP_200_OK, tags=["Internal Traces"])
def get_trace_reconstruction(trace_id: str, db: Session = Depends(get_db)):
    graph = reconstruction_engine.reconstruct_from_db(trace_id, db)
    if graph.reconstruction_status == "CORRUPTED" and any(w["code"] == "TRACE_NOT_FOUND" for w in graph.warnings):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trace '{trace_id}' not found.",
        )
    return graph.to_dict()


@router.post("/v1/traces/{trace_id}/failures", status_code=status.HTTP_200_OK, tags=["Internal Traces"])
def detect_and_persist_failures(trace_id: str, db: Session = Depends(get_db)):
    try:
        return failure_service.detect_and_persist_from_db(trace_id, db)
    except Exception as err:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(err))


@router.post("/v1/traces/{trace_id}/root-cause", status_code=status.HTTP_200_OK, tags=["Internal Traces"])
def analyze_and_persist_root_cause(trace_id: str, db: Session = Depends(get_db)):
    try:
        return rca_engine.analyze_and_persist_from_db(trace_id, db)
    except Exception as err:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(err))


@router.post("/v1/traces/{trace_id}/diagnose", status_code=status.HTTP_200_OK, tags=["Internal Traces"])
def diagnose_trace_incident(trace_id: str, use_llm: bool = True, db: Session = Depends(get_db)):
    try:
        return diagnosis_service.diagnose_and_persist_from_db(trace_id, db, use_llm=use_llm)
    except Exception as err:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(err))


@router.post("/v1/executions/{execution_id}/investigate", status_code=status.HTTP_200_OK, tags=["Internal Traces"])
def investigate_execution_legacy(execution_id: str, max_tool_calls: int = 10, use_llm: bool = True, db: Session = Depends(get_db)):
    tools = AutopsyInvestigationTools(db)
    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=max_tool_calls, use_llm=use_llm)
    return agent.investigate(execution_id=execution_id).to_dict()


@router.post("/v1/traces/{trace_id}/investigate", status_code=status.HTTP_200_OK, tags=["Internal Traces"])
def investigate_trace_legacy(trace_id: str, max_tool_calls: int = 10, use_llm: bool = True, db: Session = Depends(get_db)):
    trace_rec = db.query(TraceModel).filter_by(trace_id=trace_id).first()
    exec_id = trace_rec.execution_id if trace_rec else "unknown"
    tools = AutopsyInvestigationTools(db)
    agent = AutopsyInvestigationAgent(tools=tools, max_tool_calls=max_tool_calls, use_llm=use_llm)
    return agent.investigate(execution_id=exec_id, trace_id=trace_id).to_dict()


@router.get("/health", status_code=status.HTTP_200_OK, tags=["Health"])
def health_check():
    return {"status": "ok", "service": "pipeline-autopsy-engine", "version": "0.1.0"}


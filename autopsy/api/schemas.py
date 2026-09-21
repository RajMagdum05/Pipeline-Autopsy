from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExecutionResponse(BaseModel):
    """Execution metadata response schema."""
    execution_id: str
    pipeline_id: str
    status: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_ms: Optional[float] = None
    trace_ids: List[str] = Field(default_factory=list)
    reconstruction_status: Optional[str] = "COMPLETE"
    analysis_status: Optional[str] = "ANALYZED"
    environment: Optional[str] = "production"
    trigger_type: Optional[str] = "manual"


class ExecutionListItemResponse(ExecutionResponse):
    """Execution list item with summary counts for dashboard tables."""
    failure_count: int = 0
    primary_trace_id: Optional[str] = None


class DashboardSummaryResponse(BaseModel):
    """Customer-facing dashboard summary built from persisted telemetry."""
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    connection_status: str
    last_telemetry_received_at: Optional[str] = None
    recent_executions: List[ExecutionListItemResponse] = Field(default_factory=list)
    recent_findings: List[Dict[str, Any]] = Field(default_factory=list)


class ExecutionNodeResponse(BaseModel):
    """Reconstructed execution graph node schema."""
    span_id: str
    parent_span_id: Optional[str] = None
    service_name: str
    operation_name: str
    kind: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_ms: Optional[float] = None
    status_code: str
    status_message: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)
    is_orphan: bool = False
    is_duplicate: bool = False
    children: List["ExecutionNodeResponse"] = Field(default_factory=list)


class ExecutionGraphResponse(BaseModel):
    """Reconstructed DAG execution graph response schema."""
    execution_id: str
    trace_id: str
    reconstruction_status: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_ms: Optional[float] = None
    total_spans_count: int
    root_nodes: List[ExecutionNodeResponse] = Field(default_factory=list)
    orphan_nodes: List[ExecutionNodeResponse] = Field(default_factory=list)
    warnings: List[Dict[str, Any]] = Field(default_factory=list)


class FailureItemResponse(BaseModel):
    """Individual failure finding item."""
    failure_id: str
    execution_id: str
    trace_id: str
    span_id: Optional[str] = None
    service_name: str
    operation_name: str
    failure_type: str
    severity: str
    error_class: Optional[str] = None
    description: str
    evidence_ids: List[str] = Field(default_factory=list)
    root_cause_hypothesis: Optional[str] = None


class FailureListResponse(BaseModel):
    """Detected failures response schema."""
    execution_id: str
    total_failures: int
    failures: List[FailureItemResponse] = Field(default_factory=list)


class RootCauseCandidateResponse(BaseModel):
    """Root-cause candidate schema."""
    candidate_id: str
    service_name: str
    operation_name: str
    span_id: str
    confidence_state: str
    relationship_type: str
    reason: str
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    downstream_impact_spans: List[Dict[str, Any]] = Field(default_factory=list)


class RootCausesResponse(BaseModel):
    """Root cause analysis response schema."""
    execution_id: str
    trace_id: str
    analysis_status: str
    candidates_count: int
    candidates: List[RootCauseCandidateResponse] = Field(default_factory=list)
    unresolved_failures: List[Dict[str, Any]] = Field(default_factory=list)


class DiagnosisResponse(BaseModel):
    """Structured diagnosis response schema."""
    diagnosis_id: str
    execution_id: str
    trace_id: str
    summary: str
    affected_component: str
    observed_failure: str
    root_cause_candidate: str
    supporting_evidence: List[str] = Field(default_factory=list)
    downstream_impact: List[str] = Field(default_factory=list)
    uncertainty: str
    suggested_investigation: List[str] = Field(default_factory=list)
    reasoning_source: str
    generated_at: Optional[str] = None


class AutopsyReportResponse(BaseModel):
    """Complete investigation report response schema."""
    report_id: str
    execution_id: str
    trace_id: str
    investigation_status: str
    affected_components: List[str] = Field(default_factory=list)
    observed_failures: List[str] = Field(default_factory=list)
    root_cause_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    supporting_evidence: List[str] = Field(default_factory=list)
    downstream_impact: List[str] = Field(default_factory=list)
    diagnosis: Optional[Dict[str, Any]] = None
    uncertainty: str
    suggested_investigation: List[str] = Field(default_factory=list)
    steps_executed: List[Dict[str, Any]] = Field(default_factory=list)
    generated_at: Optional[str] = None


class ErrorDetailResponse(BaseModel):
    """Standardized API error response schema."""
    detail: str
    status_code: int


# =====================================================================
# Customer Project Onboarding & API Key Credential Schemas (Step 11)
# =====================================================================
class ProjectCreateRequest(BaseModel):
    """Payload to create a new customer project."""
    project_name: str = Field(..., min_length=1, max_length=255, description="Name of customer project")
    description: Optional[str] = Field(None, max_length=1000, description="Optional description")


class ProjectResponse(BaseModel):
    """Customer project details response."""
    project_id: str
    project_name: str
    description: Optional[str] = None
    status: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ApiKeyCreateRequest(BaseModel):
    """Payload to provision a new API key."""
    name: Optional[str] = Field("default-key", max_length=255, description="Display name for the credential")


class ApiKeyCreatedResponse(BaseModel):
    """
    Response returned ONLY ONCE when a new API key is provisioned.
    Contains the raw api_key string. Backend stores only the SHA-256 hash.
    """
    credential_id: str
    project_id: str
    name: str
    key_prefix: str
    api_key: str
    status: str
    created_at: Optional[str] = None


class ApiKeyItemResponse(BaseModel):
    """API key credential metadata (never contains raw key or full hash)."""
    credential_id: str
    project_id: str
    name: str
    key_prefix: str
    status: str
    created_at: Optional[str] = None
    revoked_at: Optional[str] = None


class ApiKeyRevokeResponse(BaseModel):
    """Response after revoking an API key credential."""
    credential_id: str
    project_id: str
    status: str
    revoked_at: Optional[str] = None
    message: str

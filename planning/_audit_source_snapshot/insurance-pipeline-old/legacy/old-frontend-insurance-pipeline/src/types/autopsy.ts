export type ConnectionStatus = 'CONNECTED' | 'NO_RECENT_DATA' | 'DISCONNECTED';

export interface ExecutionListItem {
  execution_id: string;
  pipeline_id: string;
  status: string;
  started_at?: string | null;
  ended_at?: string | null;
  duration_ms?: number | null;
  trace_ids: string[];
  primary_trace_id?: string | null;
  failure_count: number;
  reconstruction_status?: string | null;
  analysis_status?: string | null;
  environment?: string | null;
  trigger_type?: string | null;
}

export interface DashboardSummary {
  project_id?: string | null;
  project_name?: string | null;
  connection_status: ConnectionStatus;
  last_telemetry_received_at?: string | null;
  recent_executions: ExecutionListItem[];
  recent_findings: FailureItem[];
}

export interface ExecutionNode {
  span_id: string;
  parent_span_id?: string | null;
  service_name: string;
  operation_name: string;
  kind: string;
  start_time?: string | null;
  end_time?: string | null;
  duration_ms?: number | null;
  status_code: string;
  status_message?: string | null;
  attributes: Record<string, unknown>;
  events: Array<Record<string, unknown>>;
  is_orphan: boolean;
  is_duplicate: boolean;
  children: ExecutionNode[];
}

export interface ExecutionGraph {
  execution_id: string;
  trace_id: string;
  reconstruction_status: string;
  start_time?: string | null;
  end_time?: string | null;
  duration_ms?: number | null;
  total_spans_count: number;
  root_nodes: ExecutionNode[];
  orphan_nodes: ExecutionNode[];
  warnings: Array<Record<string, unknown>>;
}

export interface FailureItem {
  failure_id: string;
  execution_id: string;
  trace_id: string;
  span_id?: string | null;
  service_name: string;
  operation_name: string;
  failure_type: string;
  severity: string;
  error_class?: string | null;
  description: string;
  evidence_ids: string[];
  root_cause_hypothesis?: string | null;
}

export interface FailureList {
  execution_id: string;
  total_failures: number;
  failures: FailureItem[];
}

export interface RootCauseCandidate {
  candidate_id: string;
  service_name: string;
  operation_name: string;
  span_id: string;
  confidence_state: string;
  relationship_type: string;
  reason: string;
  supporting_evidence: Array<Record<string, unknown>>;
  downstream_impact_spans: Array<Record<string, unknown>>;
}

export interface RootCauses {
  execution_id: string;
  trace_id: string;
  analysis_status: string;
  candidates_count: number;
  candidates: RootCauseCandidate[];
  unresolved_failures: Array<Record<string, unknown>>;
}

export interface Diagnosis {
  diagnosis_id: string;
  execution_id: string;
  trace_id: string;
  summary: string;
  affected_component: string;
  observed_failure: string;
  root_cause_candidate: string;
  supporting_evidence: string[];
  downstream_impact: string[];
  uncertainty: string;
  suggested_investigation: string[];
  reasoning_source: string;
  generated_at?: string | null;
}

export interface AutopsyReport {
  report_id: string;
  execution_id: string;
  trace_id: string;
  investigation_status: string;
  affected_components: string[];
  observed_failures: string[];
  root_cause_candidates: Array<Record<string, unknown>>;
  supporting_evidence: string[];
  downstream_impact: string[];
  diagnosis?: Record<string, unknown> | null;
  uncertainty: string;
  suggested_investigation: string[];
  steps_executed: Array<Record<string, unknown>>;
  generated_at?: string | null;
}

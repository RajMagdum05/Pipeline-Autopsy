export type Execution = {
  id: string
  entity_id: string | null
  pipeline: string
  version: string
  started_at: string
  verdict: string | null
  grade: string | null
  run_outcome: string | null
  duration_ms: number | null
  origin_stages: string[]
}

export type PipelineSummary = {
  pipeline: string
  version: string
  project_id: string
  manifest: Record<string, unknown>
}

export type ExecutionPage = {
  executions: Execution[]
  next_cursor: string | null
}

export type PipelinePage = { pipelines: PipelineSummary[] }

export type ExecutionDetail = {
  id: string
  execution_id: string
  project_id: string
  pipeline: string
  version: string
  entity_id: string | null
  status: string
  trace_grade: string | null
  verdict: string | null
  ended_at: string | null
  started_at: string
  timings: { started_at: string; ended_at: string | null }
  trace_ids: string[]
  jaeger_url: string | null
}

export type GraphNode = {
  id: string
  stage: string
  item_id: string | null
  item_role: string | null
  role: string
  status: string | null
  attempts: number
}

export type GraphEdge = {
  from: string
  to: string
  kind: string
  artifact_ids: string[]
  type: 'data' | 'control'
  tainted: boolean
}

export type ExecutionGraph = { nodes: GraphNode[]; edges: GraphEdge[] }

export type Observation = {
  id: string
  family: string
  code: string
  result: string
  stage: string | null
  span_id: string | null
  artifact_id: string | null
  field: string | null
  detail: string
}

export type Finding = {
  id: string
  stage: string
  item_id: string | null
  role: string
  classification: string | null
  confidence: string | null
  severity: string | null
  link: string | null
  caused_by: string[]
  evidence: string[]
  note: string | null
}

export type Diagnosis = {
  execution_id: string
  pipeline: string
  version: string
  entity_id: string | null
  verdict: string | null
  trace_grade: string | null
  findings: Finding[]
  observations: Observation[]
  explanation: { source: string; summary: string; narrative: string[]; remediation: string[] } | null
}

export type NormalizedSpan = {
  trace_id: string
  span_id: string
  parent: string | null
  name: string
  kind: string
  role: string
  stage_name: string | null
  item_id: string | null
  status: string
  start: string
  end: string | null
  status_message: string | null
  attrs: Record<string, unknown>
  resource: Record<string, unknown>
  events: Array<{ name: string; timestamp?: string; attributes: Record<string, unknown> }>
  error_type?: string | null
  error_class?: string | null
}

export type SpanPage = { spans: NormalizedSpan[] }
export type DiagnosisResponse = { pending: true; status: string } | Diagnosis
export type ArtifactResponse = {
  id: string
  kind: string
  content?: unknown
  content_b64?: string
  content_masked?: boolean
  redacted: boolean
}

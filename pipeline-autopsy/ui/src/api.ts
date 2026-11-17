import type {
  ArtifactResponse, DiagnosisResponse, ExecutionDetail, ExecutionGraph, ExecutionPage, PipelinePage, SpanPage,
} from './types'

const API_KEY_STORAGE = 'pipeline-autopsy-api-key'

export function configuredApiKey(): string {
  try {
    return localStorage.getItem(API_KEY_STORAGE) || import.meta.env.VITE_AUTOPSY_API_KEY || ''
  } catch {
    return import.meta.env.VITE_AUTOPSY_API_KEY || ''
  }
}

export function saveApiKey(value: string): void {
  localStorage.setItem(API_KEY_STORAGE, value.trim())
}

function requestHeaders(): Record<string, string> {
  const key = configuredApiKey()
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (key) {
    headers.Authorization = `Bearer ${key}`
    headers['X-Autopsy-Api-Key'] = key
  }
  return headers
}

async function requestJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const headers = requestHeaders()
  const response = await fetch(path, { headers, signal })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json() as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // Keep the HTTP status when the server did not return JSON.
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export function getExecutions(params: URLSearchParams, signal?: AbortSignal): Promise<ExecutionPage> {
  return requestJson<ExecutionPage>(`/v1/executions?${params.toString()}`, signal)
}

export function getPipelines(signal?: AbortSignal): Promise<PipelinePage> {
  return requestJson<PipelinePage>('/v1/pipelines', signal)
}

export function getExecution(executionId: string, signal?: AbortSignal): Promise<ExecutionDetail> {
  return requestJson<ExecutionDetail>(`/v1/executions/${encodeURIComponent(executionId)}`, signal)
}

export function getExecutionGraph(executionId: string, signal?: AbortSignal): Promise<ExecutionGraph> {
  return requestJson<ExecutionGraph>(`/v1/executions/${encodeURIComponent(executionId)}/graph`, signal)
}

export function getExecutionSpans(executionId: string, signal?: AbortSignal): Promise<SpanPage> {
  return requestJson<SpanPage>(`/v1/executions/${encodeURIComponent(executionId)}/spans`, signal)
}

export async function getDiagnosis(executionId: string, signal?: AbortSignal): Promise<DiagnosisResponse> {
  const response = await fetch(`/v1/executions/${encodeURIComponent(executionId)}/diagnosis`, {
    headers: requestHeaders(), signal,
  })
  if (response.status === 409) {
    const body = await response.json() as { status?: string }
    return { pending: true, status: body.status || 'queued' }
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<DiagnosisResponse>
}

export function getArtifact(artifactId: string, signal?: AbortSignal): Promise<ArtifactResponse> {
  return requestJson<ArtifactResponse>(`/v1/artifacts/${encodeURIComponent(artifactId)}`, signal)
}

export async function requeueDiagnosis(executionId: string): Promise<void> {
  const response = await fetch(`/v1/executions/${encodeURIComponent(executionId)}/diagnose`, {
    method: 'POST', headers: requestHeaders(),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string; status?: string }
    throw new Error(body.detail || body.status || `${response.status} ${response.statusText}`)
  }
}

export async function submitFindingFeedback(findingId: string, verdict: 'confirmed' | 'rejected', comment?: string): Promise<void> {
  const response = await fetch(`/v1/findings/${encodeURIComponent(findingId)}/feedback`, {
    method: 'POST', headers: { ...requestHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ verdict, comment: comment?.trim() || null }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail || `${response.status} ${response.statusText}`)
  }
}

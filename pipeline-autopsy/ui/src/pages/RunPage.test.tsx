import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getDiagnosis, getExecution, getExecutionGraph, getExecutionSpans, getPipelines } from '../api'
import { RunPage } from './RunPage'

vi.mock('../api', () => ({
  getArtifact: vi.fn(), getDiagnosis: vi.fn(), getExecution: vi.fn(), getExecutionGraph: vi.fn(),
  getExecutionSpans: vi.fn(), getPipelines: vi.fn(), requeueDiagnosis: vi.fn(),
}))

beforeEach(() => {
  vi.mocked(getExecution).mockResolvedValue({
    id: 'toy_short_body', execution_id: 'toy_short_body', project_id: 'default',
    pipeline: 'toy-summarizer', version: '0.1.0', entity_id: null, status: 'diagnosed',
    started_at: '2026-11-17T10:00:00Z', ended_at: '2026-11-17T10:00:01Z',
    timings: { started_at: '2026-11-17T10:00:00Z', ended_at: '2026-11-17T10:00:01Z' },
    trace_grade: 'A', verdict: 'ROOT_CAUSE_IDENTIFIED', trace_ids: [], jaeger_url: null,
  })
  vi.mocked(getExecutionGraph).mockResolvedValue({
    nodes: [
      { id: 'fetch', stage: 'fetch', item_id: null, item_role: null, role: 'origin', status: 'success', attempts: 1 },
      { id: 'summarize', stage: 'summarize', item_id: null, item_role: null, role: 'tainted', status: 'success', attempts: 1 },
      { id: 'publish', stage: 'publish', item_id: null, item_role: null, role: 'tainted', status: 'success', attempts: 1 },
    ],
    edges: [{ from: 'fetch', to: 'summarize', kind: 'page', artifact_ids: ['art_0123456789abcdef'], type: 'data', tainted: true }],
  })
  vi.mocked(getExecutionSpans).mockResolvedValue({ spans: [] })
  vi.mocked(getPipelines).mockResolvedValue({ pipelines: [{ pipeline: 'toy-summarizer', version: '0.1.0', project_id: 'default', manifest: {
    evidence: { level: 'E2' }, stages: [{ name: 'fetch' }, { name: 'summarize' }, { name: 'publish' }],
  } }] })
  vi.mocked(getDiagnosis).mockResolvedValue({
    execution_id: 'toy_short_body', pipeline: 'toy-summarizer', version: '0.1.0', entity_id: null,
    verdict: 'ROOT_CAUSE_IDENTIFIED', trace_grade: 'A',
    findings: [{ id: 'finding-1', stage: 'fetch', item_id: null, role: 'origin',
      classification: 'OUTPUT_CONTRACT_VIOLATION', confidence: 'supported', severity: 'fail',
      link: null, caused_by: [], evidence: ['obs_001'], note: null }],
    observations: [{ id: 'obs_001', family: 'contract', code: 'schema.minLength', result: 'fail', stage: 'fetch',
      span_id: 'span-fetch', artifact_id: 'art_0123456789abcdef', field: 'body', detail: "'too short' is too short" }],
    explanation: { source: 'template', summary: 'fetch produced a page below the declared schema minimum.', narrative: [], remediation: [] },
  })
})

describe('RunPage', () => {
  it('shows the failing fetch stage as the origin with its schema evidence', async () => {
    const { container } = render(<MemoryRouter initialEntries={['/runs/toy_short_body']}>
      <Routes><Route path="/runs/:executionId" element={<RunPage />} /></Routes>
    </MemoryRouter>)
    expect(await screen.findByText('schema.minLength')).toBeTruthy()
    expect(screen.getAllByText('OUTPUT CONTRACT VIOLATION').length).toBeGreaterThan(0)
    expect(screen.getByText('fetch produced a page below the declared schema minimum.')).toBeTruthy()
    expect(container.querySelector('[data-role="origin"][data-stage="fetch"]')).not.toBeNull()
  })
})

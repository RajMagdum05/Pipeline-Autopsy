import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { getExecutions, getPipelines } from '../api'
import { RunsPage } from './RunsPage'

vi.mock('../api', () => ({ getExecutions: vi.fn(), getPipelines: vi.fn() }))

const execution = {
  id: 'toy-short-body',
  entity_id: 'claim-demo-1',
  pipeline: 'toy-summarizer',
  version: '0.1.0',
  started_at: '2026-11-17T10:00:00Z',
  verdict: 'ROOT_CAUSE_IDENTIFIED',
  grade: 'A',
  run_outcome: 'success',
  duration_ms: 82,
  origin_stages: ['fetch'],
}

describe('RunsPage', () => {
  beforeEach(() => {
    vi.mocked(getPipelines).mockResolvedValue({ pipelines: [{
      pipeline: 'toy-summarizer', version: '0.1.0', project_id: 'default', manifest: {},
    }] })
    vi.mocked(getExecutions).mockResolvedValue({ executions: [execution], next_cursor: null })
  })

  afterEach(() => cleanup())

  it('shows the run and its diagnosis badges from the read API', async () => {
    render(<MemoryRouter><RunsPage /></MemoryRouter>)
    const pipeline = await screen.findByText('toy-summarizer', { selector: '.pipeline-name' })
    const row = pipeline.closest('tr')
    expect(row?.querySelector('.badge')?.textContent).toBe('Root cause')
    expect(row?.querySelector('.grade')?.textContent).toBe('A')
    expect(row?.textContent).toContain('fetch')
  })
})

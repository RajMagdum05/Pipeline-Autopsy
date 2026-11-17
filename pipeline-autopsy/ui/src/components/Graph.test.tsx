import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ExecutionGraph } from '../types'
import { Graph, layoutGraph } from './Graph'

const fanoutFixture: ExecutionGraph = {
  nodes: [
    { id: 'adjudicate', stage: 'adjudicate', item_id: null, item_role: null, role: 'not_executed', status: 'not_executed', attempts: 0 },
    { id: 'extract@bill-2', stage: 'extract', item_id: 'bill-2', item_role: 'proof', role: 'healthy', status: 'success', attempts: 1 },
    { id: 'validate@policy-1', stage: 'validate', item_id: 'policy-1', item_role: 'policy', role: 'healthy', status: 'success', attempts: 1 },
    { id: 'fetch@bill-2', stage: 'fetch', item_id: 'bill-2', item_role: 'proof', role: 'origin', status: 'failed', attempts: 2 },
  ],
  edges: [
    { from: 'validate@policy-1', to: 'fetch@bill-2', kind: 'gate:validate', artifact_ids: [], type: 'control', tainted: true },
    { from: 'fetch@bill-2', to: 'extract@bill-2', kind: 'page', artifact_ids: ['art_a'], type: 'data', tainted: true },
  ],
}

describe('Graph', () => {
  it('lays out fan-out stages in manifest order with item rows and a run row', () => {
    const order = ['validate', 'fetch', 'extract', 'adjudicate']
    const first = layoutGraph(fanoutFixture, order)
    const second = layoutGraph(fanoutFixture, order)
    expect(first.nodes.map(({ id, x, y }) => [id, x, y])).toEqual(second.nodes.map(({ id, x, y }) => [id, x, y]))
    const policy = first.nodes.find((node) => node.id === 'validate@policy-1')
    const fetch = first.nodes.find((node) => node.id === 'fetch@bill-2')
    const final = first.nodes.find((node) => node.id === 'adjudicate')
    expect(policy?.x).toBeLessThan(fetch?.x ?? 0)
    expect(fetch?.row).toBe('bill-2')
    expect(final?.row).toBe('claim')
    expect(first.edges.map((edge) => edge.type).sort()).toEqual(['control', 'data'])
  })

  it('applies the origin role and semantic edge classes to SVG elements', () => {
    const { container } = render(<Graph graph={fanoutFixture} manifestStageOrder={['validate', 'fetch', 'extract', 'adjudicate']} />)
    expect(container.querySelector('[data-role="origin"][data-stage="fetch"][data-item-role="proof"]')).not.toBeNull()
    expect(container.querySelector('[data-edge-type="control"].graph-edge--control')).not.toBeNull()
    expect(container.querySelector('[data-edge-type="data"].graph-edge--data')).not.toBeNull()
  })
})

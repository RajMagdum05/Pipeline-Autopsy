import type { KeyboardEvent } from 'react'
import type { ExecutionGraph, GraphEdge, GraphNode } from '../types'

export type PositionedNode = GraphNode & { x: number; y: number; row: string }
export type PositionedEdge = GraphEdge & { source: PositionedNode; target: PositionedNode }
export type GraphLayout = { nodes: PositionedNode[]; edges: PositionedEdge[]; width: number; height: number }

const COLUMN_GAP = 230
const ROW_GAP = 112
const NODE_WIDTH = 170
const NODE_HEIGHT = 60

function roleRank(role: string | null): number {
  if (role === 'policy') return 0
  if (role === 'proof') return 1
  return 2
}

export function layoutGraph(graph: ExecutionGraph, manifestStageOrder: string[] = []): GraphLayout {
  const stages = [...new Set(graph.nodes.map((node) => node.stage))]
  const manifestIndex = new Map(manifestStageOrder.map((stage, index) => [stage, index]))
  stages.sort((a, b) => {
    const aIndex = manifestIndex.get(a)
    const bIndex = manifestIndex.get(b)
    if (aIndex !== undefined || bIndex !== undefined) {
      return (aIndex ?? Number.MAX_SAFE_INTEGER) - (bIndex ?? Number.MAX_SAFE_INTEGER) || a.localeCompare(b)
    }
    return a.localeCompare(b)
  })
  const stageIndex = new Map(stages.map((stage, index) => [stage, index]))
  const itemNodes = graph.nodes.filter((node) => node.item_id)
  const itemRows = [...new Map(itemNodes.map((node) => [node.item_id!, node])).values()]
    .sort((a, b) => roleRank(a.item_role) - roleRank(b.item_role)
      || (a.item_role || '').localeCompare(b.item_role || '')
      || (a.item_id || '').localeCompare(b.item_id || ''))
    .map((node) => node.item_id!)
  const hasRunNodes = graph.nodes.some((node) => !node.item_id)
  const rows = hasRunNodes ? [...itemRows, 'claim'] : itemRows
  if (rows.length === 0) rows.push('claim')
  const rowIndex = new Map(rows.map((row, index) => [row, index]))

  const nodes = graph.nodes.map((node) => {
    const row = node.item_id || 'claim'
    return {
      ...node,
      row,
      x: 35 + (stageIndex.get(node.stage) || 0) * COLUMN_GAP,
      y: 24 + (rowIndex.get(row) || 0) * ROW_GAP,
    }
  }).sort((a, b) => a.y - b.y || a.x - b.x || a.id.localeCompare(b.id))
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const edges = graph.edges.map((edge) => {
    const source = nodeById.get(edge.from)
    const target = nodeById.get(edge.to)
    return source && target ? { ...edge, source, target } : null
  }).filter((edge): edge is PositionedEdge => edge !== null)
    .sort((a, b) => a.source.id.localeCompare(b.source.id) || a.target.id.localeCompare(b.target.id)
      || a.type.localeCompare(b.type))
  return {
    nodes,
    edges,
    width: Math.max(360, stages.length * COLUMN_GAP + 10),
    height: Math.max(130, rows.length * ROW_GAP + 10),
  }
}

function roleClass(role: string): string {
  if (role === 'missing' || role === 'not_executed') return 'missing'
  return ['origin', 'propagated', 'tainted', 'healthy'].includes(role) ? role : 'healthy'
}

function roleLabel(role: string): string {
  if (role === 'origin') return 'ORIGIN'
  if (role === 'propagated') return 'PROPAGATED'
  if (role === 'tainted') return 'TAINTED'
  if (role === 'missing' || role === 'not_executed') return 'DID NOT RUN'
  return ''
}

function selectOnKey(event: KeyboardEvent<SVGGElement>, callback: () => void) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    callback()
  }
}

export function Graph({
  graph, manifestStageOrder = [], selectedNodeId, onSelect,
}: {
  graph: ExecutionGraph
  manifestStageOrder?: string[]
  selectedNodeId?: string | null
  onSelect?: (node: GraphNode) => void
}) {
  const layout = layoutGraph(graph, manifestStageOrder)
  return (
    <div className="graph-scroll" aria-label="Execution lineage graph">
      {layout.nodes.length === 0 ? <p className="muted graph-empty">No stage spans were recorded for this run.</p> : (
        <svg className="lineage-graph" viewBox={`0 0 ${layout.width} ${layout.height}`} role="img"
          aria-label="Pipeline stages, data lineage, and control dependencies">
          <defs>
            <marker id="graph-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L0,6 L7,3 z" fill="currentColor" />
            </marker>
          </defs>
          {layout.edges.map((edge) => {
            const x1 = edge.source.x + NODE_WIDTH
            const y1 = edge.source.y + NODE_HEIGHT / 2
            const x2 = edge.target.x
            const y2 = edge.target.y + NODE_HEIGHT / 2
            const middle = (x1 + x2) / 2
            return <path key={`${edge.from}-${edge.to}-${edge.type}-${edge.kind}`}
              className={`graph-edge graph-edge--${edge.type}${edge.tainted ? ' graph-edge--tainted' : ''}`}
              data-edge-type={edge.type} d={`M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}`}
              markerEnd="url(#graph-arrow)" aria-label={`${edge.type} edge from ${edge.from} to ${edge.to}`} />
          })}
          {layout.nodes.map((node) => {
            const cls = roleClass(node.role)
            const selected = selectedNodeId === node.id
            const choose = () => onSelect?.(node)
            return <g key={node.id} className={`graph-node graph-node--${cls}${selected ? ' is-selected' : ''}`}
              data-role={node.role} data-stage={node.stage} data-item-role={node.item_role || ''}
              transform={`translate(${node.x} ${node.y})`} role="button" tabIndex={0}
              aria-label={`${node.stage}${node.item_id ? `, ${node.item_role || 'item'} ${node.item_id}` : ', run stage'}, ${roleLabel(node.role) || node.status || 'healthy'}`}
              onClick={choose} onKeyDown={(event) => selectOnKey(event, choose)}>
              <rect width={NODE_WIDTH} height={NODE_HEIGHT} rx="8" />
              <text className="graph-node__title" x="12" y="22">{node.stage}</text>
              <text className="graph-node__subtitle" x="12" y="40">{node.item_id ? `${node.item_role || 'item'} · ${node.item_id}` : 'claim / run'}</text>
              {roleLabel(node.role) && <text className="graph-node__role" x={NODE_WIDTH - 10} y="15" textAnchor="end">{roleLabel(node.role)}</text>}
              {node.attempts > 1 && <text className="graph-node__attempts" x={NODE_WIDTH - 10} y={NODE_HEIGHT - 9} textAnchor="end">×{node.attempts}</text>}
            </g>
          })}
        </svg>
      )}
    </div>
  )
}

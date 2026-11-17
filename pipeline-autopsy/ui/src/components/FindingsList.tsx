import type { Finding } from '../types'

const ORDER: Record<string, number> = { origin: 0, propagated: 1, tainted: 2, not_executed: 3, missing: 4, healthy: 5 }

export function findingNodeId(finding: Finding): string {
  return finding.item_id ? `${finding.stage}@${finding.item_id}` : finding.stage
}

export function FindingsList({ findings, selectedStage, onSelect }: {
  findings: Finding[]
  selectedStage?: string | null
  onSelect?: (stageId: string) => void
}) {
  const sorted = [...findings].sort((a, b) => (ORDER[a.role] ?? 9) - (ORDER[b.role] ?? 9)
    || findingNodeId(a).localeCompare(findingNodeId(b)))
  return (
    <section className="findings-panel" aria-label="Findings">
      <div className="section-heading"><div><p className="eyebrow">DIAGNOSIS</p><h2>Findings</h2></div>
        <span className="count-pill">{findings.length}</span></div>
      {sorted.length === 0 ? <p className="muted panel-empty">No pipeline fault was detected.</p> : (
        <ol className="finding-list">
          {sorted.map((finding) => {
            const stageId = findingNodeId(finding)
            return <li key={finding.id}>
              <button type="button" className={`finding-item${selectedStage === stageId ? ' is-selected' : ''}`}
                onClick={() => onSelect?.(stageId)} aria-current={selectedStage === stageId ? 'true' : undefined}>
                <span className={`role-tag role-tag--${finding.role}`}>{finding.role.replace(/_/g, ' ')}</span>
                <span className="finding-item__main"><strong>{stageId}</strong>
                  <span>{finding.classification?.replace(/_/g, ' ') || 'Observation'}</span></span>
                <span className="finding-confidence">{finding.confidence || '—'}</span>
                {finding.link && <span className="finding-link">link: {finding.link}</span>}
              </button>
              {finding.caused_by.length > 0 && <p className="finding-causes">Caused by {finding.caused_by.join(', ')}</p>}
            </li>
          })}
        </ol>
      )}
    </section>
  )
}

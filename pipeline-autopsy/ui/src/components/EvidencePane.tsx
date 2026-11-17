import { useEffect, useState } from 'react'
import { getArtifact } from '../api'
import type { ArtifactResponse, Finding, NormalizedSpan, Observation } from '../types'
import { findingNodeId } from './FindingsList'

function matchesStage(observation: Observation, stageId: string): boolean {
  if (!observation.stage) return false
  return observation.stage === stageId || observation.stage === stageId.split('@')[0]
}

export function EvidencePane({
  stageId, finding, observations, spans, evidenceLevel = 'E1',
}: {
  stageId: string | null
  finding?: Finding
  observations: Observation[]
  spans: NormalizedSpan[]
  evidenceLevel?: string
}) {
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null)
  const [artifact, setArtifact] = useState<ArtifactResponse | null>(null)
  const [artifactError, setArtifactError] = useState<string | null>(null)
  const [loadingArtifact, setLoadingArtifact] = useState(false)
  const stageObservations = stageId ? observations.filter((observation) =>
    (finding?.evidence.includes(observation.id) ?? false) || matchesStage(observation, stageId)) : []
  const span = selectedSpanId ? spans.find((item) => item.span_id === selectedSpanId) : undefined
  const artifactId = stageObservations.find((observation) => observation.artifact_id)?.artifact_id || null

  useEffect(() => {
    setSelectedSpanId(null)
    setArtifact(null)
    setArtifactError(null)
  }, [stageId])

  async function loadArtifact() {
    if (!artifactId) return
    setLoadingArtifact(true)
    setArtifactError(null)
    try {
      setArtifact(await getArtifact(artifactId))
    } catch (error) {
      setArtifactError(error instanceof Error ? error.message : 'Artifact content is unavailable')
    } finally {
      setLoadingArtifact(false)
    }
  }

  return (
    <section className="evidence-panel" aria-label="Evidence details">
      <div className="section-heading"><div><p className="eyebrow">EVIDENCE</p><h2>{stageId || 'Select a stage'}</h2></div></div>
      {!stageId ? <p className="muted panel-empty">Select a graph node or finding to inspect its evidence.</p> : <>
        {finding && <div className="selected-finding">
          <span className={`role-tag role-tag--${finding.role}`}>{finding.role.replace(/_/g, ' ')}</span>
          <strong>{finding.classification?.replace(/_/g, ' ')}</strong>
          <span>{finding.confidence || 'confidence unavailable'}</span>
          {finding.note && <p>{finding.note}</p>}
        </div>}
        <div className="observation-list">
          <h3>Observations <span className="muted">({stageObservations.length})</span></h3>
          {stageObservations.length === 0 ? <p className="muted">No observations are linked to this stage.</p> : stageObservations.map((observation) => (
            <button className={`observation-card observation-card--${observation.result}`} type="button"
              key={observation.id} onClick={() => setSelectedSpanId(observation.span_id)}>
              <span className="observation-card__top"><strong>{observation.code}</strong><span>{observation.result}</span></span>
              <span className="observation-card__detail">{observation.detail}</span>
              {observation.field && <span className="observation-field">field: {observation.field}</span>}
            </button>
          ))}
        </div>
        {artifactId && <div className="artifact-reference"><h3>Artifact</h3><code>{artifactId}</code>
          {evidenceLevel.toUpperCase() !== 'E2' ? <p className="muted">Content not shared ({evidenceLevel.toUpperCase()}).</p> : <>
            <button type="button" className="button button--quiet" onClick={() => void loadArtifact()} disabled={loadingArtifact}>
              {loadingArtifact ? 'Loading…' : 'View masked content'}
            </button>
            {artifactError && <p className="error-copy" role="alert">{artifactError}</p>}
            {artifact && <pre className="artifact-content">{JSON.stringify(artifact.content ?? artifact.content_b64 ?? 'Content masked', null, 2)}</pre>}
          </>}
        </div>}
        {span && <div className="span-details"><h3>Span details</h3><p><strong>{span.name}</strong> · {span.status}</p>
          {span.error_type && <p className="error-copy">{span.error_type} · {span.error_class || 'unclassified'}</p>}
          <details><summary>Attributes and events</summary><pre>{JSON.stringify({ attributes: span.attrs, events: span.events }, null, 2)}</pre></details>
        </div>}
        {finding?.caused_by.length ? <p className="caused-by">Caused by {finding.caused_by.join(', ')}</p> : null}
      </>}
    </section>
  )
}

export function findStageFinding(findings: Finding[], stageId: string): Finding | undefined {
  return findings.find((finding) => findingNodeId(finding) === stageId)
}

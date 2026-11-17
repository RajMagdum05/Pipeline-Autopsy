import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getDiagnosis, getExecution, getExecutionGraph, getExecutionSpans, getPipelines, requeueDiagnosis, submitFindingFeedback } from '../api'
import { EvidencePane, findStageFinding } from '../components/EvidencePane'
import { FindingsList } from '../components/FindingsList'
import { Graph } from '../components/Graph'
import type { DiagnosisResponse, ExecutionDetail, ExecutionGraph, NormalizedSpan, PipelineSummary } from '../types'

function verdictLabel(value: string | null | undefined): string {
  if (!value) return 'Diagnosis pending'
  return value.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatDuration(startedAt: string, endedAt: string | null): string {
  if (!endedAt) return 'In progress'
  const elapsed = new Date(endedAt).getTime() - new Date(startedAt).getTime()
  if (!Number.isFinite(elapsed) || elapsed < 0) return '—'
  return elapsed < 1000 ? `${elapsed} ms` : `${(elapsed / 1000).toFixed(2)} s`
}

function isDiagnosis(value: DiagnosisResponse | null): value is Exclude<DiagnosisResponse, { pending: true }> {
  return Boolean(value && !('pending' in value))
}

export function RunPage() {
  const { executionId = '' } = useParams()
  const [execution, setExecution] = useState<ExecutionDetail | null>(null)
  const [graph, setGraph] = useState<ExecutionGraph>({ nodes: [], edges: [] })
  const [spans, setSpans] = useState<NormalizedSpan[]>([])
  const [pipelines, setPipelines] = useState<PipelineSummary[]>([])
  const [diagnosis, setDiagnosis] = useState<DiagnosisResponse | null>(null)
  const [selectedStage, setSelectedStage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [requeueing, setRequeueing] = useState(false)

  const loadDiagnosis = useCallback(async () => {
    if (!executionId) return
    try {
      setDiagnosis(await getDiagnosis(executionId))
      setError(null)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not load diagnosis')
    }
  }, [executionId])

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setExecution(null)
    setDiagnosis(null)
    Promise.all([
      getExecution(executionId, controller.signal),
      getExecutionGraph(executionId, controller.signal),
      getExecutionSpans(executionId, controller.signal),
      getPipelines(controller.signal),
    ]).then(([detail, currentGraph, spanPage, pipelinePage]) => {
      setExecution(detail)
      setGraph(currentGraph)
      setSpans(spanPage.spans)
      setPipelines(pipelinePage.pipelines)
      const firstOrigin = currentGraph.nodes.find((node) => node.role === 'origin')
      setSelectedStage(firstOrigin?.id || currentGraph.nodes[0]?.id || null)
      void getDiagnosis(executionId, controller.signal).then(setDiagnosis).catch((requestError) => {
        if (requestError instanceof DOMException && requestError.name === 'AbortError') return
        setError(requestError instanceof Error ? requestError.message : 'Could not load diagnosis')
      })
    }).catch((requestError) => {
      if (requestError instanceof DOMException && requestError.name === 'AbortError') return
      setError(requestError instanceof Error ? requestError.message : 'Could not load run')
    }).finally(() => setLoading(false))
    return () => controller.abort()
  }, [executionId])

  useEffect(() => {
    if (!executionId || !execution || isDiagnosis(diagnosis)) return
    let active = true
    const poll = window.setInterval(() => {
      void getDiagnosis(executionId).then((value) => {
        if (active) setDiagnosis(value)
      }).catch((requestError) => {
        if (active) setError(requestError instanceof Error ? requestError.message : 'Could not load diagnosis')
      })
    }, 1500)
    return () => { active = false; window.clearInterval(poll) }
  }, [diagnosis, execution, executionId])

  const manifest = useMemo(() => pipelines.find((item) => item.pipeline === execution?.pipeline
    && item.version === execution?.version)?.manifest, [execution, pipelines])
  const stageOrder = Array.isArray(manifest?.stages)
    ? manifest.stages.map((stage) => (stage as { name?: string }).name).filter((name): name is string => Boolean(name))
    : []
  const evidenceLevel = (manifest?.evidence as { level?: string } | undefined)?.level || 'E1'
  const readyDiagnosis = isDiagnosis(diagnosis) ? diagnosis : null
  const selectedFinding = selectedStage && readyDiagnosis
    ? findStageFinding(readyDiagnosis.findings, selectedStage) : undefined
  const structuralWarnings = readyDiagnosis?.observations.filter((observation) => observation.family === 'structural') || []

  async function handleRequeue() {
    setRequeueing(true)
    setError(null)
    try {
      await requeueDiagnosis(executionId)
      setDiagnosis({ pending: true, status: 'queued' })
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not queue diagnosis')
    } finally {
      setRequeueing(false)
    }
  }

  async function handleFeedback(findingId: string, verdict: 'confirmed' | 'rejected', comment: string) {
    try {
      await submitFindingFeedback(findingId, verdict, comment)
      await loadDiagnosis()
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Could not save finding feedback')
    }
  }

  return (
    <main className="page run-page">
      <Link className="back-link" to="/">← All runs</Link>
      {loading && <div className="run-loading" role="status"><span className="spinner" />Loading run details…</div>}
      {error && <div className="error-banner" role="alert"><span>{error}</span><button className="button button--quiet" onClick={() => { setError(null); void loadDiagnosis() }} type="button">Retry</button></div>}
      {execution && <>
        <header className="run-header">
          <div className="run-identity"><p className="eyebrow">RUN INVESTIGATION</p>
            <h1>{execution.entity_id || 'Run'} <span className="muted">·</span> <code>{execution.id}</code></h1>
            <p className="muted">{execution.pipeline}@{execution.version} <span>·</span> Started {new Date(execution.started_at).toLocaleString()} <span>·</span> {formatDuration(execution.started_at, execution.ended_at)}</p>
          </div>
          <div className="run-actions">
            {execution.jaeger_url && <a className="button button--quiet" href={execution.jaeger_url} target="_blank" rel="noreferrer">Open in Jaeger ↗</a>}
            <button className="button" type="button" onClick={() => void handleRequeue()} disabled={requeueing || !readyDiagnosis}>
              {requeueing ? 'Queueing…' : 'Re-diagnose'}
            </button>
          </div>
        </header>

        <div className="verdict-strip">
          <span className={`badge badge--${readyDiagnosis?.verdict === 'NO_ISSUE_DETECTED' ? 'healthy' : readyDiagnosis ? 'root' : 'pending'}`}>{verdictLabel(readyDiagnosis?.verdict)}</span>
          <span className={`grade grade--${(readyDiagnosis?.trace_grade || 'pending').toLowerCase()}`} title="A: complete trace · B: some structural gaps · C: not enough evidence">{readyDiagnosis?.trace_grade || '—'}</span>
          <span className="muted">Trace grade <span className="grade-help" title="A = complete; B = partial instrumentation; C = insufficient evidence">ⓘ</span></span>
          <span className="run-status">Run status: <strong>{execution.status}</strong></span>
        </div>

        {!readyDiagnosis && diagnosis && 'pending' in diagnosis && diagnosis.status === 'unregistered' && <section className="state-card state-card--notice">
          <h2>Register a manifest to enable diagnosis</h2>
          <p>Autopsy received this run but has no matching pipeline manifest.</p>
          <code>autopsy register manifest.yaml --endpoint AUTOPSY_ENDPOINT --key AUTOPSY_API_KEY</code>
        </section>}
        {!readyDiagnosis && diagnosis && 'pending' in diagnosis && diagnosis.status !== 'unregistered' && <section className="state-card state-card--pending" role="status">
          <span className="spinner" /><div><h2>Waiting for the run to finish</h2><p>Diagnosis runs after the trace settles (default 5 seconds). This page checks for updates automatically.</p></div>
        </section>}
        {readyDiagnosis?.trace_grade === 'C' && <section className="state-card state-card--notice">
          <h2>Not enough evidence to diagnose</h2><p>Check the instrumentation and structural warnings for this run.</p>
          {structuralWarnings.length > 0 && <ul>{structuralWarnings.map((warning) => <li key={warning.id}>{warning.code}: {warning.detail}</li>)}</ul>}
        </section>}

        {readyDiagnosis && <>
          <section className="summary-card">
            <div className="summary-card__source">{readyDiagnosis.explanation?.source || 'template'} explanation</div>
            <p>{readyDiagnosis.explanation?.summary || 'Diagnosis is complete. Select a finding or graph stage to inspect its evidence.'}</p>
            {(readyDiagnosis.explanation?.narrative || []).length > 0 && <ul className="explanation-narrative">
              {readyDiagnosis.explanation?.narrative.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}
            </ul>}
            {(readyDiagnosis.explanation?.remediation || []).length > 0 && <div className="remediation-list">
              {readyDiagnosis.explanation?.remediation.map((item) => <article key={item.playbook_id || item.title}>
                <h3>{item.title}{item.pack && item.pack !== 'generic' ? ` · ${item.pack}` : ''}</h3><p>{item.body}</p>
              </article>)}
            </div>}
            {readyDiagnosis.findings.filter((finding) => finding.role === 'origin').map((finding) => (
              <button type="button" className="summary-origin" key={finding.id} onClick={() => setSelectedStage(finding.item_id ? `${finding.stage}@${finding.item_id}` : finding.stage)}>
                <span className="role-tag role-tag--origin">origin</span><strong>{finding.item_id ? `${finding.stage}@${finding.item_id}` : finding.stage}</strong>
                <span>{finding.classification?.replace(/_/g, ' ')}</span><span className="finding-confidence">{finding.confidence}</span>
              </button>
            ))}
          </section>

          <section className="graph-panel"><div className="section-heading"><div><p className="eyebrow">RECONSTRUCTED EXECUTION</p><h2>Lineage graph</h2></div>
            <div className="graph-legend"><span><i className="legend-line" />Data</span><span><i className="legend-line legend-line--control" />Control</span><span><i className="legend-dot" />Tainted</span></div>
          </div>
            <Graph graph={graph} manifestStageOrder={stageOrder} selectedNodeId={selectedStage} onSelect={(node) => setSelectedStage(node.id)} />
          </section>

          <div className="investigation-columns">
            <FindingsList findings={readyDiagnosis.findings} selectedStage={selectedStage} onSelect={setSelectedStage}
              onFeedback={handleFeedback} />
            <EvidencePane stageId={selectedStage} finding={selectedFinding} observations={readyDiagnosis.observations}
              spans={spans} evidenceLevel={evidenceLevel} />
          </div>
        </>}

        <details className="raw-details"><summary>Timeline and raw spans ({spans.length})</summary>
          <ol className="span-timeline">{spans.map((span) => <li key={span.span_id}><span>{span.name}</span><span>{span.start}</span><span>{span.status}</span></li>)}</ol>
          <p><Link to={`/v1/executions/${encodeURIComponent(execution.id)}/spans`} target="_blank">Open normalized spans JSON ↗</Link></p>
        </details>
      </>}
    </main>
  )
}

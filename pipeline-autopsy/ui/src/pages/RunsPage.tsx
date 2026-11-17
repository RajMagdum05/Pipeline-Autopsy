import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getExecutions, getPipelines } from '../api'
import type { Execution, PipelineSummary } from '../types'

type VerdictFilter = '' | 'ROOT_CAUSE_IDENTIFIED' | 'MULTIPLE_ROOT_CAUSES' | 'NO_ISSUE_DETECTED' | 'INSUFFICIENT_EVIDENCE'
type TimeFilter = '24h' | '7d' | 'all'

const PAGE_SIZE = 50

function verdictLabel(verdict: string | null): string {
  switch (verdict) {
    case 'ROOT_CAUSE_IDENTIFIED': return 'Root cause'
    case 'MULTIPLE_ROOT_CAUSES': return 'Multiple causes'
    case 'NO_ISSUE_DETECTED': return 'No issue'
    case 'INSUFFICIENT_EVIDENCE': return 'Insufficient evidence'
    default: return verdict ? verdict.replace(/_/g, ' ').toLowerCase() : 'Pending'
  }
}

function verdictClass(verdict: string | null): string {
  switch (verdict) {
    case 'ROOT_CAUSE_IDENTIFIED': return 'badge--root'
    case 'MULTIPLE_ROOT_CAUSES': return 'badge--multiple'
    case 'NO_ISSUE_DETECTED': return 'badge--healthy'
    case 'INSUFFICIENT_EVIDENCE': return 'badge--insufficient'
    default: return 'badge--pending'
  }
}

function displayTime(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString()
}

function displayDuration(durationMs: number | null): string {
  if (durationMs == null) return '—'
  if (durationMs < 1000) return `${durationMs} ms`
  return `${(durationMs / 1000).toFixed(durationMs >= 10_000 ? 1 : 2)} s`
}

function withinTimeRange(execution: Execution, filter: TimeFilter): boolean {
  if (filter === 'all') return true
  const started = new Date(execution.started_at).getTime()
  if (Number.isNaN(started)) return true
  const age = Date.now() - started
  return age <= (filter === '24h' ? 24 : 24 * 7) * 60 * 60 * 1000
}

export function RunsPage() {
  const [pipelines, setPipelines] = useState<PipelineSummary[]>([])
  const [runs, setRuns] = useState<Execution[]>([])
  const [pipeline, setPipeline] = useState('')
  const [verdict, setVerdict] = useState<VerdictFilter>('')
  const [timeRange, setTimeRange] = useState<TimeFilter>('all')
  const [entityId, setEntityId] = useState('')
  const [cursors, setCursors] = useState<Array<string | null>>([null])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshCount, setRefreshCount] = useState(0)
  const cursor = cursors[cursors.length - 1] ?? null

  useEffect(() => {
    const controller = new AbortController()
    getPipelines(controller.signal).then((response) => setPipelines(response.pipelines))
      .catch(() => setPipelines([]))
    return () => controller.abort()
  }, [])

  const loadRuns = useCallback(async (signal?: AbortSignal) => {
    setError(null)
    const params = new URLSearchParams({ limit: String(PAGE_SIZE) })
    if (pipeline) params.set('pipeline', pipeline)
    if (verdict) params.set('verdict', verdict)
    if (entityId.trim()) params.set('entity_id', entityId.trim())
    if (cursor) params.set('cursor', cursor)
    try {
      const page = await getExecutions(params, signal)
      setRuns(page.executions)
      setNextCursor(page.next_cursor)
      setRefreshCount((count) => count + 1)
    } catch (requestError) {
      if (requestError instanceof DOMException && requestError.name === 'AbortError') return
      setError(requestError instanceof Error ? requestError.message : 'Could not load executions')
    } finally {
      setLoading(false)
    }
  }, [cursor, entityId, pipeline, verdict])

  useEffect(() => {
    const controller = new AbortController()
    void loadRuns(controller.signal)
    const refresh = window.setInterval(() => void loadRuns(), 5000)
    return () => {
      controller.abort()
      window.clearInterval(refresh)
    }
  }, [loadRuns])

  useEffect(() => {
    setCursors([null])
  }, [pipeline, verdict, entityId])

  const visibleRuns = useMemo(() => runs.filter((run) => withinTimeRange(run, timeRange)), [runs, timeRange])

  function resetPagination() {
    setCursors([null])
  }

  return (
    <main className="page runs-page">
      <div className="page-heading">
        <div><p className="eyebrow">OBSERVABILITY</p><h1>Pipeline runs</h1>
          <p className="muted">Recent executions, outcomes, and diagnosed origins.</p></div>
        <button className="button button--quiet refresh-button" onClick={() => void loadRuns()} type="button">Refresh</button>
      </div>

      <section className="filters" aria-label="Run filters">
        <label>Pipeline
          <select value={pipeline} onChange={(event) => { setPipeline(event.target.value); resetPagination() }}>
            <option value="">All pipelines</option>
            {pipelines.map((item) => <option key={`${item.pipeline}@${item.version}`} value={item.pipeline}>{item.pipeline}</option>)}
          </select>
        </label>
        <label>Verdict
          <select value={verdict} onChange={(event) => { setVerdict(event.target.value as VerdictFilter); resetPagination() }}>
            <option value="">All verdicts</option>
            <option value="ROOT_CAUSE_IDENTIFIED">Root cause</option>
            <option value="MULTIPLE_ROOT_CAUSES">Multiple causes</option>
            <option value="NO_ISSUE_DETECTED">No issue</option>
            <option value="INSUFFICIENT_EVIDENCE">Insufficient evidence</option>
          </select>
        </label>
        <label>Time range
          <select value={timeRange} onChange={(event) => setTimeRange(event.target.value as TimeFilter)}>
            <option value="24h">Last 24 hours</option><option value="7d">Last 7 days</option><option value="all">All time</option>
          </select>
        </label>
        <label className="entity-filter">Entity ID
          <input value={entityId} onChange={(event) => { setEntityId(event.target.value); resetPagination() }} placeholder="Search entity" />
        </label>
      </section>

      {error && <div className="error-banner" role="alert"><span>Could not load runs: {error}</span>
        <button className="button button--quiet" onClick={() => void loadRuns()} type="button">Retry</button></div>}

      <section className="table-card" aria-label="Pipeline runs">
        <div className="table-meta"><span>{visibleRuns.length} runs on this page</span>
          <span className="muted">Auto-refreshes every 5 seconds</span></div>
        <div className="table-scroll">
          <table>
            <thead><tr><th>Time</th><th>Entity</th><th>Pipeline</th><th>Verdict</th><th>Grade</th><th>Origin stages</th><th>Run outcome</th><th>Duration</th></tr></thead>
            <tbody>
              {loading && runs.length === 0 && Array.from({ length: 5 }, (_, index) => <tr className="skeleton-row" key={`skeleton-${index}`} aria-hidden="true"><td colSpan={8}><span /></td></tr>)}
              {!loading && visibleRuns.map((run) => (
                <tr key={run.id}>
                  <td><Link className="run-time" to={`/runs/${encodeURIComponent(run.id)}`}>{displayTime(run.started_at)}</Link></td>
                  <td className="mono">{run.entity_id || '—'}</td>
                  <td><span className="pipeline-name">{run.pipeline}</span><span className="pipeline-version">@{run.version}</span></td>
                  <td><span className={`badge ${verdictClass(run.verdict)}`}>{verdictLabel(run.verdict)}</span></td>
                  <td><span className={`grade grade--${(run.grade || 'pending').toLowerCase()}`} title="Trace grade reflects instrumentation completeness">{run.grade || '—'}</span></td>
                  <td>{run.origin_stages.length ? run.origin_stages.map((stage) => <span className="origin-chip" key={stage}>{stage}</span>) : <span className="muted">—</span>}</td>
                  <td><span className={`outcome outcome--${(run.run_outcome || 'pending').toLowerCase()}`}>{run.run_outcome || 'pending'}</span></td>
                  <td>{displayDuration(run.duration_ms)}</td>
                </tr>
              ))}
              {!loading && visibleRuns.length === 0 && !error && <tr><td colSpan={8} className="empty-cell">
                <div className="empty-state"><div className="empty-icon" aria-hidden="true">↗</div><h2>No runs yet</h2>
                  <p>Send your first trace: see <Link to="/pipelines">Pipelines → integration snippet</Link>.</p>
                  <pre><code>OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:8080/v1/traces<br />OTEL_EXPORTER_OTLP_HEADERS=&quot;x-autopsy-api-key=YOUR_KEY&quot;</code></pre>
                </div>
              </td></tr>}
            </tbody>
          </table>
        </div>
        <footer className="pagination">
          <button className="button button--quiet" disabled={cursors.length <= 1} onClick={() => setCursors((values) => values.slice(0, -1))} type="button">Previous</button>
          <span>Page {cursors.length} <span className="sr-only">· refreshed {refreshCount} times</span></span>
          <button className="button button--quiet" disabled={!nextCursor} onClick={() => nextCursor && setCursors((values) => [...values, nextCursor])} type="button">Next</button>
        </footer>
      </section>
    </main>
  )
}

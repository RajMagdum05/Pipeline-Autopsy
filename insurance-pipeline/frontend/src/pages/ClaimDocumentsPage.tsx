import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { PROOF_DOCUMENT_TYPES } from '../types/claim'
import { Alert } from '../components/ui/Alert'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'

const TYPES = ['policy_document', ...PROOF_DOCUMENT_TYPES.map((label) => label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, ''))]
type DocumentStatus = {
  document_id: string
  declared_type: string
  detected_type: string | null
  detected_subtype: string | null
  status: string
  extraction_status: string
  extraction_subtype: string | null
  extracted_facts: { field_name: string; raw_value: string | null; normalized_value: string | null; field_status: string; evidence: { page_number: number; quote: string }[]; warning: string | null }[] | null
  extraction_warnings: string[]
  validation_reasons: string[]
  validation_issues: { code: string; severity: string; field_path?: string | null; message: string }[]
  version_number: number
}
type StatusResponse = { claim_id: string; documents: DocumentStatus[] }

const LABELS: Record<string, string> = {
  waiting_for_text_processing: 'Waiting for text processing',
  checking_document_type: 'Checking document type',
  extracting: 'Extracting',
  validating: 'Validating',
  complete: 'Extraction complete',
  content_mismatch: 'Document type mismatch',
  review_required: 'Review required',
  unreadable: 'Unreadable document',
  classification_failed: 'Classification failed',
  technical_failure: 'Technical failure',
  extraction_failed: 'Extraction failed',
  waiting_policy_completion: 'Waiting for policy completion',
}

function accessToken(claimId: string) {
  return sessionStorage.getItem(`claim-access:${claimId}`)
}

export function ClaimDocumentsPage() {
  const { claimId = '' } = useParams()
  const [data, setData] = useState<StatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [files, setFiles] = useState<Record<string, File | undefined>>({})
  const [types, setTypes] = useState<Record<string, string>>({})
  const token = accessToken(claimId)

  const load = useCallback(async () => {
    if (!token) { setError('This claim is not available in this browser session. Create or open it from the original intake session.'); return }
    const response = await fetch(`/api/v1/claims/${claimId}/documents/status`, { headers: { Authorization: `Bearer ${token}` } })
    const body = await response.json()
    if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : 'Document statuses could not be loaded.')
    setData(body)
    setError(null)
  }, [claimId, token])

  useEffect(() => { void load().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'Unable to load document statuses.')) }, [load])
  useEffect(() => {
    if (!busy) return
    const timer = window.setInterval(() => { void load().catch(() => undefined) }, 1000)
    return () => window.clearInterval(timer)
  }, [busy, load])

  async function processDocuments() {
    if (!token) return
    setBusy(true); setError(null)
    try {
      const response = await fetch(`/api/v1/claims/${claimId}/documents/process`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ config_version: 'document-extraction-v2' }),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : 'Document processing failed.')
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Document processing failed.') }
    finally { setBusy(false) }
  }

  async function replaceDocument(documentId: string) {
    const file = files[documentId]
    if (!file || !token) return
    setBusy(true); setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      form.append('document_type', types[documentId] || data?.documents.find((doc) => doc.document_id === documentId)?.declared_type || '')
      const response = await fetch(`/api/v1/claims/${claimId}/documents/${documentId}`, {
        method: 'PUT', headers: { Authorization: `Bearer ${token}` }, body: form,
      })
      const body = await response.json()
      if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : 'Document replacement failed.')
      setFiles((current) => ({ ...current, [documentId]: undefined }))
      await load()
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Document replacement failed.') }
    finally { setBusy(false) }
  }

  return <main className="app-shell">
    <header className="topbar"><Link className="brand" to="/" aria-label="Claims Desk home"><span className="brand__mark">C</span><span>Claims Desk</span></Link><span className="topbar__context">Document extraction</span></header>
    <div className="page-content">
      <Link to="/" className="back-link">← Back to dashboard</Link>
      <section className="page-heading"><div><p className="eyebrow">CLAIM DOCUMENTS</p><h1>Document extraction</h1><p className="page-description">Each document is classified, then its own text is extracted and validated. Unsupported or uncertain output is not shown as accepted information.</p></div></section>
      {error && <Alert tone="error">{error}</Alert>}
      {data && <>
        <div className="document-actions"><p className="page-description">Claim {data.claim_id}</p><Button type="button" disabled={busy} onClick={processDocuments}>{busy ? 'Processing documents…' : 'Process documents'}</Button></div>
        {(['policy_document', 'supporting'] as const).map((group) => <section key={group} className="extraction-section"><h2>{group === 'policy_document' ? 'Policy document' : 'Supporting documents'}</h2><div className="document-status-list">{data.documents.filter((doc) => group === 'policy_document' ? doc.declared_type === 'policy_document' : doc.declared_type !== 'policy_document').map((doc) => <Card key={doc.document_id} className="document-status-card">
          <div className="document-status-card__heading"><div><p className="eyebrow">DOCUMENT {doc.document_id.slice(0, 8)}</p><h2>{doc.declared_type.replace(/_/g, ' ')}</h2></div><span className={`ocr-status ocr-status--${doc.status}`}>{LABELS[doc.status] || LABELS.waiting_for_text_processing}</span></div>
          {doc.detected_type && <p className="ocr-meta">Detected: <strong>{doc.detected_type.replace(/_/g, ' ')}</strong>{doc.detected_subtype ? ` · ${doc.detected_subtype.replace(/_/g, ' ')}` : ''} · Version {doc.version_number}</p>}
          {doc.status === 'content_mismatch' && <Alert tone="error">Selected type: {doc.declared_type.replace(/_/g, ' ')}. Detected type: {doc.detected_type?.replace(/_/g, ' ') || 'unknown'}. Replace the file or explicitly correct its declared type; downstream extraction is stopped until this is resolved.</Alert>}
          {doc.status === 'review_required' && <Alert tone="info">{doc.extraction_status === 'review_required' ? 'Extraction did not pass application validation. Candidate facts are not shown as accepted information; review this document before continuing.' : 'Document type could not be confirmed safely. Replace or review this document before continuing.'}</Alert>}
          {doc.status === 'extraction_failed' && <Alert tone="error">Structured extraction did not produce a valid accepted result. Review the document or retry processing; candidate facts are not shown.</Alert>}
          {doc.status === 'waiting_policy_completion' && <Alert tone="info">Supporting document processing is blocked until the policy completes the required processing gates.</Alert>}
          {doc.status === 'review_required' && doc.validation_reasons.length > 0 && <ul className="validation-reasons">{doc.validation_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
          {(doc.status === 'review_required' || doc.status === 'extraction_failed') && doc.validation_issues?.length > 0 && <ul className="validation-reasons">{doc.validation_issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.field_path ? `${issue.field_path}: ` : ''}{issue.message}</li>)}</ul>}
          {doc.status === 'complete' && doc.extracted_facts && <div className="extracted-facts"><h3>Validated extracted information</h3>{doc.extraction_subtype && <p className="ocr-meta">Subtype: {doc.extraction_subtype}</p>}<dl>{doc.extracted_facts.map((fact, index) => <div className="extracted-fact" key={`${fact.field_name}-${index}`}><dt>{fact.field_name.replace(/_/g, ' ')}</dt><dd><span className={`fact-status fact-status--${fact.field_status}`}>{fact.field_status.replace(/_/g, ' ')}</span>{fact.raw_value && <p>{fact.raw_value}{fact.normalized_value && fact.normalized_value !== fact.raw_value ? ` · normalized: ${fact.normalized_value}` : ''}</p>}{fact.evidence.map((evidence, evidenceIndex) => <blockquote key={evidenceIndex}>Page {evidence.page_number}: “{evidence.quote}”</blockquote>)}{fact.warning && <small>{fact.warning}</small>}</dd></div>)}</dl>{doc.extraction_warnings.map((warning) => <p className="extraction-warning" key={warning}>{warning}</p>)}</div>}
          {doc.status === 'content_mismatch' && <div className="document-replace"><label className="field__label" htmlFor={`type-${doc.document_id}`}>Correct declared type</label><select className="control" id={`type-${doc.document_id}`} value={types[doc.document_id] || doc.declared_type} onChange={(event) => setTypes((current) => ({ ...current, [doc.document_id]: event.target.value }))}>{TYPES.map((type) => <option key={type} value={type}>{type.replace(/_/g, ' ')}</option>)}</select><label className="field__label" htmlFor={`file-${doc.document_id}`}>Replacement file</label><input id={`file-${doc.document_id}`} type="file" accept="application/pdf,image/jpeg,image/png,.pdf,.jpg,.jpeg,.png" disabled={busy} onChange={(event) => setFiles((current) => ({ ...current, [doc.document_id]: event.target.files?.[0] }))} /><Button type="button" disabled={busy || !files[doc.document_id]} onClick={() => void replaceDocument(doc.document_id)}>Replace document</Button></div>}
        </Card>)}</div></section>)}
      </>}
    </div>
  </main>
}

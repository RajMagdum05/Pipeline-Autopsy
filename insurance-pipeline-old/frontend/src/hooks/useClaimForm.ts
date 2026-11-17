import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { claimSchema, type ClaimFormValues } from '../schemas/claimSchema'

export interface OCRPageResult {
  page_number: number
  raw_text: string
  status: string
  extraction_method: string
}

export interface ProcessedDocumentResult {
  id: number
  document_type: string
  file_name: string
  ocr_status: string
  ocr_result: {
    status: string
    engine: string
    engine_version?: string | null
    processing_duration_ms?: number | null
    pages: OCRPageResult[]
    errors: string[]
  } | null
}

export interface ClaimProcessingResult {
  claim_id: string
  legacy_id: number
  claim_status: string
  documents: ProcessedDocumentResult[]
}

function apiError(response: Response, payload: unknown): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return `Request failed (${response.status}).`
}

export function prepareClaimSubmission(values: ClaimFormValues): FormData {
  const formData = new FormData()
  formData.append('policyholder_name', values.policyholderName)
  formData.append('age', String(values.age))
  formData.append('policy_number', values.policyNumber)
  formData.append('incident_date', values.incidentDate)
  formData.append('description', values.description)
  formData.append('claimed_amount', String(values.claimedAmount))
  formData.append('policy_document', values.policyPaper)
  formData.append('document_1_type', values.proofDocumentType.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, ''))
  formData.append('document_1', values.proofDocument)
  return formData
}

export function useClaimForm() {
  const [result, setResult] = useState<ClaimProcessingResult | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const form = useForm<ClaimFormValues>({
    resolver: zodResolver(claimSchema),
    mode: 'onChange',
    defaultValues: {
      policyholderName: '',
      age: undefined,
      policyNumber: '',
      incidentDate: '',
      description: '',
      claimedAmount: undefined,
      proofDocumentType: undefined,
      policyPaper: undefined,
      proofDocument: undefined,
    },
  })

  async function submitClaim(values: ClaimFormValues) {
    setResult(null)
    setSubmitError(null)
    const preparedFormData = prepareClaimSubmission(values)
    try {
      const createdResponse = await fetch('/api/v1/claims', { method: 'POST', body: preparedFormData })
      const created = await createdResponse.json()
      if (!createdResponse.ok) throw new Error(apiError(createdResponse, created))

      const documentsResponse = await fetch(`/legacy-api/${created.legacy_id}/documents`)
      const documents = await documentsResponse.json()
      if (!documentsResponse.ok) throw new Error(apiError(documentsResponse, documents))
      setResult({
        claim_id: created.claim_id,
        legacy_id: created.legacy_id,
        claim_status: created.claim_status,
        documents,
      })
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'The claim could not be processed.')
    }
  }

  return { ...form, result, submitError, submitClaim }
}

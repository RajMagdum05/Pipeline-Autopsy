import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { claimSchema, type ClaimFormValues } from '../schemas/claimSchema'

export interface ClaimIntakeResult {
  claim_id: string
  legacy_id: number
  claim_status: string
  document_ids: string[]
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
  const [result, setResult] = useState<ClaimIntakeResult | null>(null)
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

      setResult({
        claim_id: created.claim_id,
        legacy_id: created.legacy_id,
        claim_status: created.claim_status,
        document_ids: created.document_ids,
      })
      if (typeof created.claim_access_token === 'string') {
        sessionStorage.setItem(`claim-access:${created.claim_id}`, created.claim_access_token)
      }
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'The claim could not be processed.')
    }
  }

  return { ...form, result, submitError, submitClaim }
}

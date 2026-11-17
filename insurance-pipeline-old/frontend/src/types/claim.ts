export const PROOF_DOCUMENT_TYPES = [
  'Hospital Bill',
  'FIR / Accident Report',
  'Medical Report',
  'Discharge Summary',
  'Repair Estimate',
  'Other Supporting Document',
] as const

export type ProofDocumentType = (typeof PROOF_DOCUMENT_TYPES)[number]

export interface ClaimSubmission {
  policyholderName: string
  age: number
  policyNumber: string
  incidentDate: string
  description: string
  claimedAmount: number
  policyPaper: File
  proofDocumentType: ProofDocumentType
  proofDocument: File
}

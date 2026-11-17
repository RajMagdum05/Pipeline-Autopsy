import { z } from 'zod'
import { PROOF_DOCUMENT_TYPES } from '../types/claim'

const MAX_FILE_SIZE = 10 * 1024 * 1024
const PDF_MIME = 'application/pdf'
const PROOF_MIME_TYPES = [PDF_MIME, 'image/jpeg', 'image/png']

const requiredFile = (message: string) =>
  z.custom<File>((value) => typeof File !== 'undefined' && value instanceof File, message)

const today = () => {
  const date = new Date()
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 10)
}

export const claimSchema = z.object({
  policyholderName: z.string().trim().min(1, 'Enter the policyholder name.'),
  age: z.number({ error: 'Enter an age.' }).min(0, 'Age must be between 0 and 120.').max(120, 'Age must be between 0 and 120.'),
  policyNumber: z.string().trim().min(1, 'Enter the policy number.'),
  incidentDate: z.string().min(1, 'Select the incident or diagnosis date.').refine((value) => value <= today(), 'Date cannot be in the future.'),
  description: z.string().trim().min(10, 'Describe what happened in at least 10 characters.'),
  claimedAmount: z.number({ error: 'Enter the claimed amount.' }).gt(0, 'Claimed amount must be greater than ₹0.'),
  policyPaper: requiredFile('Upload the insurance policy paper.')
    .refine((file) => file.type === PDF_MIME, 'Policy paper must be a PDF.')
    .refine((file) => file.size <= MAX_FILE_SIZE, 'Policy paper must be 10 MB or smaller.'),
  proofDocumentType: z.enum(PROOF_DOCUMENT_TYPES, { error: 'Select a proof document type.' }),
  proofDocument: requiredFile('Upload a proof document.')
    .refine((file) => PROOF_MIME_TYPES.includes(file.type), 'Proof document must be a PDF, JPG, or PNG.')
    .refine((file) => file.size <= MAX_FILE_SIZE, 'Proof document must be 10 MB or smaller.'),
})

export type ClaimFormValues = z.infer<typeof claimSchema>

import { Controller } from 'react-hook-form'
import { Link } from 'react-router-dom'
import { PROOF_DOCUMENT_TYPES } from '../../types/claim'
import { useClaimForm } from '../../hooks/useClaimForm'
import { Alert } from '../ui/Alert'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { FileUpload } from '../ui/FileUpload'
import { Input } from '../ui/Input'
import { Select } from '../ui/Select'

export function ClaimForm() {
  const { register, control, handleSubmit, formState: { errors, isValid, isSubmitting }, result, submitError, submitClaim } = useClaimForm()

  return (
    <>
      {submitError && <Alert tone="error">{submitError}</Alert>}
      {result && <Card className="processing-result">
        <div className="processing-result__heading">
          <div><p className="eyebrow">CLAIM INTAKE</p><h2>Claim received</h2><p>Claim {result.claim_id} · record #{result.legacy_id}</p></div>
          <span className="step-pill"><span /> {result.claim_status}</span>
        </div>
        <p className="ocr-meta">{result.document_ids.length} document(s) saved. Document IDs: {result.document_ids.join(', ')}</p>
        <Link className="text-link" to={`/claims/${result.claim_id}`}>Check each document type and status →</Link>
      </Card>}
      <form onSubmit={handleSubmit(submitClaim)} noValidate autoComplete="off">
        <Card className="form-card">
          <div className="form-section">
            <div className="form-section__heading">
              <span className="section-number">01</span>
              <div><h2>Claim information</h2><p>Enter the policyholder and incident details.</p></div>
            </div>
            <div className="form-grid">
              <Input id="policyholderName" label="Policyholder Name" autoComplete="name" placeholder="Full name" error={errors.policyholderName?.message} {...register('policyholderName')} />
              <Input id="age" label="Age" type="number" min="0" max="120" step="1" placeholder="e.g. 42" error={errors.age?.message} {...register('age', { setValueAs: (value: string) => value === '' ? undefined : Number(value) })} />
              <Input id="policyNumber" label="Policy Number" placeholder="Enter policy number" error={errors.policyNumber?.message} {...register('policyNumber')} />
              <Input id="incidentDate" label="Date of Incident / Diagnosis" type="date" max={new Date(Date.now() - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 10)} error={errors.incidentDate?.message} {...register('incidentDate')} />
              <div className="form-grid__wide">
                <label className="field__label" htmlFor="description">What happened?<span aria-hidden="true"> *</span></label>
                <textarea id="description" className={`control control--textarea${errors.description ? ' control--error' : ''}`} rows={4} placeholder="Briefly describe the incident or diagnosis (at least 10 characters)" aria-invalid={Boolean(errors.description)} aria-describedby={errors.description ? 'description-error' : undefined} {...register('description')} />
                {errors.description && <p className="field__error" id="description-error">{errors.description.message}</p>}
              </div>
              <Input id="claimedAmount" label="Claimed Amount (₹)" type="number" min="0.01" step="0.01" placeholder="e.g. 25000" error={errors.claimedAmount?.message} {...register('claimedAmount', { setValueAs: (value: string) => value === '' ? undefined : Number(value) })} />
            </div>
          </div>

          <div className="form-section form-section--documents">
            <div className="form-section__heading">
              <span className="section-number">02</span>
              <div><h2>Supporting documents</h2><p>PDF, JPG, or PNG files up to 10 MB each where accepted.</p></div>
            </div>
            <div className="form-grid">
              <Controller name="policyPaper" control={control} render={({ field }) => <FileUpload label="Upload Insurance Policy Paper" accept="application/pdf,.pdf" hint="PDF only · Maximum 10 MB" file={field.value} error={errors.policyPaper?.message} disabled={isSubmitting} onChange={field.onChange} />} />
              <Controller name="proofDocumentType" control={control} render={({ field }) => <Select id="proofDocumentType" label="Select Proof Document Type" options={PROOF_DOCUMENT_TYPES} value={field.value ?? ''} onChange={field.onChange} onBlur={field.onBlur} name={field.name} ref={field.ref} error={errors.proofDocumentType?.message} />} />
              <Controller name="proofDocument" control={control} render={({ field }) => <FileUpload label="Upload Proof Document" accept="application/pdf,.pdf,image/jpeg,.jpg,.jpeg,image/png,.png" hint="PDF, JPG, or PNG · Maximum 10 MB" file={field.value} error={errors.proofDocument?.message} disabled={isSubmitting} onChange={field.onChange} />} />
            </div>
          </div>

          <div className="form-actions">
            <p><span aria-hidden="true">*</span> Required fields</p>
            <Button type="submit" disabled={!isValid || isSubmitting}>
              {isSubmitting ? <><span className="spinner" aria-hidden="true" /> Saving claim and documents…</> : 'Submit Claim'}
            </Button>
          </div>
        </Card>
      </form>
    </>
  )
}

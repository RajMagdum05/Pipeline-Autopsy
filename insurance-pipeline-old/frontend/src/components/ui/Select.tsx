import { forwardRef, type SelectHTMLAttributes } from 'react'

type Props = SelectHTMLAttributes<HTMLSelectElement> & { label: string; error?: string; options: readonly string[] }

export const Select = forwardRef<HTMLSelectElement, Props>(function Select({ label, error, options, id, ...props }, ref) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>{label}<span aria-hidden="true"> *</span></label>
      <select ref={ref} className={`control${error ? ' control--error' : ''}`} id={id} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : undefined} {...props}>
        <option value="">Select a document type</option>
        {options.map((option) => <option value={option} key={option}>{option}</option>)}
      </select>
      {error && <p className="field__error" id={`${id}-error`}>{error}</p>}
    </div>
  )
})

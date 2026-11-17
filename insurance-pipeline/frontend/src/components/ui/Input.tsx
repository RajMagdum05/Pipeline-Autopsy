import type { InputHTMLAttributes } from 'react'

type Props = InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: string }

export function Input({ label, error, hint, id, ...props }: Props) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>{label}<span aria-hidden="true"> *</span></label>
      <input className={`control${error ? ' control--error' : ''}`} id={id} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined} {...props} />
      {hint && !error && <p className="field__hint" id={`${id}-hint`}>{hint}</p>}
      {error && <p className="field__error" id={`${id}-error`}>{error}</p>}
    </div>
  )
}

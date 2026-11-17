import { useId } from 'react'
import { formatFileSize } from '../../utils/validation'

interface Props {
  label: string
  accept: string
  hint: string
  file?: File
  error?: string
  disabled?: boolean
  onChange: (file?: File) => void
}

export function FileUpload({ label, accept, hint, file, error, disabled, onChange }: Props) {
  const id = useId()
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>{label}<span aria-hidden="true"> *</span></label>
      <div className={`file-picker${error ? ' file-picker--error' : ''}`}>
        <input id={id} type="file" accept={accept} disabled={disabled} onChange={(event) => onChange(event.target.files?.[0])} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : `${id}-hint`} />
        <span className="file-picker__button">Choose file</span>
        <span className="file-picker__name">{file ? file.name : 'No file selected'}</span>
      </div>
      {file && <p className="field__hint">{formatFileSize(file.size)}</p>}
      {!file && <p className="field__hint" id={`${id}-hint`}>{hint}</p>}
      {error && <p className="field__error" id={`${id}-error`}>{error}</p>}
    </div>
  )
}

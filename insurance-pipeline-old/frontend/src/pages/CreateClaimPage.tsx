import { Link } from 'react-router-dom'
import { ClaimForm } from '../components/claims/ClaimForm'

export function CreateClaimPage() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/" aria-label="Claims Desk home"><span className="brand__mark">C</span><span>Claims Desk</span></Link>
        <span className="topbar__context">Stage 1 · Claim intake</span>
      </header>
      <div className="page-content page-content--form">
        <Link to="/" className="back-link"><span aria-hidden="true">←</span> Back to dashboard</Link>
        <section className="page-heading">
          <div><p className="eyebrow">NEW CLAIM</p><h1>Claim details</h1><p className="page-description">Provide the information below and attach the required documents.</p></div>
          <span className="step-pill"><span /> Claim intake</span>
        </section>
        <ClaimForm />
        <footer className="form-footer">Documents are uploaded for claim intake and OCR processing.</footer>
      </div>
    </main>
  )
}

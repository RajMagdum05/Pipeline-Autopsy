import { Link } from 'react-router-dom'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'

export function DashboardPage() {
  return (
    <main className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/" aria-label="Claims Desk home"><span className="brand__mark">C</span><span>Claims Desk</span></Link>
        <span className="topbar__context">Insurance claim intake</span>
      </header>
      <div className="page-content">
        <section className="page-heading page-heading--dashboard">
          <div><p className="eyebrow">YOUR WORKSPACE</p><h1>Claims dashboard</h1><p className="page-description">Start a claim and provide its supporting documents.</p></div>
          <Link to="/claims/new"><Button>Create New Claim</Button></Link>
        </section>
        <Card className="empty-state">
          <div className="empty-state__icon" aria-hidden="true">＋</div>
          <h2>Your claims will appear here</h2>
          <p>There are no claims in this new workspace yet. Start by creating a claim.</p>
          <Link to="/claims/new" className="text-link">Create your first claim <span aria-hidden="true">→</span></Link>
        </Card>
        <p className="dashboard-note">Claims list connection will be added in a later step.</p>
      </div>
    </main>
  )
}

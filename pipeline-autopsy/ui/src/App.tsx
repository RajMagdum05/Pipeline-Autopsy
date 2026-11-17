import { useState, type FormEvent } from 'react'
import { BrowserRouter, Link, NavLink, Route, Routes } from 'react-router-dom'
import { configuredApiKey, saveApiKey } from './api'
import { RunPage } from './pages/RunPage'
import { RunsPage } from './pages/RunsPage'

function ApiKeyControl() {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const [configured, setConfigured] = useState(Boolean(configuredApiKey()))

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveApiKey(value)
    setConfigured(Boolean(value.trim()))
    setValue('')
    setOpen(false)
    window.dispatchEvent(new Event('autopsy-key-changed'))
  }

  return (
    <div className="key-control">
      <button className="key-status" onClick={() => setOpen((current) => !current)} type="button">
        <span className={configured ? 'status-dot status-dot--good' : 'status-dot'} aria-hidden="true" />
        {configured ? 'API key configured' : 'API key needed'}
      </button>
      {open && (
        <form className="key-form" onSubmit={submit}>
          <label htmlFor="api-key">Local Autopsy API key</label>
          <input id="api-key" type="password" autoComplete="off" value={value}
            onChange={(event) => setValue(event.target.value)} placeholder="Paste local key" />
          <div className="key-form__actions">
            <button type="button" className="button button--quiet" onClick={() => setOpen(false)}>Cancel</button>
            <button type="submit" className="button">Save key</button>
          </div>
        </form>
      )}
    </div>
  )
}

function AppRoutes() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">Pipeline <strong>Autopsy</strong></Link>
        <nav className="main-nav" aria-label="Main navigation">
          <NavLink to="/" end>Runs</NavLink>
          <NavLink to="/pipelines">Pipelines</NavLink>
        </nav>
        <ApiKeyControl />
      </header>
      <Routes>
        <Route path="/" element={<RunsPage />} />
        <Route path="/runs/:executionId" element={<RunPage />} />
        <Route path="/pipelines" element={<main className="page"><p className="eyebrow">PIPELINES</p><h1>Pipeline registry</h1><p className="muted">Pipeline onboarding details will appear here.</p></main>} />
        <Route path="*" element={<RunsPage />} />
      </Routes>
    </div>
  )
}

export function App() {
  return <BrowserRouter basename="/ui"><AppRoutes /></BrowserRouter>
}

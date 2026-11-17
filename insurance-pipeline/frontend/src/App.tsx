import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { DashboardPage } from './pages/DashboardPage'
import { CreateClaimPage } from './pages/CreateClaimPage'
import { ClaimDocumentsPage } from './pages/ClaimDocumentsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/claims/new" element={<CreateClaimPage />} />
        <Route path="/claims/:claimId" element={<ClaimDocumentsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

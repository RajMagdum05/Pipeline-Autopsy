import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ClaimsPage } from './pages/ClaimsPage';
import { CreateClaimPage } from './pages/CreateClaimPage';
import { ClaimDetailPage } from './pages/ClaimDetailPage';
import { ClaimsProvider } from './context/ClaimsContext';

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <ClaimsProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<Navigate to="/claims" replace />} />
            <Route path="/claims" element={<ClaimsPage />} />
            <Route path="/claims/new" element={<CreateClaimPage />} />
            <Route path="/claims/:id" element={<ClaimDetailPage />} />
            <Route path="*" element={<Navigate to="/claims" replace />} />
          </Routes>
        </Layout>
      </ClaimsProvider>
    </BrowserRouter>
  );
};

export default App;

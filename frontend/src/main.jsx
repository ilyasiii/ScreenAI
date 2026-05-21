import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import './index.css'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import { ProfileProvider, useProfile } from './contexts/ProfileContext'
import ProfileModal from './components/ProfileModal.jsx'
import App from './App.jsx'
import LandingPage from './pages/LandingPage.jsx'
import AuthPage from './pages/AuthPage.jsx'
import ResetPasswordPage from './pages/ResetPasswordPage.jsx'
import HistoryPage from './pages/HistoryPage.jsx'
import InterviewPage from './pages/InterviewPage.jsx'

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  const { onboarded } = useProfile();
  if (loading) return null;
  if (!user) return <Navigate to="/auth" replace />;
  if (!onboarded) return <ProfileModal />;
  return children;
}

function PublicOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/app" replace />;
  return children;
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <ProfileProvider>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/auth" element={<PublicOnly><AuthPage /></PublicOnly>} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/app" element={<ProtectedRoute><App /></ProtectedRoute>} />
            <Route path="/interview" element={<ProtectedRoute><InterviewPage /></ProtectedRoute>} />
            <Route path="/history" element={<ProtectedRoute><HistoryPage /></ProtectedRoute>} />
          </Routes>
        </ProfileProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)

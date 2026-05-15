import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/auth'
import Layout from '@/components/Layout'
import ProtectedRoute from '@/components/ProtectedRoute'
import LoginPage from '@/pages/LoginPage'
import NodeDashboard from '@/pages/NodeDashboard'
import PlaybookEditor from '@/pages/PlaybookEditor'
import ExclusiveGroups from '@/pages/ExclusiveGroups'
import JobMonitor from '@/pages/JobMonitor'

export default function App() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={isAuthenticated() ? <Navigate to="/" replace /> : <LoginPage />}
        />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/nodes" replace />} />
          <Route path="nodes" element={<NodeDashboard />} />
          <Route path="playbooks" element={<PlaybookEditor />} />
          <Route path="groups" element={<ExclusiveGroups />} />
          <Route path="jobs" element={<JobMonitor />} />
          <Route path="jobs/:jobId" element={<JobMonitor />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

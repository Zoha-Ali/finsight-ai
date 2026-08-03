// Design direction
// -----------------
// FinSight AI is a personal finance tool, not a generic AI-startup demo -
// it should read as grounded and bank-adjacent, not trendy. Deliberately
// avoiding the current AI-app defaults: no cream+terracotta editorial
// look, no dark mode with a neon accent.
//
// Palette: a single deep navy (#1D3557) as the primary/action color - the
// kind of blue real banking products use, not a gradient or a "brand"
// purple. A cool near-white surface (#F6F7F9) instead of stark white or
// warm cream. A muted teal-green for calm/positive state, and a
// controlled red (not orange/terracotta) reserved specifically for
// anomalies, so it stays meaningful instead of decorative.
//
// Type pairing: IBM Plex Sans throughout for a legible, engineered feel,
// with IBM Plex Mono + tabular-nums for money figures specifically, so
// digit columns line up the way they would in an actual statement.

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ProtectedRoute from '@/components/ProtectedRoute'
import Layout from '@/components/Layout'
import LoginPage from '@/routes/LoginPage'
import DashboardPage from '@/routes/DashboardPage'
import ForecastPage from '@/routes/ForecastPage'
import ReceiptsPage from '@/routes/ReceiptsPage'
import ChatPage from '@/routes/ChatPage'
import { isAuthenticated } from '@/lib/auth'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/forecast" element={<ForecastPage />} />
            <Route path="/receipts" element={<ReceiptsPage />} />
            <Route path="/chat" element={<ChatPage />} />
          </Route>
        </Route>

        <Route
          path="/"
          element={<Navigate to={isAuthenticated() ? '/dashboard' : '/login'} replace />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App

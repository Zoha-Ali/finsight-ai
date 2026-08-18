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

import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import ProtectedRoute from '@/components/ProtectedRoute'
import Layout from '@/components/Layout'
import { isAuthenticated } from '@/lib/auth'

// Route-level code splitting: each page's code (and anything it alone
// depends on, e.g. ForecastPage's react-markdown) only downloads when a
// user actually navigates there, instead of every route's code loading
// upfront on first paint regardless of which page - or whether the user
// is even authenticated yet - they land on.
const LoginPage = lazy(() => import('@/routes/LoginPage'))
const DashboardPage = lazy(() => import('@/routes/DashboardPage'))
const ForecastPage = lazy(() => import('@/routes/ForecastPage'))
const ChatPage = lazy(() => import('@/routes/ChatPage'))

// Matches the plain, muted "Loading…" text already used in-page
// throughout the app (DashboardPage, ForecastPage) rather than
// introducing a new spinner/skeleton style just for this.
function RouteFallback() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <p className="text-sm text-ink-muted">Loading…</p>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          <Route element={<ProtectedRoute />}>
            <Route element={<Layout />}>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/forecast" element={<ForecastPage />} />
              <Route path="/chat" element={<ChatPage />} />
            </Route>
          </Route>

          <Route
            path="/"
            element={<Navigate to={isAuthenticated() ? '/dashboard' : '/login'} replace />}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}

export default App

import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '@/lib/api'
import { clearTokens } from '@/lib/auth'

export default function Layout() {
  const navigate = useNavigate()

  async function handleLogout() {
    try {
      // Invalidates every outstanding token server-side (see POST
      // /auth/logout), not just this browser's copy - without this call,
      // a stolen token would stay valid until it naturally expired.
      await api.post('/auth/logout')
    } catch (err) {
      // A network failure (or a token that was already invalid) shouldn't
      // trap the user on a broken logout button - they must still be able
      // to leave this device's session locally even if the server round
      // trip fails, so this is reported rather than blocking anything.
      console.error('Logout request failed; clearing local session anyway.', err)
    } finally {
      clearTokens()
      navigate('/login', { replace: true })
    }
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-2 text-sm font-medium rounded-md transition-colors ${
      isActive ? 'bg-primary text-white' : 'text-ink-muted hover:text-ink hover:bg-surface'
    }`

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border bg-surface-card">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
          <span className="text-lg font-semibold text-primary">FinSight AI</span>
          <nav className="flex items-center gap-2">
            <NavLink to="/dashboard" className={linkClass}>
              Dashboard
            </NavLink>
            <NavLink to="/forecast" className={linkClass}>
              Forecast
            </NavLink>
            <NavLink to="/chat" className={linkClass}>
              Chat
            </NavLink>
            <button
              type="button"
              onClick={handleLogout}
              className="ml-2 px-3 py-2 text-sm font-medium text-ink-muted hover:text-danger transition-colors"
            >
              Log out
            </button>
          </nav>
        </div>
      </header>
      <main className="flex-1">
        <div className="max-w-5xl mx-auto px-6 py-8 w-full">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

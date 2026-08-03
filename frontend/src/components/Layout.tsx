import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { clearTokens } from '@/lib/auth'

export default function Layout() {
  const navigate = useNavigate()

  function handleLogout() {
    clearTokens()
    navigate('/login', { replace: true })
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

import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { Server, BookOpen, Activity, LogOut } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/auth'
import { logout } from '@/api/auth'

const navItems = [
  { to: '/nodes', label: 'Nodes', icon: Server },
  { to: '/playbooks', label: 'Playbooks', icon: BookOpen },
  { to: '/jobs', label: 'Jobs', icon: Activity },
]

export default function Layout() {
  const { setUser, user } = useAuthStore()
  const navigate = useNavigate()

  async function handleLogout() {
    try {
      await logout()
    } finally {
      setUser(null)
      navigate('/login')
    }
  }

  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 border-r border-border flex flex-col">
        <div className="px-4 py-5 border-b border-border">
          <span className="font-bold text-lg tracking-tight">Minerva</span>
        </div>
        <nav className="flex-1 py-4 px-2 space-y-1">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-4 border-t border-border">
          <div className="text-xs text-muted-foreground mb-2 truncate">{user?.username}</div>
          <button
            onClick={handleLogout}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}

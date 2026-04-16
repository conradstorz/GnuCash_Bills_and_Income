import { NavLink } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import api from '../api/client'

interface Status {
  queued_bills: number
  vendor_sync: { needs_sync: boolean }
}

function useSidebarStatus() {
  return useQuery<Status>({
    queryKey: ['status'],
    queryFn: () => api.get<Status>('/status').then(r => r.data),
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
}

export default function Sidebar() {
  const { data: status } = useSidebarStatus()

  const badges: Record<string, React.ReactNode> = {
    '/bills': status?.queued_bills
      ? <span className="ml-auto bg-amber-500 text-white text-xs font-semibold rounded-full px-1.5 py-0.5 leading-none">{status.queued_bills}</span>
      : null,
    '/vendors': status?.vendor_sync.needs_sync
      ? <span className="ml-auto bg-red-500 text-white text-xs font-semibold rounded-full px-1.5 py-0.5 leading-none">!</span>
      : null,
  }

  return (
    <aside className="w-48 min-h-screen bg-slate-900 text-slate-300 flex flex-col">
      <div className="p-4 font-semibold text-white text-sm border-b border-slate-700">
        GnuCash Bills
      </div>
      <nav className="flex flex-col gap-1 p-2 flex-1">
        {[
          { to: '/bills', label: 'Bills Queue' },
          { to: '/cash', label: 'Cash Entry' },
          { to: '/vendors', label: 'Vendors' },
          { to: '/settings', label: 'Settings' },
        ].map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex items-center px-3 py-2 rounded text-sm transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'hover:bg-slate-700 hover:text-white'
              }`
            }
          >
            {label}
            {badges[to] ?? null}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}

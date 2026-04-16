import { NavLink } from 'react-router-dom'

const links = [
  { to: '/bills', label: 'Bills Queue' },
  { to: '/cash', label: 'Cash Entry' },
  { to: '/vendors', label: 'Vendors' },
  { to: '/settings', label: 'Settings' },
]

export default function Sidebar() {
  return (
    <aside className="w-48 min-h-screen bg-slate-900 text-slate-300 flex flex-col">
      <div className="p-4 font-semibold text-white text-sm border-b border-slate-700">
        GnuCash Bills
      </div>
      <nav className="flex flex-col gap-1 p-2 flex-1">
        {links.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `px-3 py-2 rounded text-sm transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'hover:bg-slate-700 hover:text-white'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}

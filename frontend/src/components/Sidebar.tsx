import { useState, useEffect } from 'react'
import type { ReactNode } from 'react'
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
  const [showConfirm, setShowConfirm] = useState(false)
  const [isShuttingDown, setIsShuttingDown] = useState(false)

  const badges: Record<string, ReactNode> = {
    '/bills': status?.queued_bills
      ? <span className="ml-auto bg-amber-500 text-white text-xs font-semibold rounded-full px-1.5 py-0.5 leading-none">{status.queued_bills}</span>
      : null,
    '/vendors': status?.vendor_sync.needs_sync
      ? <span className="ml-auto bg-red-500 text-white text-xs font-semibold rounded-full px-1.5 py-0.5 leading-none">!</span>
      : null,
  }

  async function handleShutdown() {
    setIsShuttingDown(true)
    try {
      await api.post('/shutdown')
    } catch {
      // Server may close before the response arrives — that's expected
    }
    setShowConfirm(false)
    window.close()
  }

  useEffect(() => {
    if (!showConfirm) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !isShuttingDown) setShowConfirm(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [showConfirm, isShuttingDown])

  return (
    <>
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
        <div className="p-2 border-t border-slate-700">
          <button
            onClick={() => setShowConfirm(true)}
            className="w-full flex items-center px-3 py-2 rounded text-sm text-red-400 hover:bg-red-900/40 hover:text-red-300 transition-colors"
          >
            Shut Down
          </button>
        </div>
      </aside>

      {showConfirm && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
          onClick={() => { if (!isShuttingDown) setShowConfirm(false) }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="shutdown-dialog-title"
            className="bg-slate-800 rounded-lg p-6 w-80 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="shutdown-dialog-title" className="text-white font-semibold text-base mb-1">Shut down server?</h2>
            <p className="text-slate-400 text-sm mb-5">This will stop the server and close this tab.</p>
            <div className="flex gap-3 justify-end">
              <button
                autoFocus
                onClick={() => setShowConfirm(false)}
                disabled={isShuttingDown}
                className="px-4 py-2 rounded text-sm text-slate-300 hover:bg-slate-700 disabled:opacity-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleShutdown}
                disabled={isShuttingDown}
                className="px-4 py-2 rounded text-sm bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {isShuttingDown ? 'Shutting down…' : 'Shut Down'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

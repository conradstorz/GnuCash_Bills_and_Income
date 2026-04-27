# Shutdown Button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Shut Down" button to the sidebar that stops the uvicorn server via the existing `/api/shutdown` endpoint and attempts to close the browser tab, gated by a styled React confirmation modal.

**Architecture:** All changes are in a single frontend component (`Sidebar.tsx`). Two boolean state variables (`showConfirm`, `isShuttingDown`) control visibility and loading state. The modal renders as a portal-like fixed overlay outside the `<aside>` by wrapping the return in a React fragment. No backend changes needed — `/api/shutdown` already exists.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v4, axios (via `api` client), lucide-react (icons available but not required for this feature)

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Modify | `frontend/src/components/Sidebar.tsx` | Add state, shutdown button, confirmation modal |

---

### Task 1: Implement shutdown button and confirmation modal in Sidebar

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx`

No test framework exists for the frontend. TypeScript compilation (`tsc -b`) serves as the verification gate.

- [ ] **Step 1: Open `frontend/src/components/Sidebar.tsx` and replace its entire contents**

The current file is 61 lines. Replace it with the following (adds `useState` import, two state vars, `handleShutdown` async function, Shut Down button at sidebar bottom, and modal overlay):

```tsx
import { useState } from 'react'
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

  const badges: Record<string, React.ReactNode> = {
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
    window.close()
  }

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
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-lg p-6 w-80 shadow-xl">
            <h2 className="text-white font-semibold text-base mb-1">Shut down server?</h2>
            <p className="text-slate-400 text-sm mb-5">This will stop the server and close this tab.</p>
            <div className="flex gap-3 justify-end">
              <button
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
```

- [ ] **Step 2: Run TypeScript type check**

```bash
cd frontend && npx tsc -b --noEmit
```

Expected: no errors. If you see `useState` not found, verify the `import { useState }` line is present at the top. If you see type errors on `api.post('/shutdown')`, check that `api` is the axios instance from `../api/client`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Sidebar.tsx
git commit -m "feat: add shutdown button with confirmation modal to sidebar"
```

---

### Task 2: Build frontend and smoke-test

**Files:**
- No file changes — build and verify only

- [ ] **Step 1: Build the production bundle**

```bash
cd frontend && npm run build
```

Expected: `dist/` updated with no errors. Output ends with something like:
```
✓ built in Xs
```

- [ ] **Step 2: Start the server**

```bash
uv run uvicorn bill_processor.web.app:app --reload --port 7432
```

Open `http://localhost:7432` in the browser.

- [ ] **Step 3: Verify the Shut Down button appears**

At the bottom of the left sidebar, below the Settings nav link, you should see a "Shut Down" button in muted red. It should be separated from the nav links by a faint horizontal border.

- [ ] **Step 4: Verify the modal**

Click "Shut Down". A dark overlay should appear with a card containing:
- Title: "Shut down server?"
- Description: "This will stop the server and close this tab."
- Cancel button (slate, left)
- Shut Down button (red, right)

Click **Cancel** — the modal should close, the app continues normally.

- [ ] **Step 5: Verify shutdown flow**

Click "Shut Down" again, then click the red **Shut Down** button. The button should show "Shutting down…" briefly, the server should stop (the terminal running uvicorn exits), and the browser tab should either close or show a connection-refused page.

- [ ] **Step 6: Commit**

```bash
git add frontend/dist
git commit -m "build: rebuild frontend with shutdown button"
```

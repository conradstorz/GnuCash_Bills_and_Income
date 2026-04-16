# Create New Vendor Modal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Create New Vendor" modal triggered from the Bills Queue vendor autocomplete and the Vendors page, with live non-blocking internet address lookup, that creates the vendor in GnuCash and auto-fills the vendor field when triggered from bill entry.

**Architecture:** A new `CreateVendorModal` React component manages form fields and a debounced live search against a new `GET /api/vendors/search-candidates` backend endpoint. The modal is self-contained — `VendorInput` in BillsQueue owns its instance; the Vendors page owns its own. Both call `POST /api/vendors` (existing) on Finish.

**Tech Stack:** FastAPI (Python), React 18, TypeScript, TanStack Query, Tailwind v4, shadcn/ui `Input`/`Button`, axios AbortController for request cancellation.

---

## File Map

| File | Change |
|---|---|
| `web/app.py` | Add `GET /api/vendors/search-candidates` endpoint |
| `tests/test_web_app.py` | Add tests for the new endpoint |
| `frontend/src/api/vendors.ts` | Add `VendorCandidate` type, `searchVendorCandidates`, `createVendor` |
| `frontend/src/components/CreateVendorModal.tsx` | New component |
| `frontend/src/pages/BillsQueue.tsx` | Add "＋ Add [name]" to VendorInput; wire modal |
| `frontend/src/pages/Vendors.tsx` | Add "+ New Vendor" button; wire modal |

---

## Background: Codebase Context

**`web/app.py`** imports address lookup as `import bill_processor.address_lookup as addr_lookup` (line 21). The existing lookup-address endpoint (line 494) calls `addr_lookup.lookup_google_places(query)` without `return_all=True`, returning one result. Both `lookup_google_places` and `lookup_openstreetmap` accept `return_all=True` and return a list of dicts with keys: `name`, `addr_line1`, `city`, `state`, `zip`.

**`POST /api/vendors`** (line 387) accepts `VendorIn`: `vendor_name` (required), `display_name`, `addr_line1`, `addr_city`, `addr_state`, `addr_zip`. Returns `{"ok": true, "key": "...", "guid": "..."}` or `{"ok": false, "error": "..."}`.

**`frontend/src/pages/BillsQueue.tsx`** — `VendorInput` component (line 16) fetches `/vendors/search?q=...` and shows a dropdown. The autocomplete `ul` element is the target for adding the "＋ Add" option.

**Tests** use `TestClient(app)` from `fastapi.testclient`. Mock `addr_lookup` by patching `bill_processor.web.app.addr_lookup`.

---

## Task 1: Backend — `GET /api/vendors/search-candidates`

**Files:**
- Modify: `web/app.py` (after line 501, the existing `lookup-address` endpoint)
- Modify: `tests/test_web_app.py` (append to end of file)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_app.py`:

```python
# ---------------------------------------------------------------------------
# Vendor search candidates
# ---------------------------------------------------------------------------

class TestVendorSearchCandidates:
    GOOGLE_RESULT = [
        {
            "name": "The Home Depot",
            "addr_line1": "4011 Eastgate Dr",
            "city": "Cincinnati",
            "state": "OH",
            "zip": "45245",
            "source": "google",
        }
    ]
    OSM_RESULT = [
        {
            "name": "Home Depot",
            "addr_line1": "100 Main St",
            "city": "Columbus",
            "state": "OH",
            "zip": "43215",
            "source": "openstreetmap",
        }
    ]

    def test_returns_google_candidates(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        mock_lookup = MagicMock()
        mock_lookup.lookup_google_places.return_value = self.GOOGLE_RESULT
        monkeypatch.setattr(web_app, "addr_lookup", mock_lookup)
        response = client.get("/api/vendors/search-candidates?name=Home+Depot")
        assert response.status_code == 200
        data = response.json()
        assert len(data["candidates"]) == 1
        c = data["candidates"][0]
        assert c["display_name"] == "The Home Depot"
        assert c["addr_line1"] == "4011 Eastgate Dr"
        assert c["addr_city"] == "Cincinnati"
        assert c["addr_state"] == "OH"
        assert c["addr_zip"] == "45245"

    def test_falls_back_to_osm_when_google_empty(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        mock_lookup = MagicMock()
        mock_lookup.lookup_google_places.return_value = []
        mock_lookup.lookup_openstreetmap.return_value = self.OSM_RESULT
        monkeypatch.setattr(web_app, "addr_lookup", mock_lookup)
        response = client.get("/api/vendors/search-candidates?name=Home+Depot")
        assert response.status_code == 200
        assert len(response.json()["candidates"]) == 1
        assert response.json()["candidates"][0]["display_name"] == "Home Depot"

    def test_empty_query_returns_empty_list(self, client):
        response = client.get("/api/vendors/search-candidates")
        assert response.status_code == 200
        assert response.json() == {"candidates": []}

    def test_lookup_returns_none_returns_empty_list(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        mock_lookup = MagicMock()
        mock_lookup.lookup_google_places.return_value = None
        mock_lookup.lookup_openstreetmap.return_value = None
        monkeypatch.setattr(web_app, "addr_lookup", mock_lookup)
        response = client.get("/api/vendors/search-candidates?name=Unknown+Vendor")
        assert response.status_code == 200
        assert response.json() == {"candidates": []}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest tests/test_web_app.py::TestVendorSearchCandidates -v
```

Expected: 4 failures with `404 Not Found` or `AttributeError` (endpoint doesn't exist yet).

- [ ] **Step 3: Add the endpoint to `web/app.py`**

Insert after the `lookup_address` function (after line 500):

```python
@app.get("/api/vendors/search-candidates")
def vendor_search_candidates(name: str = "", city: str = "", zip: str = ""):
    parts = [p for p in [name, city, zip] if p.strip()]
    if not parts:
        return {"candidates": []}
    query = " ".join(parts)
    raw = addr_lookup.lookup_google_places(query, return_all=True) or \
          addr_lookup.lookup_openstreetmap(query, return_all=True)
    if not raw:
        return {"candidates": []}
    return {
        "candidates": [
            {
                "display_name": r.get("name", ""),
                "addr_line1": r.get("addr_line1", ""),
                "addr_city": r.get("city", ""),
                "addr_state": r.get("state", ""),
                "addr_zip": r.get("zip", ""),
            }
            for r in raw
        ]
    }
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_web_app.py::TestVendorSearchCandidates -v
```

Expected: 4 passing.

- [ ] **Step 5: Commit**

```bash
git add web/app.py tests/test_web_app.py
git commit -m "feat: add GET /api/vendors/search-candidates endpoint"
```

---

## Task 2: Frontend API additions

**Files:**
- Modify: `frontend/src/api/vendors.ts`

- [ ] **Step 1: Add `VendorCandidate` type, `searchVendorCandidates`, and `createVendor` to `vendors.ts`**

The current file ends at line 29. Append:

```typescript
export interface VendorCandidate {
  display_name: string
  addr_line1: string
  addr_city: string
  addr_state: string
  addr_zip: string
}

export const searchVendorCandidates = (
  params: { name?: string; city?: string; zip?: string },
  signal?: AbortSignal,
) =>
  api
    .get<{ candidates: VendorCandidate[] }>('/vendors/search-candidates', { params, signal })
    .then(r => r.data.candidates)

export const createVendor = (body: {
  vendor_name: string
  display_name?: string
  addr_line1?: string
  addr_city?: string
  addr_state?: string
  addr_zip?: string
}) =>
  api
    .post<{ ok: boolean; key?: string; guid?: string; error?: string }>('/vendors', body)
    .then(r => r.data)
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/vendors.ts
git commit -m "feat: add searchVendorCandidates and createVendor API functions"
```

---

## Task 3: `CreateVendorModal` component

**Files:**
- Create: `frontend/src/components/CreateVendorModal.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/CreateVendorModal.tsx`:

```tsx
import { useState, useEffect, useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  createVendor,
  searchVendorCandidates,
  type VendorCandidate,
} from '../api/vendors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface Props {
  initialName: string
  onCreated: (displayName: string) => void
  onClose: () => void
}

export default function CreateVendorModal({ initialName, onCreated, onClose }: Props) {
  const qc = useQueryClient()
  const [displayName, setDisplayName] = useState(initialName)
  const [addrLine1, setAddrLine1] = useState('')
  const [city, setCity] = useState('')
  const [addrState, setAddrState] = useState('')
  const [zip, setZip] = useState('')
  const [candidates, setCandidates] = useState<VendorCandidate[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Debounced, non-blocking live search — watches name/city/zip only
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (!displayName.trim() && !city.trim() && !zip.trim()) {
        setCandidates([])
        return
      }
      if (abortRef.current) abortRef.current.abort()
      const controller = new AbortController()
      abortRef.current = controller
      setIsSearching(true)
      setSearchError(false)
      try {
        const results = await searchVendorCandidates(
          { name: displayName, city, zip },
          controller.signal,
        )
        setCandidates(results)
        setIsSearching(false)
      } catch (e: unknown) {
        // ERR_CANCELED means the request was aborted by a newer keystroke — ignore
        if ((e as { code?: string })?.code !== 'ERR_CANCELED') {
          setSearchError(true)
          setIsSearching(false)
        }
      }
    }, 600)
    return () => clearTimeout(timer)
  }, [displayName, city, zip])

  const fillFromCandidate = (c: VendorCandidate) => {
    setDisplayName(c.display_name)
    setAddrLine1(c.addr_line1)
    setCity(c.addr_city)
    setAddrState(c.addr_state)
    setZip(c.addr_zip)
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createVendor({
        vendor_name: displayName,
        display_name: displayName,
        addr_line1: addrLine1,
        addr_city: city,
        addr_state: addrState,
        addr_zip: zip,
      }),
    onSuccess: data => {
      if (data.ok) {
        qc.invalidateQueries({ queryKey: ['vendors'] })
        onCreated(displayName)
        onClose()
      } else {
        setCreateError(data.error ?? 'Failed to create vendor')
      }
    },
    onError: (e: unknown) => {
      setCreateError(e instanceof Error ? e.message : 'Failed to create vendor')
    },
  })

  // Close on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <h2 className="text-base font-semibold text-slate-800">New Vendor</h2>
          <span className="text-xs text-slate-400">Esc to cancel</span>
        </div>

        {/* Body */}
        <div className="flex min-h-64">
          {/* Left: form fields */}
          <div className="flex-1 p-6 border-r border-slate-100">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-4">
              Details
            </p>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-500 block mb-1">Display Name *</label>
                <Input
                  className="h-8 text-sm"
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  autoFocus
                />
              </div>
              <div>
                <label className="text-xs text-slate-500 block mb-1">Address</label>
                <Input
                  className="h-8 text-sm"
                  value={addrLine1}
                  onChange={e => setAddrLine1(e.target.value)}
                  placeholder="123 Main St"
                />
              </div>
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="text-xs text-slate-500 block mb-1">City</label>
                  <Input
                    className="h-8 text-sm"
                    value={city}
                    onChange={e => setCity(e.target.value)}
                  />
                </div>
                <div className="w-16">
                  <label className="text-xs text-slate-500 block mb-1">State</label>
                  <Input
                    className="h-8 text-sm"
                    value={addrState}
                    onChange={e => setAddrState(e.target.value)}
                  />
                </div>
                <div className="w-24">
                  <label className="text-xs text-slate-500 block mb-1">ZIP</label>
                  <Input
                    className="h-8 text-sm"
                    value={zip}
                    onChange={e => setZip(e.target.value)}
                  />
                </div>
              </div>
            </div>
            {createError && (
              <div className="mt-3 p-2 bg-red-50 border border-red-200 rounded text-red-600 text-xs">
                {createError}
              </div>
            )}
          </div>

          {/* Right: live candidates panel */}
          <div className="w-56 p-6 flex-shrink-0">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Internet Results
              {isSearching && (
                <span className="ml-2 text-blue-400 font-normal normal-case">searching…</span>
              )}
            </p>
            {searchError ? (
              <p className="text-xs text-slate-400 italic">Search unavailable</p>
            ) : candidates.length === 0 && !isSearching ? (
              <p className="text-xs text-slate-400 italic">No matches found</p>
            ) : (
              <div className="space-y-2">
                {candidates.map((c, i) => (
                  <button
                    key={i}
                    onClick={() => fillFromCandidate(c)}
                    className="w-full text-left p-2 border border-slate-200 rounded hover:border-blue-400 hover:bg-blue-50 transition-colors"
                  >
                    <div className="text-xs font-medium text-slate-800 truncate">
                      {c.display_name}
                    </div>
                    <div className="text-xs text-slate-500 truncate">{c.addr_line1}</div>
                    <div className="text-xs text-slate-500 truncate">
                      {[c.addr_city, c.addr_state, c.addr_zip].filter(Boolean).join(', ')}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-slate-200">
          <Button size="sm" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => createMutation.mutate()}
            disabled={!displayName.trim() || createMutation.isPending}
          >
            {createMutation.isPending ? 'Creating…' : 'Finish'}
          </Button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/CreateVendorModal.tsx
git commit -m "feat: add CreateVendorModal component with live search"
```

---

## Task 4: Wire modal into Bills Queue

**Files:**
- Modify: `frontend/src/pages/BillsQueue.tsx`

The `VendorInput` component (lines 16–62) renders a dropdown `ul`. It needs:
1. A new `onAddNew` prop.
2. A "＋ Add [name]" `li` at the bottom, shown when `value.trim().length >= 2` and no suggestion's `display_name` exactly matches `value`.
3. Modal state managed inside `VendorInput` so it stays self-contained.

- [ ] **Step 1: Update `VendorInput` in `BillsQueue.tsx`**

Replace the entire `VendorInput` function (lines 16–62) with:

```tsx
function VendorInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [suggestions, setSuggestions] = useState<VendorMatch[]>([])
  const [open, setOpen] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [modalInitialName, setModalInitialName] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleChange = async (v: string) => {
    onChange(v)
    if (v.trim().length < 2) { setSuggestions([]); setOpen(false); return }
    const res = await api.get<{ results: VendorMatch[] }>(`/vendors/search?q=${encodeURIComponent(v)}`)
    setSuggestions(res.data.results)
    setOpen(true)
  }

  const showAddNew =
    value.trim().length >= 2 &&
    !suggestions.some(s => s.display_name.toLowerCase() === value.trim().toLowerCase())

  return (
    <div className="relative" ref={ref}>
      <Input
        className="h-7 text-sm"
        value={value}
        placeholder="Vendor"
        autoFocus
        onChange={e => handleChange(e.target.value)}
        onFocus={() => (suggestions.length > 0 || showAddNew) && setOpen(true)}
      />
      {open && (suggestions.length > 0 || showAddNew) && (
        <ul className="absolute z-20 w-full bg-white border border-slate-200 rounded shadow-lg max-h-48 overflow-y-auto text-sm">
          {suggestions.map(s => (
            <li
              key={s.key}
              className="px-3 py-1.5 cursor-pointer hover:bg-blue-50"
              onMouseDown={() => { onChange(s.display_name); setSuggestions([]); setOpen(false) }}
            >
              {s.display_name}
            </li>
          ))}
          {showAddNew && (
            <li
              className="px-3 py-1.5 cursor-pointer hover:bg-green-50 text-green-700 font-medium border-t border-slate-100"
              onMouseDown={() => {
                setModalInitialName(value.trim())
                setShowModal(true)
                setOpen(false)
              }}
            >
              ＋ Add "{value.trim()}"
            </li>
          )}
        </ul>
      )}
      {showModal && (
        <CreateVendorModal
          initialName={modalInitialName}
          onCreated={displayName => { onChange(displayName); setShowModal(false) }}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add the import for `CreateVendorModal` at the top of `BillsQueue.tsx`**

After the existing imports (after line 6), add:

```tsx
import CreateVendorModal from '../components/CreateVendorModal'
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Manual smoke test**

Start the dev server:
```bash
cd frontend && npm run dev
```

1. Open Bills Queue, click "+ Add Bill".
2. In the Vendor field, type a name that doesn't exist (e.g. "Zanzibar Plumbing").
3. Confirm "＋ Add "Zanzibar Plumbing"" appears at the bottom of the dropdown.
4. Click it — the modal opens with "Zanzibar Plumbing" pre-filled in Display Name.
5. The search panel shows "searching…" then results (or "No matches found" if offline).
6. If results appear, click one — all fields fill in.
7. Click Finish — vendor is created, modal closes, vendor field in the bill row now shows the display name.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/BillsQueue.tsx
git commit -m "feat: add Create New Vendor flow to Bills Queue vendor autocomplete"
```

---

## Task 5: Wire modal into Vendors page

**Files:**
- Modify: `frontend/src/pages/Vendors.tsx`

- [ ] **Step 1: Add import for `CreateVendorModal` at the top of `Vendors.tsx`**

After the existing imports (after line 7), add:

```tsx
import CreateVendorModal from '../components/CreateVendorModal'
```

- [ ] **Step 2: Add modal state to the `Vendors` component**

Inside `export default function Vendors()` (after line 146), after the existing `useState` declarations, add:

```tsx
const [showCreateModal, setShowCreateModal] = useState(false)
```

- [ ] **Step 3: Add "+ New Vendor" button to the page header**

Replace the existing header div (lines 165–170):

```tsx
<div className="flex items-center justify-between mb-4">
  <h1 className="text-xl font-semibold text-slate-800">Vendors</h1>
  <div className="flex gap-2">
    <Button size="sm" onClick={() => setShowCreateModal(true)}>+ New Vendor</Button>
    <Button size="sm" variant="outline" onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}>
      {syncMutation.isPending ? 'Syncing...' : 'Sync All'}
    </Button>
  </div>
</div>
```

- [ ] **Step 4: Render the modal at the bottom of the return**

Before the final closing `</div>` of the component's return:

```tsx
{showCreateModal && (
  <CreateVendorModal
    initialName=""
    onCreated={() => {
      qc.invalidateQueries({ queryKey: ['vendors'] })
      setShowCreateModal(false)
    }}
    onClose={() => setShowCreateModal(false)}
  />
)}
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6: Manual smoke test**

1. Open the Vendors page.
2. Click "+ New Vendor".
3. Modal opens with empty fields.
4. Type a vendor name — search fires after 600ms.
5. Click a candidate to fill fields, or fill manually.
6. Click Finish — vendor appears in the list.
7. Click Cancel — modal closes, no vendor created.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/Vendors.tsx
git commit -m "feat: add Create New Vendor button to Vendors page"
```

---

## Task 6: Build and run full test suite

- [ ] **Step 1: Run all Python tests**

```bash
uv run pytest tests/ -v
```

Expected: all tests pass. The 4 new `TestVendorSearchCandidates` tests must be green.

- [ ] **Step 2: Build the frontend**

```bash
cd frontend && npm run build
```

Expected: builds without errors or type errors.

- [ ] **Step 3: Commit build verification (no new files — build output is gitignored)**

If all tests and build pass with no issues, no additional commit is needed. If any fix was required, commit it:

```bash
git add <changed files>
git commit -m "fix: <description of what was fixed>"
```

# React Frontend Rewrite — Design Spec

**Date:** 2026-04-15  
**Status:** Approved

## Overview

Replace the current HTMX + Jinja2 web interface with a React SPA backed by a clean FastAPI REST API. The data layer (`gnucash_db.py`) is unchanged. The Tkinter GUIs are removed. The CLI remains for non-interactive, automation-oriented operations.

---

## Architecture

### Three layers, clean boundaries

```
gnucash_db.py          ← data layer, untouched, fully tested
web/app.py             ← REST API only, returns JSON, no templates
frontend/              ← React SPA, talks to the API
```

**FastAPI** serves two things from one process:
- `GET /api/*` — REST endpoints (JSON in/out)
- `GET /*` — static files from `frontend/dist` (React build output)

On `GET /` and any unmatched route, FastAPI serves `frontend/dist/index.html` so React Router handles client-side navigation.

### Frontend project

`/frontend` is a self-contained Vite + React project:
- `npm run dev` — dev server with HMR, proxies `/api` to the FastAPI backend
- `npm run build` — outputs to `frontend/dist`, gitignored (build artifacts are not committed; the `.bat` launcher runs the build before starting the server)
- TypeScript throughout
- Component library: shadcn/ui (copy-paste components, no style lock-in)
- State management: React Query for server state (fetching, caching, mutations), `useState`/`useContext` for local UI state only

### What gets deleted

- All Jinja2 templates (`web/templates/`)
- HTMX-specific endpoints (any route that returns HTML fragments)
- `bill_entry_gui.py` and `vendor_manager_gui.py`

### What stays unchanged

- `gnucash_db.py` — zero modifications
- `web/cash_io.py` — memo history IO, called by API layer
- `web/queue_io.py` — bill queue file IO, called by API layer
- `settings_manager.py`, `config.py`, `vendor_manager.py`, etc.
- All CLI entry points (`main.py`)
- All existing tests — the data layer tests continue to pass

---

## UI Layout

**Persistent sidebar** navigation with four sections:

```
┌─────────────┬──────────────────────────────────┐
│  GnuCash    │                                  │
│  Bills      │   <active section content>       │
│  ─────────  │                                  │
│  Bills      │                                  │
│  Cash Entry │                                  │
│  Vendors    │                                  │
│  Settings   │                                  │
└─────────────┴──────────────────────────────────┘
```

React Router manages navigation. Each sidebar item is a `<NavLink>` that highlights when active.

---

## Section: Bills Queue (`/bills`)

A table of pending bills from `bills_to_process.txt`. Each row has inline actions.

**Table columns:** Vendor | Amount | Memo | Date | Actions (Post / Edit / Delete)

**Add bill:** `+ Add Bill` button inserts a new editable row at the top of the table. Fields: vendor search (autocomplete against vendor list), amount, memo, date. Tab moves between fields. Enter or clicking "Add" saves the row to the queue file. Escape cancels.

**Edit bill:** Clicking "Edit" on an existing row converts it to the same inline editable form in place. Save commits, Escape reverts.

**Post bill:** Clicking "Post" on a row calls the 3-step bill workflow (`create_bill` → `post_bill` → `pay_bill`) via the API. The row shows a loading state during processing. On success it is removed from the queue. On error a red inline message appears on that row.

**Delete bill:** Removes the row from the queue file without processing. Prompts for confirmation.

---

## Section: Cash Entry (`/cash`)

A spreadsheet-style multi-row batch form for posting cash transactions to GnuCash.

**Layout:**
```
Date: [picker]                              [Post to GnuCash]

  Memo              Account          Amount    ✕
  ─────────────────────────────────────────────
  [autocomplete]    [autocomplete]   [0.00]    ✕
  Smith Family      Income:Collect   75.00     ✕
  Jones Account     Income:Collect   120.00    ✕
  + Add row
  ─────────────────────────────────────────────
  SAMUSE (auto)     Cash on Hand     195.00
```

- **Memo autocomplete** — prefix/substring match against `memo_history.json`, ranked by usage frequency
- **Account autocomplete** — all non-placeholder accounts from GnuCash chart of accounts
- **SAMUSE row** — read-only footer, auto-calculated as the sum of all entry amounts
- **Tab navigation** — Tab moves Memo → Account → Amount → next row's Memo
- **Add row** — keyboard shortcut (Tab from last Amount) or click
- **Post to GnuCash** — submits the batch, saves all memos to history, clears the form on success
- **Deposit button** — separate button for an independent bank deposit transaction (amount unrelated to batch total); opens a small inline form above the table

---

## Section: Vendor Management (`/vendors`)

Master / detail layout.

**Left panel (master):** Searchable list of all vendors. Each entry shows display name, vendor key, and a sync status indicator (synced / not synced). Clicking a vendor selects it and loads the detail panel.

**Right panel (detail):** Shows full vendor record for the selected vendor:
- Display name, vendor key
- Aliases (editable list — add/remove individual aliases)
- Address fields (addr_line1, addr_city, addr_state, addr_zip)
- GnuCash GUID
- Edit button — makes fields editable in place; Save / Cancel
- Sync button — pushes the record to GnuCash and updates the sync status
- Address lookup button — triggers Google Places / OSM lookup to populate address fields

**Add vendor:** `+ New Vendor` button at the top of the left panel opens an inline form in the detail panel for a new record.

---

## Section: Settings (`/settings`)

A standard form layout for user-configurable settings, organized into groups:

- **Database** — GnuCash database path (with file browser button)
- **Cash entry accounts** — checkbox grid to enable/disable accounts in the cash entry dropdown
- **Cash-on-hand account** — text input with live validation (account must exist in GnuCash)
- **Locality** — city, state, coordinates, search radius
- **Fuzzy matching** — match and ambiguous thresholds
- **Reset** — restore all settings to defaults

Live validation on the cash-on-hand account field (debounced, calls `/api/accounts/validate`).

---

## API Layer

All existing HTMX routes in `web/app.py` are replaced with clean REST endpoints. No route returns HTML. Existing route paths are restructured under `/api/` prefix to leave `/` free for the React app.

**Key endpoint groups:**

| Group | Examples |
|---|---|
| Bills | `GET /api/bills`, `POST /api/bills`, `PUT /api/bills/{idx}`, `DELETE /api/bills/{idx}`, `POST /api/bills/{idx}/post` |
| Cash | `POST /api/cash/submit`, `POST /api/cash/deposit` |
| Vendors | `GET /api/vendors`, `POST /api/vendors`, `PUT /api/vendors/{key}`, `POST /api/vendors/{key}/sync` |
| Accounts | `GET /api/accounts` (all), `GET /api/accounts/cash` (cash entry subset), `GET /api/accounts/validate?name=X` |
| Memos | `GET /api/memos?q=X` |
| Settings | `GET /api/settings`, `PUT /api/settings` |
| DB health | `GET /api/db/health`, `POST /api/db/path` |

---

## Error Handling

- API errors return `{"error": "message"}` with appropriate HTTP status codes
- The React app displays inline errors on the affected component (row-level for bills, form-level for cash/settings)
- DB unavailable: the React app checks `GET /api/db/health` on load; if unhealthy, renders a full-screen error state with recovery options (browse for file, retry)

---

## Testing

- Existing `gnucash_db.py` tests are unchanged and must continue to pass
- New API route tests replace the current `test_web_app.py` and `test_cash_web.py` — same coverage, updated for JSON responses instead of HTML
- React components are not unit tested (this is a personal tool; integration via the API tests is sufficient)

---

## Migration Path

1. Commit current uncommitted changes (`gnucash_db.py`, `test_get_cash_accounts.py`)
2. Build the REST API layer (restructure `web/app.py`, verify all existing tests pass)
3. Scaffold the React + Vite frontend (`/frontend`)
4. Implement sections in order: Bills Queue → Cash Entry → Vendors → Settings
5. Delete Jinja2 templates and Tkinter GUI files once all sections are working
6. Update the `.bat` launcher to serve the new static build

---

## Out of Scope

- Authentication / multi-user (single-user personal tool)
- Mobile layout (desktop browser only)
- Dark mode
- CLI changes (CLI is not being touched)

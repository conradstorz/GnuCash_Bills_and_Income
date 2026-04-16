# Create New Vendor — Design Spec

## Overview

A reusable `CreateVendorModal` component that lets the user create a new vendor from scratch, with live non-blocking internet lookup to pre-fill address details. Triggered from two places: the Bills Queue vendor autocomplete and the Vendors page.

---

## Entry Points

### Bills Queue (`BillsQueue.tsx` → `VendorInput`)

The autocomplete dropdown currently shows matching vendors. After this change, when the typed text does not exactly match any existing vendor, a final option appears at the bottom of the list:

```
＋ Add "Home Depot"
```

Clicking it opens `CreateVendorModal` with `initialName` pre-set to the typed text. On `onCreated(displayName)`, the display name is dropped directly into the vendor field so the user can continue entering the bill without any extra steps.

### Vendors Page (`Vendors.tsx`)

A "+ New Vendor" button is added to the page header, next to the existing "Sync All" button. Clicking it opens `CreateVendorModal` with an empty `initialName`. On `onCreated`, the vendor list is refreshed via React Query cache invalidation.

---

## Modal Design

**Style:** Full-screen centred overlay (Option A from design review). Blocks the rest of the UI while open. Dismissed only by the user clicking Cancel or Finish — never auto-closes.

**Layout:** Two-column body.

- **Left column — Details form:** Five editable fields: Display Name (required), Address Line 1, City, State, ZIP. All address fields are optional.
- **Right column — Internet Results panel:** Shows live search candidates. Displays a subtle spinner while a search is in flight. Shows "No matches found" or "Search unavailable" in the appropriate failure cases.

**Footer:** Cancel button (closes modal, no action) and Finish button (creates vendor). Finish is disabled only when Display Name is empty.

---

## Search Behaviour

Search is fully automatic and non-blocking.

- A `useEffect` watches all five form fields.
- After a 600ms debounce, it fires `GET /api/vendors/search-candidates` with whatever fields are non-empty as query params (`name`, `city`, `zip`).
- Any in-flight request is cancelled via `AbortController` when new input arrives. Field inputs never wait on a search — they are always immediately responsive.
- No minimum character requirement. Even a single character triggers a search after the debounce.
- Results appear in the right panel as cards showing display name and formatted address.
- Clicking a result fills **all five fields** from that candidate (replacing any values already typed).
- After a candidate fills the fields, the user may edit any field freely before clicking Finish.

---

## Backend: New Endpoint

### `GET /api/vendors/search-candidates`

Query params: `name` (str), `city` (str, optional), `zip` (str, optional).

Builds a single query string from the non-empty params. Calls `addr_lookup.lookup_google_places(query, return_all=True)`. If that returns an empty list (no API key or no results), falls back to `addr_lookup.lookup_openstreetmap(query, return_all=True)`.

Response:
```json
{
  "candidates": [
    {
      "display_name": "The Home Depot",
      "addr_line1": "4011 Eastgate Dr",
      "addr_city": "Cincinnati",
      "addr_state": "OH",
      "addr_zip": "45245"
    }
  ]
}
```

Returns an empty `candidates` list (never an error) when no results are found. Returns a 500 with `{"error": "..."}` only for unexpected failures.

### Existing endpoints unchanged

- `POST /api/vendors` — used by Finish to create the vendor. No changes.
- `POST /api/vendors/lookup-address` — used by the Vendors page edit flow (single best match). No changes.

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Search returns no results | Right panel shows "No matches found" — user fills fields manually |
| Search fails (network/API error) | Right panel shows "Search unavailable" — form stays fully usable |
| `POST /api/vendors` fails (e.g. name already exists) | Inline error shown below form fields — modal stays open |
| User edits fields after clicking a candidate | Always allowed — fields are never locked |
| Finish with only Display Name filled | Valid — address fields are optional |

---

## Frontend Files

| File | Change |
|---|---|
| `frontend/src/components/CreateVendorModal.tsx` | New component |
| `frontend/src/api/vendors.ts` | Add `searchVendorCandidates(params)` function |
| `frontend/src/pages/BillsQueue.tsx` | Add "＋ Add [name]" to `VendorInput` dropdown; wire modal |
| `frontend/src/pages/Vendors.tsx` | Add "+ New Vendor" button; wire modal |

## Backend Files

| File | Change |
|---|---|
| `web/app.py` | Add `GET /api/vendors/search-candidates` endpoint |

---

## Testing

**Backend:**
- `GET /api/vendors/search-candidates` with valid name — returns candidates from Google Places path
- `GET /api/vendors/search-candidates` — OSM fallback when Google Places returns empty
- `GET /api/vendors/search-candidates` with empty query — returns empty candidates list, no error
- `GET /api/vendors/search-candidates` — returns empty list when lookup returns None

**Frontend (`CreateVendorModal`):**
- Clicking a candidate populates all five fields
- Finish button disabled when Display Name is empty, enabled otherwise
- `onCreated` called with correct display name on successful POST
- Inline error shown when POST fails
- Search debounce: rapid field changes produce only one fetch (the last one)

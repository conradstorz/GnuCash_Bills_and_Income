# Vendor Form Dialog Refactor

**Date:** 2026-03-24
**Status:** Approved

## Problem

The "Add new vendor" form is rendered inline inside the bill entry `<form>` via HTMX (`hx-get="/vendors/new-form"` → `#new-vendor-section`). This causes the form to close unpredictably because:

1. The vendor input's `hx-trigger="keyup changed delay:300ms"` fires when JS programmatically sets the input value, triggering a new search whose dropdown results contain `onclick` handlers that clear `#new-vendor-section`.
2. The new vendor form's inputs (including a hidden `vendor_name`) live inside the outer bill entry `<form>`, creating name conflicts.
3. Any HTMX swap targeting `#bill-entry-form` (e.g., form submission) destroys the new vendor form and all in-progress data.
4. The 30-second polling on `#queued-bills` is safe (different target), but the architecture provides no guarantee of isolation — the form is unprotected DOM.

HTMX is the wrong tool for a stateful multi-step workflow (open form → lookup address → refine → select candidate → create or cancel). It has no concept of application state or mode, and competing swap targets destroy in-progress work.

## Solution

Move the new vendor creation workflow into a native `<dialog>` element managed by a vanilla JS module (`vendor-form.js`). The dialog lives outside the bill entry form in `dashboard.html`, providing browser-level DOM isolation. HTMX cannot reach inside it.

The rest of the app (bill queue, cash entry, polling, settings) remains pure HTMX — unchanged.

## Architecture

### Current structure (broken)

```
<form hx-post="/bills/queue">          ← outer bill form
  <input id="vendor-input" hx-get>    ← triggers HTMX searches
  <div id="vendor-dropdown">           ← HTMX dropdown results
  <div id="new-vendor-section">        ← vendor form HERE (vulnerable to swaps)
  <input amount, memo, date...>
  <button submit>
</form>
```

### New structure

```
<form hx-post="/bills/queue">          ← outer bill form (unchanged)
  <input id="vendor-input" hx-get>    ← HTMX fuzzy search (unchanged)
  <div id="vendor-dropdown">           ← HTMX dropdown (unchanged)
  <input amount, memo, date...>
  <button submit>
</form>

<dialog id="vendor-dialog">            ← OUTSIDE form, browser-isolated
  <div id="vendor-form-content">       ← managed by vendor-form.js
    display name, address fields, candidates, create/cancel buttons
  </div>
</dialog>
```

## Interaction Flow

### Step 1: Vendor search (unchanged)

User types in `#vendor-input` → HTMX `GET /vendors/search` after 300ms → dropdown renders fuzzy matches. No changes.

### Step 2: Select existing vendor (unchanged)

User clicks dropdown result → JS sets `#vendor-input.value` → dropdown clears. No changes.

### Step 3: "+ Add new vendor" opens dialog

User clicks "+ Add new vendor" in dropdown. Instead of `hx-get="/vendors/new-form"`, this calls:

```js
VendorForm.open('the typed name')
```

This:
1. Clears the vendor dropdown
2. Populates the dialog's display name field with the typed name
3. Calls `dialog.showModal()` (browser handles backdrop, focus trap, Escape key)
4. Fires initial address lookup via `fetch()`

### Step 4: Address lookup inside dialog

Managed by `vendor-form.js` using `fetch()`:
- On open: `fetch('/vendors/lookup-address', ...)` with display name
- Renders candidates into a list inside the dialog
- User edits city/zip → debounced `fetch()` re-queries (500ms)
- User clicks candidate → JS populates address fields, clears candidate list

Same backend endpoints, same logic — `fetch()` instead of HTMX.

### Step 5: Create or Cancel

- **Create**: `fetch('/vendors/create', ...)` → on success, sets `#vendor-input.value` to new display name, closes dialog
- **Cancel**: `dialog.close()` — vendor input untouched

### Step 6: After dialog closes

Vendor input has the name. User fills in amount/memo/date, submits bill form via HTMX as normal.

## New File: `web/static/vendor-form.js`

~150-200 lines. Plain ES module exposing a global `VendorForm` object.

### Public API

- `VendorForm.open(name)` — populate dialog, fire initial address lookup, show modal
- `VendorForm.close()` — close dialog, clear state

### Internal methods

- `lookupAddress()` — debounced fetch to `/vendors/lookup-address`, render candidates into `#vf-candidates`
- `selectCandidate(element)` — populate address fields from clicked candidate data attributes
- `create()` — POST `/vendors/create`, handle success/error, close dialog on success
- `_debounce(fn, ms)` — utility for city/zip input listeners (500ms delay)
- `_attachListeners()` — called once on page load; attaches `input` event listeners with debounce to `#vf-city` and `#vf-zip` to re-query address lookup as the user refines

### What it does NOT do

- No framework, no classes, no module bundler
- No interaction with HTMX-managed elements except setting `#vendor-input.value` on successful create
- No polling or timers other than address lookup debounce

## Backend Changes

### Request format

Both `/vendors/create` and `/vendors/lookup-address` currently accept `Form()` parameters (URL-encoded). The `fetch()` calls in `vendor-form.js` will send `FormData` objects to match the existing route signatures. No changes to parameter parsing — only the response format changes.

### `/vendors/create` (POST)

Accept `FormData` (unchanged). Return JSON instead of HTML+script:

```json
// Success
{"ok": true, "display_name": "Acme Electric Co.", "guid": "abc123..."}

// Error
{"ok": false, "error": "Vendor name is required."}
```

### `/vendors/lookup-address` (POST)

Accept `FormData` (unchanged). Return JSON instead of rendering `address_candidates.html`:

```json
{
  "candidates": [
    {
      "name": "Acme Electric Co.",
      "addr_line1": "123 Main St",
      "addr_line2": "Cincinnati, OH 45202",
      "phone": "513-555-1234",
      "distance": 2.3,
      "formatted_address": "123 Main St, Cincinnati, OH 45202"
    }
  ],
  "message": ""
}
```

The `vendor-form.js` `lookupAddress()` method always sends `display_name` (pre-populated from the typed name). The `vendor_name` Form parameter is also sent for backward compatibility with the route's fallback logic (line 358-359 of app.py).

### `/vendors/new-form` (GET)

Delete this route. The dialog doesn't need it.

## Template Changes

### `dashboard.html`

Add at the end of `{% block content %}`, before `{% endblock %}`:

```html
<dialog id="vendor-dialog">
  <div id="vendor-form-content">
    <h3>New Vendor: <span id="vf-title"></span></h3>
    <div id="vf-error" class="error-msg" style="display:none"></div>

    <label for="vf-display-name">Display Name</label>
    <input type="text" id="vf-display-name">

    <div id="vf-candidates"></div>

    <label for="vf-addr1">Address Line 1</label>
    <input type="text" id="vf-addr1">

    <label for="vf-addr2">Address Line 2</label>
    <input type="text" id="vf-addr2">

    <div style="display:flex; gap:1rem">
      <div style="flex:1">
        <label for="vf-city">City</label>
        <input type="text" id="vf-city">
      </div>
      <div style="flex:1">
        <label for="vf-state">State</label>
        <input type="text" id="vf-state">
      </div>
      <div style="flex:1">
        <label for="vf-zip">ZIP</label>
        <input type="text" id="vf-zip">
      </div>
    </div>

    <label for="vf-phone">Phone</label>
    <input type="text" id="vf-phone">

    <div style="margin-top:0.75rem; display:flex; gap:0.5rem">
      <button type="button" class="btn-primary" onclick="VendorForm.create()">Create Vendor</button>
      <button type="button" onclick="VendorForm.close()">Cancel</button>
    </div>
  </div>
</dialog>
<script src="/static/vendor-form.js"></script>
```

### `bill_entry.html`

Remove `<div id="new-vendor-section"></div>` (line 11).

### `partials/vendor_dropdown.html`

Two changes:

1. **Existing vendor items (line 7):** Remove the `document.getElementById("new-vendor-section").innerHTML = ""` reference from the `onclick` handler. `#new-vendor-section` no longer exists.

2. **"+ Add new vendor" item:** Change from `hx-get="/vendors/new-form"` to:

```html
<div class="dropdown-item" style="color:#888; font-style:italic"
     onclick="VendorForm.open({{ query | tojson }})">
  + Add &ldquo;{{ query | e }}&rdquo; as new vendor&hellip;
</div>
```

Remove the `hx-on::after-request` attribute — dropdown clearing now happens inside `VendorForm.open()` immediately.

### Templates deleted

- `partials/new_vendor_form.html` — replaced by dialog in dashboard.html
- `partials/address_candidates.html` — rendered by JS from JSON

## CSS Additions

Minimal dialog styling in `style.css`:

```css
#vendor-dialog {
  max-width: 32rem;
  border-radius: 6px;
  border: 1px solid #ccc;
  padding: 1.5rem;
}
#vendor-dialog::backdrop {
  background: rgba(0, 0, 0, 0.4);
}
```

## Complete Changeset

| Action | File |
|--------|------|
| New | `web/static/vendor-form.js` |
| Modify | `web/app.py` (2 routes return JSON, 1 route deleted) |
| Modify | `web/templates/dashboard.html` (add dialog + script tag) |
| Modify | `web/templates/bill_entry.html` (remove new-vendor-section div) |
| Modify | `web/templates/partials/vendor_dropdown.html` (onclick instead of hx-get) |
| Modify | `web/static/style.css` (dialog styling) |
| Delete | `web/templates/partials/new_vendor_form.html` |
| Delete | `web/templates/partials/address_candidates.html` |

## What stays untouched

- Bill entry form (HTMX post to queue)
- Vendor search dropdown (HTMX fuzzy search)
- Queued bills (HTMX polling, process/remove/edit)
- Cash entry panel (entire right side)
- Sync status card (HTMX polling)
- Settings pages
- All backend logic (vendor_manager.py, utils.py, gnucash_db.py, address_lookup.py)
- queue_io.py, cash_io.py

## Testing

### Tests to delete (route `/vendors/new-form` is removed)

These tests in `test_web_app.py` assert behavior of the deleted route/template:

- `test_new_vendor_form_renders`
- `test_new_vendor_form_auto_fires_address_search_on_load`
- `test_new_vendor_form_hx_vals_contains_display_name`
- `test_new_vendor_form_city_zip_have_refinement_triggers`
- `test_new_vendor_form_no_lookup_button`
- `test_new_vendor_form_cancel_clears_vendor_input`

### Tests to rewrite (JSON responses instead of HTML)

- `test_address_lookup_returns_form` — assert JSON structure `{"candidates": [...], "message": ""}` instead of HTML
- `test_address_candidates_height_shows_three` — delete (CSS concern of deleted template)
- `test_create_vendor_empty_name_rejected` — assert `{"ok": false, "error": "..."}` instead of HTML error

### Tests unchanged

- All `/vendors/search` tests (dropdown is still HTMX)
- All bill queue tests
- All cash entry tests

### Manual testing

- Open dialog, refine address, create vendor, verify it appears in vendor input and `vendor_database.json`
- Verify Escape key closes dialog without side effects
- Verify backdrop click closes dialog
- Verify city/zip edits trigger debounced address re-lookup

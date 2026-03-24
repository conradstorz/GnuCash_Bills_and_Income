# Vendor Discovery and Creation UX Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the broken new-vendor flow so that clicking "+ Add as new vendor…" loads the creation form, auto-fires an address search, and lets the user refine results by typing address details before selecting and creating the vendor.

**Architecture:** HTMX-native — all interactions use existing HTMX patterns and the existing `/vendors/lookup-address` endpoint. No new routes required. Changes touch `new_vendor_form.html`, `vendor_dropdown.html`, `address_candidates.html`, the `/vendors/lookup-address` route, and tests.

**Tech Stack:** FastAPI, HTMX, Jinja2, existing address lookup service (Google Places / OSM)

---

## Section 1: Bug Fix — Dropdown Clear Race Condition

**Root cause:** The `onclick` on the "+ Add as new vendor…" item in `vendor_dropdown.html` empties `#vendor-dropdown`, removing the element that carries `hx-get` from the DOM before HTMX can fire the request.

**Fix:** Remove the `onclick` attribute from that item. Replace it with:
```
hx-on::after-request="document.getElementById('vendor-dropdown').innerHTML=''"
```
HTMX fires the request first; the dropdown is cleared after the response arrives and the new vendor form is already loaded. The existing `hx-get`, `hx-target="#new-vendor-section"`, and `hx-swap="innerHTML"` attributes on that element are preserved unchanged.

**Second-click note:** After `after-request` fires, `#vendor-dropdown` is empty, so the "+ Add…" item no longer exists in the DOM. A second click cannot occur. No additional handling needed.

**Files changed:** `web/templates/partials/vendor_dropdown.html`

---

## Section 2: Auto-Fire Address Search on Form Load

**Behavior:** When the new vendor form renders in `#new-vendor-section`, it immediately triggers an address search without any user action.

**Implementation:** The `#address-candidates` div in `new_vendor_form.html` gets HTMX attributes:
- `hx-post="/vendors/lookup-address"`
- `hx-trigger="load"`
- `hx-swap="innerHTML"`
- `hx-vals='{"display_name": "{{ display_name | e }}"}'` — Jinja2 renders the vendor name into the JSON string at template render time, so HTMX sends the correct value when it fires on load.

The "Look Up Address" button is removed — it is replaced by the auto-trigger.

**Files changed:** `web/templates/partials/new_vendor_form.html`

---

## Section 3: Refinement Inputs Trigger Narrowed Search

**Behavior:** As the user types in the city or ZIP fields, the address search re-fires (debounced 500ms) using all currently-filled values combined as the search query. This naturally narrows results via the address lookup service without any server-side state.

**Trigger fields:** `addr_city` and `addr_zip` only. `addr_line1` is intentionally excluded — it is filled by candidate selection, and triggering a search from it would cause an immediate re-search loop after the user picks a candidate.

**Implementation:** The `addr_city` and `addr_zip` inputs each get:
- `hx-post="/vendors/lookup-address"`
- `hx-trigger="keyup changed delay:500ms"`
- `hx-target="#address-candidates"`
- `hx-swap="innerHTML"`
- `hx-include="closest form"` — sends all form fields; the route reads only `display_name`, `addr_city`, and `addr_zip`

**Route update (`/vendors/lookup-address`):** Add `addr_city: str = Form("")` and `addr_zip: str = Form("")` to the route signature alongside the existing `vendor_name` and `display_name` parameters. Build the search string by joining all non-empty values from `display_name`, `addr_city`, and `addr_zip` with a space (e.g., `"Kroger Cincinnati 45202"`). Skip any that are empty or whitespace-only. Pass the combined string to the address lookup service as the search query.

**Files changed:**
- `web/templates/partials/new_vendor_form.html`
- `web/app.py` (`lookup_address` route)

---

## Section 4: Candidate List Display

**Behavior:**
- All candidates are rendered in a scrollable container sized to show ~3 at a time.
- No pagination; user scrolls to see more.
- Even a single candidate requires an explicit click to select — no auto-selection.
- Selecting a candidate fills the address fields (existing `onclick` behavior preserved) and clears the candidate list (`document.getElementById('address-candidates').innerHTML = ''`).
- The user may then modify any pre-filled field and must click **Create Vendor** to finalize.

**Implementation:** In `address_candidates.html`, set the scrollable container to `max-height: 9rem; overflow-y: auto`. All other rendering logic unchanged.

**Files changed:** `web/templates/partials/address_candidates.html`

---

## Section 5: Cancel Button

**Behavior:** The Cancel button in the new vendor form resets the entire bill entry row to a blank state:
1. Clears `#new-vendor-section` (removes the form)
2. Clears `#vendor-dropdown` (removes any stale dropdown)
3. Sets `#vendor-input` to empty string (blank vendor name field)

`#vendor-dropdown` and `#vendor-input` are confirmed to exist in the outer page DOM — `#vendor-dropdown` is the container rendered by the bill entry template, and `#vendor-input` is the text input for the vendor name (referenced in `vendor_dropdown.html` line 5).

**Implementation:** Update the Cancel button's `onclick`:
```javascript
document.getElementById('new-vendor-section').innerHTML='';
document.getElementById('vendor-dropdown').innerHTML='';
document.getElementById('vendor-input').value='';
```

**Files changed:** `web/templates/partials/new_vendor_form.html`

---

## What Is Not Changing

- `/vendors/lookup-address` route signature — gains `addr_city` and `addr_zip` Form parameters; query assembly logic updated; response format unchanged
- `/vendors/create` route — unchanged
- `address_candidates.html` candidate selection `onclick` — unchanged (fills fields, clears candidate list)
- Existing vendor selection in `vendor_dropdown.html` — unchanged
- All other bill entry form behavior — unchanged

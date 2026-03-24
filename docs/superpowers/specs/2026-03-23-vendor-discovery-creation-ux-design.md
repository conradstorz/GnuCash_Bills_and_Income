# Vendor Discovery and Creation UX Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the broken new-vendor flow so that clicking "+ Add as new vendor…" loads the creation form, auto-fires an address search, and lets the user refine results by typing address details before selecting and creating the vendor.

**Architecture:** HTMX-native — all interactions use existing HTMX patterns and the existing `/vendors/lookup-address` endpoint. No new routes required. Changes touch `new_vendor_form.html`, `vendor_dropdown.html`, `address_candidates.html`, the `/vendors/lookup-address` route, and tests.

**Tech Stack:** FastAPI, HTMX, Jinja2, existing address lookup service (Google Places / OSM)

---

## Section 1: Bug Fix — Dropdown Clear Race Condition

**Root cause:** The `onclick` on the "+ Add as new vendor…" item in `vendor_dropdown.html` empties `#vendor-dropdown`, removing the element that carries `hx-get` from the DOM before HTMX can fire the request.

**Fix:** Remove the `onclick` attribute from that item. Replace it with `hx-on::after-request="document.getElementById('vendor-dropdown').innerHTML=''"`. HTMX fires the request first; the dropdown is cleared after the response arrives and the new vendor form is already loaded.

**Files changed:** `web/templates/partials/vendor_dropdown.html`

---

## Section 2: Auto-Fire Address Search on Form Load

**Behavior:** When the new vendor form renders in `#new-vendor-section`, it immediately triggers an address search without any user action.

**Implementation:** The `#address-candidates` div in `new_vendor_form.html` gets HTMX attributes:
- `hx-post="/vendors/lookup-address"`
- `hx-trigger="load"`
- `hx-swap="innerHTML"`
- `hx-vals` carrying the vendor display name

The "Look Up Address" button is removed — it is replaced by the auto-trigger.

**Files changed:** `web/templates/partials/new_vendor_form.html`

---

## Section 3: Refinement Inputs Trigger Narrowed Search

**Behavior:** As the user types in the city, ZIP, or street fields, the address search re-fires (debounced 500ms) using all currently-filled values combined as the search query. This naturally narrows results via the address lookup service without any server-side state.

**Implementation:** The city, ZIP, and street address fields each get:
- `hx-post="/vendors/lookup-address"`
- `hx-trigger="keyup changed delay:500ms"`
- `hx-target="#address-candidates"`
- `hx-swap="innerHTML"`
- `hx-include` referencing all relevant fields: `display_name`, `addr_line1`, `addr_city`, `addr_zip`

The `/vendors/lookup-address` route is updated to assemble the search query from all provided fields (e.g., `"Kroger Cincinnati 45202"`) instead of only `display_name`.

**Files changed:**
- `web/templates/partials/new_vendor_form.html`
- `web/app.py` (`lookup_address` route)

---

## Section 4: Candidate List Display

**Behavior:**
- All candidates are rendered in a scrollable container sized to show ~3 at a time.
- No pagination; user scrolls to see more.
- Even a single candidate requires an explicit click to select — no auto-selection.
- Selecting a candidate fills the address fields (existing `onclick` behavior preserved) and clears the candidate list.
- The user may then modify any pre-filled field and must click **Create Vendor** to finalize.

**Implementation:** `address_candidates.html` scrollable container height adjusted to `~9rem` (shows ~3 candidates). All other rendering logic unchanged.

**Files changed:** `web/templates/partials/address_candidates.html`

---

## Section 5: Cancel Button

**Behavior:** The Cancel button in the new vendor form resets the entire bill entry row to a blank state:
1. Clears `#new-vendor-section` (removes the form)
2. Clears `#vendor-dropdown` (removes any stale dropdown)
3. Sets `#vendor-input` to empty string (blank vendor name field)

**Implementation:** Update the Cancel button's `onclick` to perform all three operations.

**Files changed:** `web/templates/partials/new_vendor_form.html`

---

## What Is Not Changing

- `/vendors/lookup-address` route signature — only the query assembly logic changes internally
- `/vendors/create` route — unchanged
- `address_candidates.html` candidate selection `onclick` — unchanged (fills fields, clears candidate list)
- Existing vendor selection in `vendor_dropdown.html` — unchanged
- All other bill entry form behavior — unchanged

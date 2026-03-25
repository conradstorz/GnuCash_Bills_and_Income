# Vendor Dialog Live Search — Design Spec

**Date:** 2026-03-24
**Status:** Draft
**Scope:** `web/static/vendor-form.js`, `web/templates/dashboard.html`, `web/static/style.css`
**Backend routes:** No changes required — `/vendors/lookup-address` already returns JSON

## Problem

The vendor creation dialog opens but gives no feedback that a search is in progress. Results eventually appear but feel disconnected from the form inputs. Changing city or zip doesn't visibly update results. Stale results linger after inputs change. The user can't tell if the system is working or stuck.

## Design Principles

1. **The search panel is always visible** — never hidden, collapsed, or removed from the DOM.
2. **All relevant inputs drive the search** — display name, city, and zip each trigger a debounced re-search.
3. **Loading state is explicit** — the user always knows when a search is in flight.
4. **Results reflect current inputs** — stale results are replaced immediately when a new search fires.
5. **The user is the authority** — the search is a convenience helper, not a gatekeeper. "No exact matches found" is a valid state, not an error.

## Candidates Panel

### Placement

Between the display name field and the address fields, inside the dialog. Always rendered. Fixed max-height (~9rem), scrollable when results overflow.

### Three States

| State | Display |
|-------|---------|
| **Loading** | Text: "Searching..." in muted italic. Replaces any previous content immediately. |
| **Results** | Clickable candidate cards showing name, formatted address, and distance (if available). Same card format as current implementation. |
| **Empty** | Text: "No exact matches found" in muted italic. |

### State Transitions

```
Dialog opens
  → Panel shows "Searching..."
  → lookupAddress() fires immediately
  → Response arrives → render results or "No exact matches found"

User edits display name, city, or zip
  → Debounce timer resets (500ms)
  → Panel shows "Searching..." immediately when fetch fires
  → Response arrives → render results or "No exact matches found"
  → Stale responses discarded via requestGen counter

User clicks a candidate
  → Form fields populate (addr1, city, state, zip, phone)
  → Panel stays open (not cleared)
  → Populated city/zip trigger debounced re-search
  → New results reflect the selected address context
```

## Search Triggers

All three fields use `input` event listeners with 500ms debounce:

| Field | Current behavior | New behavior |
|-------|-----------------|--------------|
| Display name (`vf-display-name`) | No search trigger | Triggers debounced re-search |
| City (`vf-city`) | Triggers debounced re-search | No change |
| ZIP (`vf-zip`) | Triggers debounced re-search | No change |

The debounce timer is shared — any keystroke in any of the three fields resets the same timer. This prevents overlapping searches when the user tabs between fields quickly.

## Candidate Selection

When the user clicks a candidate card:

1. Form fields populate: addr1, addr2 (cleared), city, state, zip, phone
2. The candidates panel **remains visible** — it is not cleared or hidden
3. The city/zip fields now contain new values, which will trigger a debounced re-search
4. The re-search results will naturally reflect the updated location context

This means after selecting a candidate, the panel briefly shows "Searching..." then refreshes with results near the selected address. This is correct and expected behavior.

## Loading Feedback

When `lookupAddress()` is called:

1. **Immediately** set the candidates panel to show "Searching..." (before the fetch fires)
2. Fire the fetch request
3. On response: render results or "No exact matches found"
4. On network error: show "Address lookup unavailable"

The "Searching..." message replaces whatever was in the panel. This ensures the user always sees that something is happening, even if the fetch takes several seconds.

## Changes Required

### `web/static/vendor-form.js`

1. **Add display name to search triggers:** Attach `input` event listener with `debouncedLookup()` to the display name field in `init()`.

2. **Show loading state in `lookupAddress()`:** Before the fetch call, set `candidates.innerHTML` to the "Searching..." message.

3. **Update `renderCandidates()` empty state:** When items array is empty and no error message, show "No exact matches found" instead of clearing the panel.

4. **Do not clear candidates on selection:** In `selectCandidate()`, remove the line `candidates.innerHTML = ""`. The panel stays as-is; the city/zip changes will trigger a natural re-search.

### `web/templates/dashboard.html`

No changes needed. The dialog HTML structure is unchanged.

### `web/static/style.css`

Minor addition: style for the "Searching..." / "No exact matches found" status text within the candidates panel (muted, italic).

### `web/app.py`

No changes needed. The `/vendors/lookup-address` route already accepts `display_name` as a form parameter and returns JSON.

## Out of Scope

- Changing the dialog layout (stays single-column)
- Modifying the backend search logic or API
- Fixing the pre-existing `addr_city`/`addr_state`/`addr_zip` mapping bug in `gnucash_db.create_vendor()`
- Styling overhaul of the dialog itself

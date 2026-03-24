# Vendor Dropdown Overlap Fix — Design Spec

**Date:** 2026-03-23
**Status:** Approved

## Problem

When a user types a vendor name, a floating dropdown appears (`position: absolute; z-index: 10`). The dropdown contains matching vendors plus a "+ Add as new vendor…" item. Clicking an existing vendor clears the dropdown via `onclick`. Clicking "+ Add as new vendor…" loads the new vendor form into `#new-vendor-section` via HTMX but does **not** clear the dropdown — the dropdown stays open and floats over the new vendor form, blocking it.

## Fix

Add `onclick="document.getElementById('vendor-dropdown').innerHTML=''"` to the "+ Add as new vendor…" item in `web/templates/partials/vendor_dropdown.html`.

This is the exact same pattern used by the existing vendor items, which already clear `#vendor-dropdown` (and `#new-vendor-section`) via `onclick`.

## File Changed

- **Modify:** `web/templates/partials/vendor_dropdown.html` — add `onclick` to the "+ Add" div

No server-side changes. No other templates affected.

## No Tests Required

This is a pure template behavior fix. The existing test `test_vendor_search_returns_html` confirms the route works. The dropdown-clearing behavior is client-side JavaScript with no server-side logic to test.

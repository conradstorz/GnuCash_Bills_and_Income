# Vendor Dropdown Overlap Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear the vendor dropdown when the user clicks "+ Add as new vendor…" so it no longer overlaps the new vendor form.

**Architecture:** The dropdown uses `position: absolute` and floats over the page. Existing vendor items already clear the dropdown via `onclick`. The "+ Add" item uses HTMX but lacks this `onclick` — adding it fixes the overlap.

**Tech Stack:** Jinja2 template, inline JavaScript, HTMX

---

## Files

- Modify: `web/templates/partials/vendor_dropdown.html` — add `onclick` to the "+ Add" div

---

## Task 1: Clear dropdown on "+ Add as new vendor" click

**Files:**
- Modify: `web/templates/partials/vendor_dropdown.html`

No server-side logic changes. No new tests required (client-side DOM mutation; the server route is already covered by `test_vendor_search_returns_html`).

- [ ] **Step 1: Read the current template**

Read `web/templates/partials/vendor_dropdown.html` to confirm the exact current state of the "+ Add" div (lines 12–17):

```html
<div class="dropdown-item" style="color:#888; font-style:italic"
     hx-get="/vendors/new-form?name={{ query | urlencode }}"
     hx-target="#new-vendor-section"
     hx-swap="innerHTML">
  + Add &ldquo;{{ query | e }}&rdquo; as new vendor&hellip;
</div>
```

- [ ] **Step 2: Add `onclick` to clear the dropdown**

Add `onclick="document.getElementById('vendor-dropdown').innerHTML=''"` to the div:

```html
<div class="dropdown-item" style="color:#888; font-style:italic"
     onclick="document.getElementById('vendor-dropdown').innerHTML=''"
     hx-get="/vendors/new-form?name={{ query | urlencode }}"
     hx-target="#new-vendor-section"
     hx-swap="innerHTML">
  + Add &ldquo;{{ query | e }}&rdquo; as new vendor&hellip;
</div>
```

**Why only `#vendor-dropdown`:** The existing vendor items also clear `#new-vendor-section` because selecting an existing vendor should close any open new-vendor form. The "+ Add" path is intentionally loading content *into* `#new-vendor-section`, so it must not clear it.

- [ ] **Step 3: Run the existing test suite to confirm nothing broke**

```
uv run pytest tests/test_web_app.py -q
```

Expected: all pass (no new failures).

- [ ] **Step 4: Commit**

```
git add web/templates/partials/vendor_dropdown.html
git commit -m "fix: clear vendor dropdown when opening new vendor form"
```

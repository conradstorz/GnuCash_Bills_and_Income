# Vendor Form Nested-Form Bug Fix Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all three vendor-creation-window bugs (window closes unexpectedly, Enter key submits outer form, candidate selection doesn't work) by replacing the illegal nested `<form>` in `new_vendor_form.html` with a `<div>` and wiring HTMX directly to the Create button.

**Architecture:** The outer bill-entry `<form>` in `bill_entry.html` wraps `#new-vendor-section`. When HTMX injects `new_vendor_form.html` via `innerHTML`, the browser's HTML5 fragment parser sees a second `<form>` opening tag inside an already-open form ancestor and silently strips it — this is defined behavior in the spec, not a browser bug. Removing the inner `<form>` element and putting HTMX attributes directly on the Create button is the minimal, standards-compliant fix.

**Tech Stack:** Jinja2 templates, HTMX 1.x, FastAPI

---

## Root Cause Analysis

### The Bug

`#new-vendor-section` (line 11, `web/templates/bill_entry.html`) lives **inside** the outer bill-entry `<form>`:

```html
<!-- bill_entry.html -->
<form hx-post="/bills/queue" hx-target="#bill-entry-form" hx-swap="innerHTML">
  <input type="text" name="vendor_name" id="vendor-input" ...>
  <div id="vendor-dropdown"></div>
  <div id="new-vendor-section"></div>   ← injection target IS INSIDE outer form
  <input type="number" name="amount" ...>
  ...
  <button type="submit" class="btn-primary">Add to Queue</button>
</form>
```

When HTMX injects `new_vendor_form.html` into `#new-vendor-section` via `element.innerHTML = htmlString`, the browser parses the fragment **in the context of the current DOM node**, which is already inside a `<form>`. Per the [HTML5 parsing spec §8.4](https://html.spec.whatwg.org/multipage/parsing.html#parsing-main-inbody), a `<form>` start tag encountered while a form element is already open is treated as a **parse error and the tag is ignored**. The inner form's attributes (`hx-post="/vendors/create"`, etc.) are stripped from the DOM entirely.

### Three Symptoms — One Root Cause

| Symptom | Mechanism |
|---|---|
| Vendor window closes when clicking "Create Vendor" | Create button has `type="submit"` → submits **outer** bill-entry form → HTMX replaces `#bill-entry-form` → vendor form disappears |
| Vendor window closes when pressing Enter in any field | Enter in form field triggers default form submission → same outer form submission |
| "Enter details manually" message appears with closed box | `hx-trigger="load"` on `#address-candidates` fires and swaps in error message from `/vendors/lookup-address`, but the form is already gone because Enter or Create submitted the outer form first |
| Can't select a candidate or refine search | `hx-post="/vendors/create"` on the stripped `<form>` is never registered with HTMX — the element doesn't exist in the DOM |

### Why It Was Hard to Notice During Development

HTMX's `hx-include="closest form"` on the city/ZIP refinement inputs **accidentally still worked** because after stripping, the outer bill-entry form is the closest ancestor form. The outer form includes `display_name` (now a live DOM input in the outer form context), so search queries happened to include the vendor name. The address-lookup refinement appeared functional during testing.

---

## The Fix

**One file to change:** `web/templates/partials/new_vendor_form.html`

Replace the inner `<form>` element with a `<div>`, move HTMX POST attributes to the Create button (now `type="button"`), update `hx-include` selectors to target the form div by ID, and add an Enter-key trap on the wrapper div.

**No Python changes required.** The `/vendors/create` route already reads all fields via `Form("")` parameters — it doesn't care whether they came from a `<form>` submit or an HTMX request triggered by a button.

---

## Task 1: Fix `new_vendor_form.html`

**Files:**
- Modify: `web/templates/partials/new_vendor_form.html`

- [ ] **Step 1: Write a failing test that demonstrates the nested-form behavior**

  Add to `tests/test_web_app.py`. This test verifies that clicking "Create Vendor" does NOT submit the bill-entry queue form:

  ```python
  def test_create_vendor_does_not_submit_bill_queue(client):
      """
      The /vendors/create endpoint must be reachable via POST independently
      of /bills/queue. If the inner form were correctly wired, a POST to
      /vendors/create with a valid display_name should return 200/redirect,
      NOT a 422 from /bills/queue's required 'amount' field.
      """
      resp = client.post("/vendors/create", data={
          "vendor_name": "Test Co",
          "display_name": "Test Co",
          "addr_line1": "",
          "addr_line2": "",
          "addr_city": "",
          "addr_state": "",
          "addr_zip": "",
          "addr_phone": "",
      }, follow_redirects=False)
      # Should not be a 422 (which would mean /bills/queue rejected it for
      # missing required 'amount' field)
      assert resp.status_code != 422, (
          "POST /vendors/create returned 422 — this indicates the request "
          "was routed to /bills/queue instead, which means the inner form "
          "is either missing or wired to the wrong endpoint."
      )
  ```

- [ ] **Step 2: Run test to verify it fails (or passes trivially — see note)**

  ```bash
  uv run pytest tests/test_web_app.py::test_create_vendor_does_not_submit_bill_queue -v
  ```

  Note: This test verifies the *server-side route* is correct, not the DOM stripping (which is browser-side). The route itself should work. The DOM fix below is the real guard. This test serves as a regression anchor.

- [ ] **Step 3: Replace the inner `<form>` with a `<div>` in `new_vendor_form.html`**

  Replace the entire file with:

  ```html
  <div id="new-vendor-form"
       onkeydown="if(event.key==='Enter' && event.target.tagName!=='BUTTON'){event.preventDefault();}">
    <strong>New Vendor: {{ vendor_name | e }}</strong>
    {% if message %}<p class="error-msg" style="margin-top:0.3rem">{{ message | e }}</p>{% endif %}

    <input type="hidden" id="new-vendor-name" value="{{ vendor_name | e }}">

    <label for="new-vendor-display-name">Display Name</label>
    <input type="text" id="new-vendor-display-name"
           value="{{ display_name | e }}">

    <div id="address-candidates"
         hx-post="/vendors/lookup-address"
         hx-trigger="load"
         hx-swap="innerHTML"
         hx-vals='{"display_name": {{ display_name | tojson }}}'>
    </div>

    <label for="new-vendor-addr1">Address Line 1</label>
    <input type="text" id="new-vendor-addr1" value="{{ addr_line1 | e }}">

    <label for="new-vendor-addr2">Address Line 2</label>
    <input type="text" id="new-vendor-addr2" value="{{ addr_line2 | e }}">

    <label for="new-vendor-city">City</label>
    <input type="text" id="new-vendor-city" value="{{ addr_city | e }}"
           hx-post="/vendors/lookup-address"
           hx-trigger="keyup changed delay:500ms"
           hx-target="#address-candidates"
           hx-swap="innerHTML"
           hx-include="#new-vendor-form input">

    <div style="display:flex; gap:1rem">
      <div style="flex:1">
        <label for="new-vendor-state">State</label>
        <input type="text" id="new-vendor-state"
               value="{{ addr_state | e }}" style="width:100%">
      </div>
      <div style="flex:1">
        <label for="new-vendor-zip">ZIP</label>
        <input type="text" id="new-vendor-zip"
               value="{{ addr_zip | e }}" style="width:100%"
               hx-post="/vendors/lookup-address"
               hx-trigger="keyup changed delay:500ms"
               hx-target="#address-candidates"
               hx-swap="innerHTML"
               hx-include="#new-vendor-form input">
      </div>
    </div>

    <label for="new-vendor-phone">Phone</label>
    <input type="text" id="new-vendor-phone" value="{{ addr_phone | e }}">

    <div style="margin-top:0.75rem; display:flex; gap:0.5rem">
      <button type="button" class="btn-primary"
              hx-post="/vendors/create"
              hx-target="#new-vendor-section"
              hx-swap="innerHTML"
              hx-include="#new-vendor-form input"
              hx-vals='{"vendor_name": {{ vendor_name | tojson }}}'>
        Create Vendor
      </button>
      <button type="button"
        onclick="document.getElementById('new-vendor-section').innerHTML='';document.getElementById('vendor-dropdown').innerHTML='';document.getElementById('vendor-input').value='';">
        Cancel
      </button>
    </div>
  </div>
  ```

  **Key changes from the old template:**
  | Old | New | Why |
  |---|---|---|
  | `<form hx-post="/vendors/create">` | `<div id="new-vendor-form">` | Eliminates nested form; browser no longer strips it |
  | `<input type="hidden" name="vendor_name">` | `<input type="hidden" id="new-vendor-name">` | No `name` needed — not in a form; value captured via `hx-include` or `hx-vals` |
  | All inputs have `name=` attributes | All inputs have only `id=` attributes | HTMX's `hx-include` picks up values by element, not by form submission |
  | `hx-include="closest form"` on city/ZIP | `hx-include="#new-vendor-form input"` | Explicitly targets only vendor form inputs, not the outer bill-entry form |
  | `<button type="submit" class="btn-primary">` | `<button type="button" ... hx-post="/vendors/create">` | `type="button"` never triggers form submission; HTMX fires the POST explicitly |
  | `required` on display_name | _(removed)_ | HTML5 `required` only enforces at form submission — server-side validation is the guard |
  | `onkeydown` not present | `onkeydown="if(event.key==='Enter' && event.target.tagName!=='BUTTON'){event.preventDefault();}"` | Prevents Enter from bubbling up and triggering the outer form's submit button |

- [ ] **Step 4: Update the `/vendors/create` route to read inputs sent by `hx-include`**

  `hx-include="#new-vendor-form input"` will post all `<input>` values using their `id` as the field name (HTMX uses the `name` attribute if present, otherwise falls back to `id`). The current route reads `Form("")` parameters by name. We need to ensure the field names match.

  Check `web/app.py` `/vendors/create` route parameter names vs. the new input IDs:

  | Input `id` | Route parameter name | Match? |
  |---|---|---|
  | `new-vendor-name` | `vendor_name` | ❌ mismatch — use `hx-vals` to pass vendor_name |
  | `new-vendor-display-name` | `display_name` | ❌ mismatch |
  | `new-vendor-addr1` | `addr_line1` | ❌ mismatch |
  | `new-vendor-addr2` | `addr_line2` | ❌ mismatch |
  | `new-vendor-city` | `addr_city` | ❌ mismatch |
  | `new-vendor-state` | `addr_state` | ❌ mismatch |
  | `new-vendor-zip` | `addr_zip` | ❌ mismatch |
  | `new-vendor-phone` | `addr_phone` | ❌ mismatch |

  **Important:** HTMX `hx-include` serializes inputs using their `name` attribute. If `name` is absent, the input is **skipped**. The revised template above must add `name` attributes back to all inputs (but not `<form>` as container). Update the template in Step 3 to add `name` attributes alongside `id` on each input:

  ```html
  <input type="hidden" name="vendor_name" id="new-vendor-name" value="{{ vendor_name | e }}">
  <input type="text"   name="display_name" id="new-vendor-display-name" value="{{ display_name | e }}">
  <input type="text"   name="addr_line1"   id="new-vendor-addr1"         value="{{ addr_line1 | e }}">
  <input type="text"   name="addr_line2"   id="new-vendor-addr2"         value="{{ addr_line2 | e }}">
  <input type="text"   name="addr_city"    id="new-vendor-city"          value="{{ addr_city | e }}"   ...>
  <input type="text"   name="addr_state"   id="new-vendor-state"         value="{{ addr_state | e }}"  ...>
  <input type="text"   name="addr_zip"     id="new-vendor-zip"           value="{{ addr_zip | e }}"    ...>
  <input type="text"   name="addr_phone"   id="new-vendor-phone"         value="{{ addr_phone | e }}">
  ```

  Remove the `hx-vals='{"vendor_name": ...}'` from the Create button (vendor_name is already on the hidden input). Also update `hx-include` on city/ZIP and the Create button to `#new-vendor-form input` (unchanged from above — this now works since `name` attributes are present).

  No changes to `web/app.py` are needed — the route parameter names already match.

- [ ] **Step 5: Write the corrected final version of `new_vendor_form.html`**

  The complete correct file (incorporating Step 3 + Step 4 corrections):

  ```html
  <div id="new-vendor-form"
       onkeydown="if(event.key==='Enter' && event.target.tagName!=='BUTTON'){event.preventDefault();}">
    <strong>New Vendor: {{ vendor_name | e }}</strong>
    {% if message %}<p class="error-msg" style="margin-top:0.3rem">{{ message | e }}</p>{% endif %}

    <input type="hidden" name="vendor_name" id="new-vendor-name" value="{{ vendor_name | e }}">

    <label for="new-vendor-display-name">Display Name</label>
    <input type="text" name="display_name" id="new-vendor-display-name"
           value="{{ display_name | e }}">

    <div id="address-candidates"
         hx-post="/vendors/lookup-address"
         hx-trigger="load"
         hx-swap="innerHTML"
         hx-vals='{"display_name": {{ display_name | tojson }}}'>
    </div>

    <label for="new-vendor-addr1">Address Line 1</label>
    <input type="text" name="addr_line1" id="new-vendor-addr1" value="{{ addr_line1 | e }}">

    <label for="new-vendor-addr2">Address Line 2</label>
    <input type="text" name="addr_line2" id="new-vendor-addr2" value="{{ addr_line2 | e }}">

    <label for="new-vendor-city">City</label>
    <input type="text" name="addr_city" id="new-vendor-city" value="{{ addr_city | e }}"
           hx-post="/vendors/lookup-address"
           hx-trigger="keyup changed delay:500ms"
           hx-target="#address-candidates"
           hx-swap="innerHTML"
           hx-include="#new-vendor-form input">

    <div style="display:flex; gap:1rem">
      <div style="flex:1">
        <label for="new-vendor-state">State</label>
        <input type="text" name="addr_state" id="new-vendor-state"
               value="{{ addr_state | e }}" style="width:100%">
      </div>
      <div style="flex:1">
        <label for="new-vendor-zip">ZIP</label>
        <input type="text" name="addr_zip" id="new-vendor-zip"
               value="{{ addr_zip | e }}" style="width:100%"
               hx-post="/vendors/lookup-address"
               hx-trigger="keyup changed delay:500ms"
               hx-target="#address-candidates"
               hx-swap="innerHTML"
               hx-include="#new-vendor-form input">
      </div>
    </div>

    <label for="new-vendor-phone">Phone</label>
    <input type="text" name="addr_phone" id="new-vendor-phone" value="{{ addr_phone | e }}">

    <div style="margin-top:0.75rem; display:flex; gap:0.5rem">
      <button type="button" class="btn-primary"
              hx-post="/vendors/create"
              hx-target="#new-vendor-section"
              hx-swap="innerHTML"
              hx-include="#new-vendor-form input">
        Create Vendor
      </button>
      <button type="button"
        onclick="document.getElementById('new-vendor-section').innerHTML='';document.getElementById('vendor-dropdown').innerHTML='';document.getElementById('vendor-input').value='';">
        Cancel
      </button>
    </div>
  </div>
  ```

- [ ] **Step 6: Run the full test suite**

  ```bash
  uv run pytest tests/ -v
  ```

  Expected: all tests pass (51+).

- [ ] **Step 7: Commit**

  ```bash
  git add web/templates/partials/new_vendor_form.html
  git commit -m "fix: replace nested form with div to fix vendor window closing unexpectedly

  The inner <form hx-post='/vendors/create'> in new_vendor_form.html was
  injected via HTMX innerHTML into #new-vendor-section, which lives inside
  the outer bill-entry <form>. The HTML5 fragment parser strips inner <form>
  tags as parse errors when a form ancestor is already open, so the inner
  form's HTMX attributes never reached the DOM.

  Result: Create Vendor button (type=submit) submitted the outer bill-entry
  form instead, collapsing the vendor window. Enter key in any vendor field
  had the same effect.

  Fix: replace <form> with <div id='new-vendor-form'>, change Create button
  to type=button with explicit hx-post/hx-include, add Enter key trap on the
  wrapper div, update hx-include selectors from 'closest form' to
  '#new-vendor-form input'."
  ```

---

## Verification

After implementing, manually verify:
- [ ] Open new vendor form, press Enter in Display Name field → window does NOT close
- [ ] Open new vendor form, press Enter in City field → window does NOT close, address search fires
- [ ] Type a vendor name, open form, wait for address candidates → candidates appear
- [ ] Click a candidate → fields populate, candidates clear
- [ ] Add city refinement → candidates update
- [ ] Click Create Vendor → vendor is created, form closes, vendor name populates the vendor field
- [ ] Click Cancel → form closes, vendor input cleared

# Vendor Form Dialog Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the inline HTMX vendor creation form with a browser-native `<dialog>` managed by vanilla JS, eliminating DOM conflicts that cause the form to close randomly.

**Architecture:** The new vendor form moves into a `<dialog>` element in `dashboard.html`, outside the bill entry form. A new `vendor-form.js` module manages the dialog lifecycle and communicates with the backend via `fetch()` + `FormData`. Two backend routes switch from HTML to JSON responses. The rest of the app stays pure HTMX.

**Tech Stack:** FastAPI, Jinja2, vanilla JavaScript (ES module), HTML `<dialog>` element, HTMX (existing, unchanged for other features)

**Spec:** `docs/superpowers/specs/2026-03-24-vendor-form-dialog-refactor-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `web/static/vendor-form.js` | Dialog lifecycle, address lookup via fetch, vendor creation via fetch |
| Modify | `web/app.py` | `/vendors/lookup-address` and `/vendors/create` return JSON; delete `/vendors/new-form` route |
| Modify | `web/templates/dashboard.html` | Add `<dialog>` block and `<script>` tag |
| Modify | `web/templates/bill_entry.html` | Remove `#new-vendor-section` div |
| Modify | `web/templates/partials/vendor_dropdown.html` | Replace HTMX add-vendor link with `VendorForm.open()` call; clean up `#new-vendor-section` references |
| Modify | `web/static/style.css` | Add dialog styling |
| Modify | `tests/test_web_app.py` | Delete 7 tests, rewrite 3 tests, add 1 new test for JSON/dialog responses |
| Delete | `web/templates/partials/new_vendor_form.html` | Replaced by dialog in dashboard.html |
| Delete | `web/templates/partials/address_candidates.html` | Rendered by JS from JSON |

---

### Task 1: Backend — Convert `/vendors/lookup-address` to JSON response

**Files:**
- Modify: `web/app.py:348-376`
- Modify: `tests/test_web_app.py:141-146, 650-663`

- [ ] **Step 1: Write failing test for JSON response from lookup-address**

In `tests/test_web_app.py`, replace `test_address_lookup_returns_form` (line 141) with:

```python
def test_address_lookup_returns_json(client):
    """Address lookup returns JSON with candidates list and message."""
    response = client.post("/vendors/lookup-address", data={"vendor_name": "Acme Electric"})
    assert response.status_code == 200
    data = response.json()
    assert "candidates" in data
    assert "message" in data
    assert isinstance(data["candidates"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_app.py::test_address_lookup_returns_json -v`
Expected: FAIL — response is HTML, not JSON

- [ ] **Step 3: Convert route to return JSON**

In `web/app.py`, replace the `/vendors/lookup-address` route (lines 348-376). Note: remove `response_class=HTMLResponse` from the decorator — the route now returns `JSONResponse`. Replace with:

```python
@app.post("/vendors/lookup-address")
def lookup_address(
    request: Request,
    vendor_name: str = Form(""),
    display_name: str = Form(""),
    addr_city: str = Form(""),
    addr_zip: str = Form(""),
):
    """Look up address candidates and return JSON."""
    parts = [p.strip() for p in [display_name, addr_city, addr_zip] if p.strip()]
    if not parts:
        parts = [vendor_name.strip()]
    search_name = " ".join(parts)
    candidates = []
    message = ""
    try:
        candidates = addr_lookup.lookup_google_places(search_name, return_all=True) or []
        if not candidates:
            candidates = addr_lookup.lookup_openstreetmap(search_name, return_all=True) or []
        if not candidates:
            message = "No results found — enter address manually"
    except Exception as e:
        logger.warning(f"Address lookup failed for '{search_name}': {e}")
        message = "Address lookup unavailable — enter manually"

    return JSONResponse({
        "candidates": candidates,
        "message": message,
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_web_app.py::test_address_lookup_returns_json -v`
Expected: PASS

- [ ] **Step 5: Delete obsolete tests**

Delete `test_address_candidates_height_shows_three` (lines 650-663) — it asserts HTML/CSS from the deleted `address_candidates.html` template. Note: `test_address_lookup_returns_form` was already replaced with `test_address_lookup_returns_json` in Step 1. Verify `test_lookup_address_combines_city_and_zip` (line 149) still passes — it only checks the monkeypatched query string, not the response format.

Run: `uv run pytest tests/test_web_app.py -k "address" -v`
Expected: all remaining address tests pass

- [ ] **Step 6: Commit**

```
git add web/app.py tests/test_web_app.py
git commit -m "refactor: /vendors/lookup-address returns JSON instead of HTML"
```

---

### Task 2: Backend — Convert `/vendors/create` to JSON response

**Files:**
- Modify: `web/app.py:379-429`
- Modify: `tests/test_web_app.py:238-244`

- [ ] **Step 1: Write failing test for JSON response from create**

Replace `test_create_vendor_empty_name_rejected` (line 238) with:

```python
def test_create_vendor_empty_name_returns_json_error(client):
    """Creating a vendor with empty name returns JSON error."""
    response = client.post("/vendors/create", data={
        "vendor_name": "",
        "display_name": "",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "required" in data["error"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_web_app.py::test_create_vendor_empty_name_returns_json_error -v`
Expected: FAIL — response is HTML, not JSON

- [ ] **Step 3: Convert route to return JSON**

In `web/app.py`, replace the `/vendors/create` route (lines 379-429). Note: remove `response_class=HTMLResponse` from the decorator — the route now returns `JSONResponse`. Replace with:

```python
@app.post("/vendors/create")
def create_vendor_route(
    request: Request,
    vendor_name: str = Form(""),
    display_name: str = Form(""),
    addr_line1: str = Form(""),
    addr_line2: str = Form(""),
    addr_city: str = Form(""),
    addr_state: str = Form(""),
    addr_zip: str = Form(""),
    addr_phone: str = Form(""),
):
    """Create vendor in GnuCash + JSON cache, return JSON result."""
    display_name = display_name.strip() or vendor_name.strip()
    if not display_name:
        return JSONResponse({"ok": False, "error": "Vendor name is required."})

    try:
        guid = gnucash_db.create_vendor(
            name=display_name,
            addr_name=display_name,
            addr_addr1=addr_line1,
            addr_addr2=addr_line2,
            addr_city=addr_city,
            addr_state=addr_state,
            addr_zip=addr_zip,
            addr_phone=addr_phone,
        )
        # Cache in JSON vendor database
        vm = VendorManager()
        key = strip_vendor_name(display_name)
        vm.vendors["vendors"][key] = {
            "display_name": display_name,
            "gnucash_guid": guid,
            "addr_line1": addr_line1,
            "addr_line2": addr_line2,
            "addr_city": addr_city,
            "addr_state": addr_state,
            "addr_zip": addr_zip,
            "addr_phone": addr_phone,
        }
        vm.save()
        logger.info(f"Created vendor '{display_name}' with GUID {guid}")
        return JSONResponse({"ok": True, "display_name": display_name, "guid": guid})
    except Exception as e:
        logger.error(f"Failed to create vendor '{display_name}': {e}")
        return JSONResponse({"ok": False, "error": str(e)})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_web_app.py::test_create_vendor_empty_name_returns_json_error -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
git add web/app.py tests/test_web_app.py
git commit -m "refactor: /vendors/create returns JSON instead of HTML+script"
```

---

### Task 3: Backend — Delete `/vendors/new-form` route and its tests

**Files:**
- Modify: `web/app.py:332-345`
- Modify: `tests/test_web_app.py:88-138`

- [ ] **Step 1: Delete the route**

Remove the `/vendors/new-form` route from `web/app.py` (lines 332-345):

```python
# DELETE THIS ENTIRE BLOCK:
@app.get("/vendors/new-form", response_class=HTMLResponse)
def new_vendor_form(request: Request, name: str = ""):
    """Return the new vendor inline creation form."""
    return templates.TemplateResponse(request, "partials/new_vendor_form.html", {
        ...
    })
```

- [ ] **Step 2: Delete all 6 tests for this route**

Remove these test functions from `tests/test_web_app.py`:
- `test_new_vendor_form_renders` (line 88)
- `test_new_vendor_form_auto_fires_address_search_on_load` (line 94)
- `test_new_vendor_form_hx_vals_contains_display_name` (line 103)
- `test_new_vendor_form_city_zip_have_refinement_triggers` (line 112)
- `test_new_vendor_form_no_lookup_button` (line 121)
- `test_new_vendor_form_cancel_clears_vendor_input` (line 128)

- [ ] **Step 3: Run all remaining tests to verify nothing else depends on this route**

Run: `uv run pytest tests/test_web_app.py -v`
Expected: all remaining tests pass. Note: `test_vendor_dropdown_add_item_uses_after_request_not_onclick` (line 639) hits `GET /vendors/search` which renders `vendor_dropdown.html` — this template still references `/vendors/new-form` as an attribute string, but the test only checks rendered HTML, not route reachability. This test will be rewritten in Task 4 Step 6.

- [ ] **Step 4: Commit**

```
git add web/app.py tests/test_web_app.py
git commit -m "refactor: delete /vendors/new-form route (replaced by dialog)"
```

---

### Task 4: Templates — Add `<dialog>` to dashboard, clean up bill_entry and vendor_dropdown

**Files:**
- Modify: `web/templates/dashboard.html:50-52`
- Modify: `web/templates/bill_entry.html:11`
- Modify: `web/templates/partials/vendor_dropdown.html:1-19`
- Modify: `web/static/style.css`
- Delete: `web/templates/partials/new_vendor_form.html`
- Delete: `web/templates/partials/address_candidates.html`

- [ ] **Step 1: Add dialog block to dashboard.html**

Before the closing `{% endblock %}` (line 52), add:

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

- [ ] **Step 2: Remove `#new-vendor-section` from bill_entry.html**

Delete line 11 from `web/templates/bill_entry.html`:

```html
  <div id="new-vendor-section"></div>
```

- [ ] **Step 3: Update vendor_dropdown.html**

Replace the entire file `web/templates/partials/vendor_dropdown.html` with:

```html
<div class="dropdown-list">
  {% for vendor in results %}
  <div class="dropdown-item"
       onclick='
         document.getElementById("vendor-input").value = {{ vendor.display_name | tojson }};
         document.getElementById("vendor-dropdown").innerHTML = "";
       '>
    {{ vendor.display_name }}
  </div>
  {% endfor %}
  <div class="dropdown-item" style="color:#888; font-style:italic"
       onclick="VendorForm.open({{ query | tojson }})">
    + Add &ldquo;{{ query | e }}&rdquo; as new vendor&hellip;
  </div>
</div>
```

Changes from the original:
1. Removed `document.getElementById("new-vendor-section").innerHTML = ""` from existing vendor onclick (line 7) — element no longer exists.
2. Replaced HTMX `hx-get="/vendors/new-form"` + `hx-on::after-request` on the "+ Add" item with `onclick="VendorForm.open(...)"`.

- [ ] **Step 4: Add dialog CSS to style.css**

Append to `web/static/style.css`:

```css
/* Vendor creation dialog */
#vendor-dialog {
  max-width: 32rem;
  border-radius: 6px;
  border: 1px solid #ccc;
  padding: 1.5rem;
}
#vendor-dialog::backdrop {
  background: rgba(0, 0, 0, 0.4);
}
#vendor-dialog label {
  display: block;
  margin-top: 0.5rem;
  font-weight: 600;
  font-size: 0.9rem;
}
#vendor-dialog input[type="text"] {
  width: 100%;
  box-sizing: border-box;
}
#vf-candidates .candidate-item {
  padding: 0.4rem 0.6rem;
  border-top: 1px solid #eee;
  cursor: pointer;
}
#vf-candidates .candidate-item:hover {
  background: #f0f0f0;
}
```

- [ ] **Step 5: Delete obsolete templates**

Delete these files:
- `web/templates/partials/new_vendor_form.html`
- `web/templates/partials/address_candidates.html`

- [ ] **Step 6: Update the vendor_dropdown test**

Replace `test_vendor_dropdown_add_item_uses_after_request_not_onclick` (line 639) in `tests/test_web_app.py` with:

```python
def test_vendor_dropdown_add_item_uses_vendor_form_open(client):
    """The '+ Add' item opens the vendor dialog via VendorForm.open()."""
    response = client.get("/vendors/search", params={"vendor_name": "TestQuery"})
    assert response.status_code == 200
    html = response.text
    assert "VendorForm.open(" in html
    # Old HTMX attributes and route reference must be gone
    assert "/vendors/new-form" not in html
    assert "hx-on::after-request" not in html
```

- [ ] **Step 7: Add test that dashboard includes the dialog and script**

Add to `tests/test_web_app.py`:

```python
def test_dashboard_includes_vendor_dialog(client):
    """Dashboard renders the vendor creation dialog and loads vendor-form.js."""
    response = client.get("/")
    assert response.status_code == 200
    assert b'id="vendor-dialog"' in response.content
    assert b"vendor-form.js" in response.content
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest tests/test_web_app.py -v`
Expected: all tests pass

- [ ] **Step 9: Commit**

```
git add web/templates/ web/static/style.css tests/test_web_app.py
git commit -m "refactor: add vendor dialog to dashboard, remove inline form templates"
```

---

### Task 5: Create `vendor-form.js` — dialog lifecycle and address lookup

**Files:**
- Create: `web/static/vendor-form.js`

- [ ] **Step 1: Create the vendor-form.js module**

Create `web/static/vendor-form.js`:

```javascript
/**
 * Vendor creation dialog manager.
 *
 * Opens a <dialog> for creating new vendors, handles address lookup
 * via fetch(), and populates #vendor-input on success.
 */
const VendorForm = (() => {
  // --- DOM references (resolved once) ---
  let dialog, title, error, displayName, addr1, addr2, city, state, zip, phone, candidates;
  let debounceTimer = null;
  let vendorName = "";  // original typed name, sent as vendor_name for backend fallback

  function init() {
    dialog = document.getElementById("vendor-dialog");
    title = document.getElementById("vf-title");
    error = document.getElementById("vf-error");
    displayName = document.getElementById("vf-display-name");
    addr1 = document.getElementById("vf-addr1");
    addr2 = document.getElementById("vf-addr2");
    city = document.getElementById("vf-city");
    state = document.getElementById("vf-state");
    zip = document.getElementById("vf-zip");
    phone = document.getElementById("vf-phone");
    candidates = document.getElementById("vf-candidates");

    if (!dialog) return;

    // Close on backdrop click
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) close();
    });

    // Debounced address re-lookup on city/zip change
    city.addEventListener("input", () => debouncedLookup());
    zip.addEventListener("input", () => debouncedLookup());
  }

  function open(name) {
    vendorName = name;
    // Clear previous state
    title.textContent = name;
    displayName.value = name;
    error.style.display = "none";
    error.textContent = "";
    addr1.value = "";
    addr2.value = "";
    city.value = "";
    state.value = "";
    zip.value = "";
    phone.value = "";
    candidates.innerHTML = "";

    // Clear the vendor dropdown behind us
    document.getElementById("vendor-dropdown").innerHTML = "";

    dialog.showModal();
    lookupAddress();
  }

  function close() {
    dialog.close();
    candidates.innerHTML = "";
    clearTimeout(debounceTimer);
  }

  function debouncedLookup() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(lookupAddress, 500);
  }

  async function lookupAddress() {
    const formData = new FormData();
    formData.append("vendor_name", vendorName);
    formData.append("display_name", displayName.value);
    formData.append("addr_city", city.value);
    formData.append("addr_zip", zip.value);

    try {
      const resp = await fetch("/vendors/lookup-address", {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      renderCandidates(data.candidates, data.message);
    } catch (err) {
      renderCandidates([], "Address lookup unavailable");
    }
  }

  function renderCandidates(items, message) {
    if (!items || items.length === 0) {
      candidates.innerHTML = message
        ? `<p class="error-msg" style="margin-top:0.25rem">${escapeHtml(message)}</p>`
        : "";
      return;
    }

    let html = `<div style="margin-top:0.25rem; border:1px solid #aaa; border-radius:4px; overflow:hidden">`;
    html += `<div style="padding:0.3rem 0.6rem; background:#f5f5f5; font-size:0.8rem; color:#555">`;
    html += `${items.length} result${items.length !== 1 ? "s" : ""} — select a match or edit the fields below manually</div>`;
    html += `<div style="max-height:9rem; overflow-y:auto">`;

    items.forEach((c, i) => {
      const dist = c.distance != null ? ` <span style="color:#888; font-size:0.85rem">(${c.distance.toFixed(1)} mi)</span>` : "";
      html += `<div class="candidate-item" data-index="${i}" onclick="VendorForm._selectCandidate(this, ${i})">`;
      html += `<strong>${escapeHtml(c.name)}</strong>${dist}`;
      html += `<br><small style="color:#555">${escapeHtml(c.formatted_address)}</small>`;
      html += `</div>`;
    });

    html += `</div></div>`;
    candidates.innerHTML = html;

    // Store candidate data for selection
    candidates._data = items;
  }

  function selectCandidate(el, index) {
    const c = candidates._data[index];
    if (!c) return;

    addr1.value = c.addr_line1 || "";
    // Parse "City, ST ZIP" from addr_line2 (US format; non-US leaves city/state/zip blank)
    const a2 = c.addr_line2 || "";
    const m = a2.match(/^(.*),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$/);
    addr2.value = "";
    city.value = m ? m[1] : "";
    state.value = m ? m[2] : "";
    zip.value = m ? m[3] : "";
    phone.value = c.phone || "";
    candidates.innerHTML = "";
  }

  async function create() {
    const name = displayName.value.trim();
    if (!name) {
      showError("Display name is required.");
      return;
    }

    const formData = new FormData();
    formData.append("vendor_name", vendorName);
    formData.append("display_name", name);
    formData.append("addr_line1", addr1.value);
    formData.append("addr_line2", addr2.value);
    formData.append("addr_city", city.value);
    formData.append("addr_state", state.value);
    formData.append("addr_zip", zip.value);
    formData.append("addr_phone", phone.value);

    try {
      const resp = await fetch("/vendors/create", {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      if (data.ok) {
        document.getElementById("vendor-input").value = data.display_name;
        close();
      } else {
        showError(data.error || "Failed to create vendor.");
      }
    } catch (err) {
      showError("Request failed — check your connection.");
    }
  }

  function showError(msg) {
    error.textContent = msg;
    error.style.display = "block";
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // Initialize when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  return { open, close, create, _selectCandidate: selectCandidate };
})();
```

- [ ] **Step 2: Manual smoke test**

Start the server: `uv run uvicorn bill_processor.web.app:app --reload --port 7432`

Test the full flow:
1. Open http://localhost:7432
2. Type a vendor name in the bill entry form
3. Click "+ Add ... as new vendor" — dialog should open with backdrop
4. Verify address candidates load (or "no results" message appears)
5. Edit city or zip — candidates should refresh after 500ms
6. Click a candidate — address fields populate
7. Click "Create Vendor" — dialog closes, vendor name appears in input
8. Click "Cancel" instead — dialog closes, input unchanged
9. Press Escape — dialog closes
10. Click backdrop — dialog closes

- [ ] **Step 3: Commit**

```
git add web/static/vendor-form.js
git commit -m "feat: add vendor-form.js dialog manager for vendor creation"
```

---

### Task 6: Final verification — run full test suite

**Files:** None (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 2: Run just the web app tests to confirm no regressions**

Run: `uv run pytest tests/test_web_app.py -v`
Expected: all tests pass, no references to deleted routes or templates

- [ ] **Step 3: Verify deleted files are gone**

Confirm these files no longer exist:
- `web/templates/partials/new_vendor_form.html`
- `web/templates/partials/address_candidates.html`

Confirm the `/vendors/new-form` route does not exist in `web/app.py`.

- [ ] **Step 4: Final commit if any cleanup needed, then tag completion**

If all clean:
```
git log --oneline -6
```

Expected commit history (newest first):
1. `feat: add vendor-form.js dialog manager for vendor creation`
2. `refactor: add vendor dialog to dashboard, remove inline form templates`
3. `refactor: delete /vendors/new-form route (replaced by dialog)`
4. `refactor: /vendors/create returns JSON instead of HTML+script`
5. `refactor: /vendors/lookup-address returns JSON instead of HTML`
6. `docs: vendor form dialog refactor design spec`

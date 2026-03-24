# Vendor Discovery and Creation UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the broken new-vendor flow: clicking "+ Add as new vendor…" must load the creation form, auto-fire an address search, allow refinement by city/ZIP, and require explicit candidate selection before creating.

**Architecture:** HTMX-native — replace a synchronous `onclick` race with `hx-on::after-request`, add `hx-trigger="load"` to auto-fire address search on form render, add debounced refinement triggers on city/ZIP inputs, update the `/vendors/lookup-address` route to accept and combine those extra fields into the search query.

**Tech Stack:** FastAPI, HTMX, Jinja2, `bill_processor.address_lookup` (Google Places / OSM fallback), pytest

---

## File Structure

| File | What changes |
|---|---|
| `web/app.py` | `lookup_address` route: add `addr_city`, `addr_zip` Form params; build combined search query |
| `web/templates/partials/vendor_dropdown.html` | "+ Add" item: replace `onclick` with `hx-on::after-request` |
| `web/templates/partials/new_vendor_form.html` | Add auto-fire load trigger (moves `#address-candidates` to just after Display Name input); add city/ZIP refinement triggers; remove "Look Up Address" button; update Cancel onclick |
| `web/templates/partials/address_candidates.html` | Scrollable container height: `10rem` → `9rem` |
| `tests/test_web_app.py` | New tests for all of the above |

No new files. No new routes.

---

### Task 1: Update lookup_address route to accept refinement fields

**Background:** `GET /vendors/search` → `vendor_dropdown.html` shows fuzzy vendor matches. `GET /vendors/new-form` → `new_vendor_form.html` shows the creation form. `POST /vendors/lookup-address` → `address_candidates.html` runs the address search. Currently `lookup_address` only reads `vendor_name` and `display_name`; it must also read `addr_city` and `addr_zip` and combine them into the search query.

The route lives at `web/app.py:348`. The address lookup module is `import bill_processor.address_lookup as addr_lookup` (line 24 of app.py). In tests, mock it via `monkeypatch.setattr(web_app.addr_lookup, "lookup_google_places", ...)`.

**Files:**
- Modify: `web/app.py:348-367`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_app.py` (after the existing `test_address_lookup_returns_form` test):

```python
def test_lookup_address_combines_city_and_zip(client, monkeypatch):
    """Route builds combined query from display_name + addr_city + addr_zip."""
    import bill_processor.web.app as web_app
    captured = []
    monkeypatch.setattr(web_app.addr_lookup, "lookup_google_places",
                        lambda q, **kw: captured.append(q) or [])
    monkeypatch.setattr(web_app.addr_lookup, "lookup_openstreetmap",
                        lambda q, **kw: [])
    response = client.post("/vendors/lookup-address", data={
        "display_name": "Kroger",
        "addr_city": "Cincinnati",
        "addr_zip": "45202",
    })
    assert response.status_code == 200
    assert captured == ["Kroger Cincinnati 45202"]


def test_lookup_address_skips_empty_refinement_fields(client, monkeypatch):
    """Blank city/zip fields are omitted from the combined query."""
    import bill_processor.web.app as web_app
    captured = []
    monkeypatch.setattr(web_app.addr_lookup, "lookup_google_places",
                        lambda q, **kw: captured.append(q) or [])
    monkeypatch.setattr(web_app.addr_lookup, "lookup_openstreetmap",
                        lambda q, **kw: [])
    response = client.post("/vendors/lookup-address", data={
        "display_name": "Kroger",
        "addr_city": "",
        "addr_zip": "45202",
    })
    assert response.status_code == 200
    assert captured == ["Kroger 45202"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_web_app.py::test_lookup_address_combines_city_and_zip tests/test_web_app.py::test_lookup_address_skips_empty_refinement_fields -v
```

Expected: FAIL — route ignores `addr_city`/`addr_zip` so `captured[0]` will be `"Kroger"` not `"Kroger Cincinnati 45202"`.

- [ ] **Step 3: Update the lookup_address route in web/app.py**

Replace the existing `lookup_address` function (lines 348-367):

```python
@app.post("/vendors/lookup-address", response_class=HTMLResponse)
def lookup_address(
    request: Request,
    vendor_name: str = Form(""),
    display_name: str = Form(""),
    addr_city: str = Form(""),
    addr_zip: str = Form(""),
):
    """Look up address candidates and return a picker fragment."""
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

    return templates.TemplateResponse(request, "partials/address_candidates.html", {
        "candidates": candidates,
        "message": message,
    })
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_web_app.py::test_lookup_address_combines_city_and_zip tests/test_web_app.py::test_lookup_address_skips_empty_refinement_fields -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regressions**

```bash
uv run pytest tests/test_web_app.py -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add web/app.py tests/test_web_app.py
git commit -m "feat: lookup-address accepts addr_city and addr_zip for combined query"
```

---

### Task 2: Fix vendor dropdown race condition

**Background:** `vendor_dropdown.html` renders for every keystroke in the vendor input. It shows fuzzy matches plus a "+ Add as new vendor…" item at the bottom. The "+ Add" item currently has `onclick="document.getElementById('vendor-dropdown').innerHTML=''"` which removes the element from the DOM synchronously — before HTMX can fire its `hx-get` request. The fix: remove `onclick`, replace with `hx-on::after-request` which runs *after* the HTMX response has been swapped in.

The existing regular vendor items (lines 3-11) have their own `onclick` that clears both `#vendor-dropdown` and `#new-vendor-section` — those are correct and must not be changed.

**Files:**
- Modify: `web/templates/partials/vendor_dropdown.html`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_web_app.py`:

```python
def test_vendor_dropdown_add_item_uses_after_request_not_onclick(client):
    """The '+ Add' item clears the dropdown via hx-on::after-request, not onclick."""
    response = client.get("/vendors/search", params={"vendor_name": "TestQuery"})
    assert response.status_code == 200
    html = response.text
    # New attribute must be present
    assert "hx-on::after-request" in html
    # The old synchronous onclick that cleared the dropdown must be gone from the add item.
    # The add item's onclick previously was exactly this string:
    assert "onclick=\"document.getElementById('vendor-dropdown').innerHTML=''\"" not in html
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_web_app.py::test_vendor_dropdown_add_item_uses_after_request_not_onclick -v
```

Expected: FAIL — template still has the old `onclick`.

- [ ] **Step 3: Update vendor_dropdown.html**

Replace the entire file `web/templates/partials/vendor_dropdown.html`:

```html
<div class="dropdown-list">
  {% for vendor in results %}
  <div class="dropdown-item"
       onclick='
         document.getElementById("vendor-input").value = {{ vendor.display_name | tojson }};
         document.getElementById("vendor-dropdown").innerHTML = "";
         document.getElementById("new-vendor-section").innerHTML = "";
       '>
    {{ vendor.display_name }}
  </div>
  {% endfor %}
  <div class="dropdown-item" style="color:#888; font-style:italic"
       hx-on::after-request="document.getElementById('vendor-dropdown').innerHTML=''"
       hx-get="/vendors/new-form?name={{ query | urlencode }}"
       hx-target="#new-vendor-section"
       hx-swap="innerHTML">
    + Add &ldquo;{{ query | e }}&rdquo; as new vendor&hellip;
  </div>
</div>
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_web_app.py::test_vendor_dropdown_add_item_uses_after_request_not_onclick -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/test_web_app.py -v
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add web/templates/partials/vendor_dropdown.html tests/test_web_app.py
git commit -m "fix: clear vendor dropdown after-request so HTMX can fire new-form request"
```

---

### Task 3: Update new vendor form

**Background:** `new_vendor_form.html` is rendered by `GET /vendors/new-form?name=...` and injected into `#new-vendor-section`. The form context from the route provides: `vendor_name`, `display_name`, `addr_line1`, `addr_line2`, `addr_city`, `addr_state`, `addr_zip`, `addr_phone`, `message`.

Four changes in this task:
1. `#address-candidates` div gets auto-fire load trigger (`hx-trigger="load"`) with `hx-vals` carrying the display name rendered at template time.
2. Remove the "Look Up Address" button entirely.
3. `addr_city` and `addr_zip` inputs get debounced refinement triggers (`hx-trigger="keyup changed delay:500ms"`) with `hx-include="closest form"`.
4. Cancel button onclick extended to also clear `#vendor-dropdown` and blank `#vendor-input`.

**Files:**
- Modify: `web/templates/partials/new_vendor_form.html`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_web_app.py`:

```python
def test_new_vendor_form_auto_fires_address_search_on_load(client):
    """#address-candidates has hx-trigger=load to auto-fire address search."""
    response = client.get("/vendors/new-form", params={"name": "Kroger"})
    assert response.status_code == 200
    html = response.text
    assert 'hx-trigger="load"' in html
    assert 'hx-post="/vendors/lookup-address"' in html


def test_new_vendor_form_hx_vals_contains_display_name(client):
    """hx-vals on #address-candidates includes the rendered vendor display name as JSON."""
    response = client.get("/vendors/new-form", params={"name": "Kroger"})
    assert response.status_code == 200
    # The hx-vals attribute must contain the JSON key "display_name" (with quotes)
    # and the rendered vendor name. Neither of these patterns exist in the current
    # template, so this assertion will correctly FAIL before the implementation.
    assert '"display_name": "Kroger"' in response.text


def test_new_vendor_form_city_zip_have_refinement_triggers(client):
    """City and ZIP inputs carry HTMX refinement triggers."""
    response = client.get("/vendors/new-form", params={"name": "Kroger"})
    assert response.status_code == 200
    html = response.text
    assert 'hx-trigger="keyup changed delay:500ms"' in html
    assert 'hx-include="closest form"' in html


def test_new_vendor_form_no_lookup_button(client):
    """The manual 'Look Up Address' button has been removed."""
    response = client.get("/vendors/new-form", params={"name": "Kroger"})
    assert response.status_code == 200
    assert b"Look Up Address" not in response.content


def test_new_vendor_form_cancel_clears_vendor_input(client):
    """Cancel button onclick clears #new-vendor-section, #vendor-dropdown, and #vendor-input."""
    response = client.get("/vendors/new-form", params={"name": "Kroger"})
    assert response.status_code == 200
    html = response.text
    assert "vendor-dropdown" in html
    assert "vendor-input" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_web_app.py::test_new_vendor_form_auto_fires_address_search_on_load tests/test_web_app.py::test_new_vendor_form_hx_vals_contains_display_name tests/test_web_app.py::test_new_vendor_form_city_zip_have_refinement_triggers tests/test_web_app.py::test_new_vendor_form_no_lookup_button tests/test_web_app.py::test_new_vendor_form_cancel_clears_vendor_input -v
```

Expected: all FAIL.

- [ ] **Step 3: Rewrite new_vendor_form.html**

Replace the entire file `web/templates/partials/new_vendor_form.html`:

```html
<div id="new-vendor-form">
  <strong>New Vendor: {{ vendor_name | e }}</strong>
  {% if message %}<p class="error-msg" style="margin-top:0.3rem">{{ message | e }}</p>{% endif %}

  <form hx-post="/vendors/create" hx-target="#new-vendor-section" hx-swap="innerHTML">
    <input type="hidden" name="vendor_name" value="{{ vendor_name | e }}">

    <label for="new-vendor-display-name">Display Name</label>
    <input type="text" name="display_name" id="new-vendor-display-name"
           value="{{ display_name | e }}" required>

    <div id="address-candidates"
         hx-post="/vendors/lookup-address"
         hx-trigger="load"
         hx-swap="innerHTML"
         hx-vals='{"display_name": "{{ display_name | e }}"}'>
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
           hx-include="closest form">

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
               hx-include="closest form">
      </div>
    </div>

    <label for="new-vendor-phone">Phone</label>
    <input type="text" name="addr_phone" id="new-vendor-phone" value="{{ addr_phone | e }}">

    <div style="margin-top:0.75rem; display:flex; gap:0.5rem">
      <button type="submit" class="btn-primary">Create Vendor</button>
      <button type="button"
        onclick="document.getElementById('new-vendor-section').innerHTML='';document.getElementById('vendor-dropdown').innerHTML='';document.getElementById('vendor-input').value='';">Cancel</button>
    </div>
  </form>
</div>
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_web_app.py::test_new_vendor_form_auto_fires_address_search_on_load tests/test_web_app.py::test_new_vendor_form_hx_vals_contains_display_name tests/test_web_app.py::test_new_vendor_form_city_zip_have_refinement_triggers tests/test_web_app.py::test_new_vendor_form_no_lookup_button tests/test_web_app.py::test_new_vendor_form_cancel_clears_vendor_input -v
```

Expected: all PASS.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/test_web_app.py -v
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add web/templates/partials/new_vendor_form.html tests/test_web_app.py
git commit -m "feat: auto-fire address search on new vendor form load; add city/zip refinement triggers; update cancel button"
```

---

### Task 4: Update address candidate list height

**Background:** `address_candidates.html` renders the scrollable candidate list only when `candidates` is non-empty (the `{% if candidates %}` block). The scrollable container is currently `max-height:10rem; overflow-y:auto`. Change to `max-height:9rem` to show approximately 3 candidates at a time.

**Files:**
- Modify: `web/templates/partials/address_candidates.html`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_web_app.py`:

```python
def test_address_candidates_height_shows_three(client, monkeypatch):
    """Candidate list scrollable container uses max-height:9rem."""
    import bill_processor.web.app as web_app
    fake_candidates = [
        {"name": "Kroger #1", "formatted_address": "100 Main St, Cincinnati, OH 45202",
         "addr_line1": "100 Main St", "addr_line2": "Cincinnati, OH 45202",
         "phone": "513-555-0001", "distance": 1.2},
    ]
    monkeypatch.setattr(web_app.addr_lookup, "lookup_google_places",
                        lambda q, **kw: fake_candidates)
    response = client.post("/vendors/lookup-address", data={"display_name": "Kroger"})
    assert response.status_code == 200
    assert b"max-height:9rem" in response.content
    assert b"max-height:10rem" not in response.content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_web_app.py::test_address_candidates_height_shows_three -v
```

Expected: FAIL — template still has `max-height:10rem`.

- [ ] **Step 3: Update address_candidates.html**

In `web/templates/partials/address_candidates.html`, change line 6 from:
```html
  <div style="max-height:10rem; overflow-y:auto">
```
to:
```html
  <div style="max-height:9rem; overflow-y:auto">
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_web_app.py::test_address_candidates_height_shows_three -v
```

Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/test_web_app.py -v
```

Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add web/templates/partials/address_candidates.html tests/test_web_app.py
git commit -m "fix: address candidate list height 9rem (~3 visible at a time)"
```

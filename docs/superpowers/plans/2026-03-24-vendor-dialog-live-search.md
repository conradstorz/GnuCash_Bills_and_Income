# Vendor Dialog Live Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the vendor dialog's address candidates panel always-visible with live search feedback driven by display name, city, and zip inputs.

**Architecture:** Four targeted changes to `vendor-form.js` (add display name listener, show loading state, update empty state text, keep panel on selection) plus one CSS class for status text styling. No backend changes.

**Tech Stack:** Vanilla JavaScript, CSS

**Spec:** `docs/superpowers/specs/2026-03-24-vendor-dialog-live-search-design.md`

---

### Task 1: Add CSS class for candidates panel status text

**Files:**
- Modify: `web/static/style.css:95-102` (after existing `#vf-candidates` rules)

- [ ] **Step 1: Add the `.vf-status` CSS class**

Append after line 102 in `style.css`:

```css
#vf-candidates .vf-status {
  padding: 0.4rem 0.6rem;
  color: #888;
  font-style: italic;
  font-size: 0.9rem;
}
```

- [ ] **Step 2: Verify visually**

Start the dev server (`uv run uvicorn bill_processor.web.app:app --reload --port 7432`) and confirm the dialog still renders correctly at `http://localhost:7432`. No functional change yet — this is just a CSS addition.

- [ ] **Step 3: Commit**

```bash
git add web/static/style.css
git commit -m "style: add .vf-status class for candidates panel status text"
```

---

### Task 2: Show "Searching..." loading state in lookupAddress()

**Files:**
- Modify: `web/static/vendor-form.js:73-92` (`lookupAddress` function)

- [ ] **Step 1: Add loading indicator before fetch**

In `lookupAddress()`, immediately after `const gen = ++requestGen;` (line 74), add:

```javascript
    candidates.innerHTML = '<p class="vf-status">Searching\u2026</p>';
```

This goes before the `FormData` construction (line 75). The full function opening becomes:

```javascript
  async function lookupAddress() {
    const gen = ++requestGen;
    candidates.innerHTML = '<p class="vf-status">Searching\u2026</p>';
    const formData = new FormData();
```

- [ ] **Step 2: Test manually**

Open the dialog by searching for a vendor name that doesn't exist and clicking "+ Add." Confirm "Searching..." appears immediately in the candidates panel before results load.

- [ ] **Step 3: Commit**

```bash
git add web/static/vendor-form.js
git commit -m "feat: show Searching... loading state in vendor dialog"
```

---

### Task 3: Update empty-results state to "No exact matches found"

**Files:**
- Modify: `web/static/vendor-form.js:94-100` (`renderCandidates` empty branch)

- [ ] **Step 1: Change the empty/no-message branch**

In `renderCandidates()`, replace lines 95-99:

```javascript
    if (!items || items.length === 0) {
      candidates.innerHTML = message
        ? `<p class="error-msg" style="margin-top:0.25rem">${escapeHtml(message)}</p>`
        : "";
      return;
    }
```

With:

```javascript
    if (!items || items.length === 0) {
      candidates.innerHTML = message
        ? `<p class="error-msg" style="margin-top:0.25rem">${escapeHtml(message)}</p>`
        : '<p class="vf-status">No exact matches found</p>';
      return;
    }
```

The only change is replacing the empty string `""` with the "No exact matches found" status paragraph.

- [ ] **Step 2: Test manually**

Open the dialog with a nonsense name (e.g., "xyzzy123"). After "Searching..." resolves, confirm the panel shows "No exact matches found" in muted italic text instead of going blank.

- [ ] **Step 3: Commit**

```bash
git add web/static/vendor-form.js
git commit -m "feat: show 'No exact matches found' instead of blank panel"
```

---

### Task 4: Add display name field as search trigger

**Files:**
- Modify: `web/static/vendor-form.js:34-36` (`init` function, event listeners section)

- [ ] **Step 1: Add input listener on display name**

In `init()`, after line 36 (`zip.addEventListener("input", () => debouncedLookup());`), add:

```javascript
    displayName.addEventListener("input", () => debouncedLookup());
```

The event listener block becomes:

```javascript
    // Debounced address re-lookup on display name/city/zip change
    displayName.addEventListener("input", () => debouncedLookup());
    city.addEventListener("input", () => debouncedLookup());
    zip.addEventListener("input", () => debouncedLookup());
```

Also update the comment on line 34 from `// Debounced address re-lookup on city/zip change` to `// Debounced address re-lookup on display name/city/zip change`.

- [ ] **Step 2: Test manually**

Open the dialog, then edit the display name field. Confirm "Searching..." appears and results update based on the new name.

- [ ] **Step 3: Commit**

```bash
git add web/static/vendor-form.js
git commit -m "feat: display name edits trigger address re-search"
```

---

### Task 5: Keep candidates panel open after selection

**Files:**
- Modify: `web/static/vendor-form.js:122-136` (`selectCandidate` function)

- [ ] **Step 1: Remove candidates clearing and add explicit re-search**

In `selectCandidate()`, delete line 135 (`candidates.innerHTML = "";`) and replace it with `debouncedLookup();`. Note: setting `.value` programmatically does NOT fire `input` events, so we must explicitly trigger the re-search after populating fields.

```javascript
    debouncedLookup();
```

The full `selectCandidate` function becomes:

```javascript
  function selectCandidate(el, index) {
    const c = candidates._data[index];
    if (!c) return;

    addr1.value = c.addr_line1 || "";
    const a2 = c.addr_line2 || "";
    const m = a2.match(/^(.*),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$/);
    addr2.value = "";
    city.value = m ? m[1] : "";
    state.value = m ? m[2] : "";
    zip.value = m ? m[3] : "";
    phone.value = c.phone || "";
    debouncedLookup();
  }
```

- [ ] **Step 3: Test manually**

Open the dialog, wait for results, click a candidate. Confirm:
- Form fields populate correctly
- Panel shows "Searching..." briefly
- New results appear reflecting the selected location
- Panel never disappears

- [ ] **Step 4: Commit**

```bash
git add web/static/vendor-form.js
git commit -m "feat: keep candidates panel open after selection, trigger re-search"
```

---

### Task 6: Update open() to show loading state instead of blank panel

**Files:**
- Modify: `web/static/vendor-form.js:39-59` (`open` function)

- [ ] **Step 1: Replace blank candidates clear with loading message**

In `open()`, change line 52:

```javascript
    candidates.innerHTML = "";
```

To:

```javascript
    candidates.innerHTML = '<p class="vf-status">Searching\u2026</p>';
```

This ensures the panel shows "Searching..." immediately when the dialog opens, before `lookupAddress()` even fires. The subsequent `lookupAddress()` call on line 58 will also set "Searching..." (from Task 2), which is harmless — it's the same content.

- [ ] **Step 2: Test manually**

Open the dialog. Confirm "Searching..." appears instantly in the candidates panel (no blank flash).

- [ ] **Step 3: Commit**

```bash
git add web/static/vendor-form.js
git commit -m "feat: show Searching... immediately when dialog opens"
```

---

### Task 7: Run full test suite and verify

**Files:**
- Read: `tests/test_web_app.py` (existing tests should still pass)

- [ ] **Step 1: Run all tests**

```bash
uv run python tests/run_tests.py
```

Expected: All tests pass. No backend or template changes were made, so existing tests (including `test_dashboard_includes_vendor_dialog`, `test_vendor_dropdown_add_item_uses_vendor_form_open`, `test_address_lookup_returns_json`) should be unaffected.

- [ ] **Step 2: Manual end-to-end test**

Start the dev server and test the complete flow:
1. Type a vendor name in the bill entry form
2. Click "+ Add" in the dropdown
3. Dialog opens → "Searching..." appears immediately
4. Results load (or "No exact matches found")
5. Edit display name → results refresh
6. Edit city or zip → results refresh
7. Click a candidate → fields populate, panel stays open, re-search fires
8. Click "Create Vendor" → vendor created, dialog closes
9. Vendor name populates the bill entry input

- [ ] **Step 3: Final commit if any adjustments were needed**

If any tweaks were required during testing, commit them now.

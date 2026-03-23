# Processing Accounts Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated settings page where the user selects an A/P account and a checking account; block bill processing until both are configured; log both at INFO level during processing.

**Architecture:** Settings are persisted in `data/user_settings.json` via `SettingsManager`. `_process_one_bill()` reads the two GUIDs from settings and passes them explicitly to `post_bill()` and `pay_bill()`. The dashboard buttons are conditionally disabled when either GUID is absent. A new `/settings/processing-accounts` page with two independent HTMX sections (radio lists, save-on-click) manages the selections.

**Tech Stack:** Python/FastAPI, HTMX, Jinja2, SQLite (GnuCash), pytest/monkeypatch

**Spec:** `docs/superpowers/specs/2026-03-23-processing-accounts-settings-design.md`

---

## File Map

| Action | File | What changes |
|--------|------|-------------|
| Modify | `gnucash_db.py` | Add `get_payable_accounts()` after line 1654 |
| Modify | `settings_manager.py` | Add `ap_account_guid`, `checking_account_guid`, `processing_accounts_configured` |
| Modify | `web/app.py` | 3 new routes; rewrite `_process_one_bill` guard; add `processing_accounts_configured` to GET / and GET /partials/queued-bills |
| Create | `web/templates/settings_processing_accounts.html` | New settings page |
| Create | `web/templates/partials/processing_ap_section.html` | HTMX A/P section partial |
| Create | `web/templates/partials/processing_checking_section.html` | HTMX checking section partial |
| Modify | `web/templates/settings.html` | Add "Processing Accounts →" nav link at top |
| Modify | `web/templates/partials/queued_bills.html` | Conditionally disable process buttons; add configure link |
| Modify | `tests/test_get_cash_accounts.py` | Add `TestGetPayableAccounts` class |
| Modify | `tests/test_settings_manager.py` | Add processing account field tests |
| Modify | `tests/test_web_app.py` | Add new tests; update `TestProcessOneBill._patch_gnucash` |

---

## Task 1: Add `get_payable_accounts()` to gnucash_db.py

**Files:**
- Modify: `gnucash_db.py` (after line 1654, after `get_checking_accounts()`)
- Test: `tests/test_get_cash_accounts.py`

- [ ] **Step 1: Write the failing tests**

Add this class to the bottom of `tests/test_get_cash_accounts.py`:

```python
class TestGetPayableAccounts:
    def test_returns_payable_accounts(self):
        rows = [{"guid": "a" * 32, "name": "Accounts Payable", "description": ""}]
        conn = _make_fake_conn(rows)
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            result = gnucash_db.get_payable_accounts()
        assert len(result) == 1
        assert result[0]["name"] == "Accounts Payable"
        assert result[0]["guid"] == "a" * 32

    def test_returns_empty_list_when_no_payable_accounts(self):
        conn = _make_fake_conn([])
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            result = gnucash_db.get_payable_accounts()
        assert result == []

    def test_queries_payable_account_type(self):
        conn = _make_fake_conn([])
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            gnucash_db.get_payable_accounts()
        params = conn.execute.call_args[0][1]
        assert config.ACCOUNT_TYPE_PAYABLE in params

    def test_excludes_placeholder_accounts(self):
        conn = _make_fake_conn([])
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            gnucash_db.get_payable_accounts()
        params = conn.execute.call_args[0][1]
        assert config.PLACEHOLDER_FALSE in params

    def test_result_dicts_have_name_and_guid(self):
        rows = [{"guid": "b" * 32, "name": "AP Trade", "description": ""}]
        conn = _make_fake_conn(rows)
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            result = gnucash_db.get_payable_accounts()
        assert "name" in result[0]
        assert "guid" in result[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/test_get_cash_accounts.py::TestGetPayableAccounts -v
```

Expected: `AttributeError: module 'bill_processor.gnucash_db' has no attribute 'get_payable_accounts'`

- [ ] **Step 3: Implement `get_payable_accounts()`**

In `gnucash_db.py`, immediately after the closing `return` of `get_checking_accounts()` (after line 1654), add:

```python
def get_payable_accounts() -> List[Dict]:
    """Get all non-placeholder Accounts Payable (PAYABLE-type) accounts."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT guid, name, description FROM accounts
            WHERE account_type = ? AND placeholder = ?
            ORDER BY name
        """, (config.ACCOUNT_TYPE_PAYABLE, config.PLACEHOLDER_FALSE))
        return [dict(row) for row in cursor]
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/test_get_cash_accounts.py::TestGetPayableAccounts -v
```

Expected: 5 passed

- [ ] **Step 5: Run full suite to check no regressions**

```
uv run pytest tests/ -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```
git add gnucash_db.py tests/test_get_cash_accounts.py
git commit -m "feat: add get_payable_accounts() to gnucash_db"
```

---

## Task 2: Add processing account fields to SettingsManager

**Files:**
- Modify: `settings_manager.py`
- Test: `tests/test_settings_manager.py`

- [ ] **Step 1: Write the failing tests**

Add this class to the bottom of `tests/test_settings_manager.py`:

```python
class TestProcessingAccountSettings:
    """Tests for ap_account_guid, checking_account_guid, processing_accounts_configured."""

    def test_ap_account_guid_defaults_to_none(self, settings_manager):
        assert settings_manager.ap_account_guid is None

    def test_checking_account_guid_defaults_to_none(self, settings_manager):
        assert settings_manager.checking_account_guid is None

    def test_processing_accounts_configured_false_when_both_none(self, settings_manager):
        assert settings_manager.processing_accounts_configured is False

    def test_processing_accounts_configured_false_when_only_ap_set(self, settings_manager):
        settings_manager.ap_account_guid = "a" * 32
        assert settings_manager.processing_accounts_configured is False

    def test_processing_accounts_configured_false_when_only_checking_set(self, settings_manager):
        settings_manager.checking_account_guid = "c" * 32
        assert settings_manager.processing_accounts_configured is False

    def test_processing_accounts_configured_true_when_both_set(self, settings_manager):
        settings_manager.ap_account_guid = "a" * 32
        settings_manager.checking_account_guid = "c" * 32
        assert settings_manager.processing_accounts_configured is True

    def test_ap_account_guid_persists_to_file(self, settings_manager, temp_settings_file):
        settings_manager.ap_account_guid = "a" * 32
        import json
        with open(temp_settings_file) as f:
            data = json.load(f)
        assert data["ap_account_guid"] == "a" * 32

    def test_checking_account_guid_persists_to_file(self, settings_manager, temp_settings_file):
        settings_manager.checking_account_guid = "c" * 32
        import json
        with open(temp_settings_file) as f:
            data = json.load(f)
        assert data["checking_account_guid"] == "c" * 32

    def test_reset_clears_processing_account_guids(self, settings_manager):
        settings_manager.ap_account_guid = "a" * 32
        settings_manager.checking_account_guid = "c" * 32
        settings_manager.reset_to_defaults()
        assert settings_manager.ap_account_guid is None
        assert settings_manager.checking_account_guid is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/test_settings_manager.py::TestProcessingAccountSettings -v
```

Expected: `AttributeError: 'SettingsManager' object has no attribute 'ap_account_guid'`

- [ ] **Step 3: Implement the settings fields**

In `settings_manager.py`:

**a)** In `_load_defaults()`, add two entries after the `"log_level"` line (around line 120):

```python
            # Processing Accounts (bill posting/payment)
            "ap_account_guid": None,
            "checking_account_guid": None,
```

**b)** After the `log_level` setter (around line 207), add:

```python
    @property
    def ap_account_guid(self) -> Optional[str]:
        """GUID of the selected A/P account for bill posting."""
        return self._settings.get("ap_account_guid")

    @ap_account_guid.setter
    def ap_account_guid(self, value: Optional[str]):
        self.set("ap_account_guid", value)

    @property
    def checking_account_guid(self) -> Optional[str]:
        """GUID of the selected checking account for bill payment."""
        return self._settings.get("checking_account_guid")

    @checking_account_guid.setter
    def checking_account_guid(self, value: Optional[str]):
        self.set("checking_account_guid", value)

    @property
    def processing_accounts_configured(self) -> bool:
        """True only when both A/P and checking accounts have been selected."""
        return bool(self.ap_account_guid and self.checking_account_guid)
```

- [ ] **Step 4: Run tests to verify they pass**

```
uv run pytest tests/test_settings_manager.py::TestProcessingAccountSettings -v
```

Expected: 9 passed

- [ ] **Step 5: Run full suite to check no regressions**

```
uv run pytest tests/ -q
```

Expected: all pass

- [ ] **Step 6: Commit**

```
git add settings_manager.py tests/test_settings_manager.py
git commit -m "feat: add ap_account_guid and checking_account_guid to SettingsManager"
```

---

## Task 3: Update `_process_one_bill` — guard + explicit account passing

**Files:**
- Modify: `web/app.py` (lines 163–221)
- Test: `tests/test_web_app.py`

This task has three phases: write new tests (they fail), implement changes (new tests pass but old tests break), fix old tests.

### Phase A: Write new failing tests

- [ ] **Step 1: Write new tests in `TestProcessOneBill`**

Add `AP_GUID = "e" * 32` to the class constants (alongside the existing `VENDOR_GUID`, etc.).

Add these four test methods to `TestProcessOneBill`:

```python
    AP_GUID = "e" * 32  # add to class body alongside existing GUIDs

    def test_blocks_when_ap_account_not_configured(self, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", None)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)

        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "not configured" in result["error"].lower()

    def test_blocks_when_checking_account_not_configured(self, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", self.AP_GUID)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", None)

        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "not configured" in result["error"].lower()

    def test_uses_configured_ap_account_guid(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", self.AP_GUID)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test", "guid": guid})
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", lambda **kw: "pay_guid")
        captured = {}
        monkeypatch.setattr(web_app.gnucash_db, "post_bill",
                            lambda **kw: captured.update(kw))

        web_app._process_one_bill(self._bill())
        assert captured.get("ap_account_guid") == self.AP_GUID

    def test_uses_configured_checking_account_guid(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", self.AP_GUID)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test", "guid": guid})
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "post_bill", lambda **kw: None)
        captured = {}
        def capture_pay(**kw):
            captured.update(kw)
            return "pay_guid"
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", capture_pay)

        web_app._process_one_bill(self._bill())
        assert captured.get("checking_account_guid") == self.CHECKING_GUID
```

- [ ] **Step 2: Run new tests to verify they fail**

```
uv run pytest tests/test_web_app.py::TestProcessOneBill::test_blocks_when_ap_account_not_configured tests/test_web_app.py::TestProcessOneBill::test_blocks_when_checking_account_not_configured tests/test_web_app.py::TestProcessOneBill::test_uses_configured_ap_account_guid tests/test_web_app.py::TestProcessOneBill::test_uses_configured_checking_account_guid -v
```

Expected: the guard tests fail (no guard exists yet); the forwarding tests fail (wrong kwargs).

### Phase B: Implement the changes

- [ ] **Step 3: Rewrite `_process_one_bill` in `web/app.py`**

Replace the entire `_process_one_bill` function (lines 163–221) with:

```python
def _process_one_bill(bill: dict) -> dict:
    """
    Run create/post/pay for a single queued bill dict.
    Returns {"ok": True} or {"ok": False, "error": str}.
    """
    # Guard: both processing accounts must be configured before any GnuCash call
    ap_guid = settings.ap_account_guid
    checking_guid = settings.checking_account_guid
    if not ap_guid or not checking_guid:
        return {"ok": False, "error": "Processing accounts not configured — visit Settings > Processing Accounts"}

    # Resolve account names for logging only
    ap_account = gnucash_db.get_account_by_guid(ap_guid)
    checking_account = gnucash_db.get_account_by_guid(checking_guid)
    ap_name = ap_account["name"] if ap_account else ap_guid
    checking_name = checking_account["name"] if checking_account else checking_guid

    vm = VendorManager()
    vendor_data, match_type = vm.find_vendor(bill["vendor_name"])
    if not vendor_data:
        return {"ok": False, "error": f"Vendor not found: {bill['vendor_name']}"}

    vendor_guid = vendor_data.get("gnucash_guid")
    if not vendor_guid:
        gc_vendor = gnucash_db.find_vendor_by_name(vendor_data.get("display_name", ""))
        if not gc_vendor:
            return {"ok": False, "error": f"No GnuCash record for vendor: {vendor_data.get('display_name')}"}
        vendor_guid = gc_vendor["guid"]

    expense_guid = vendor_data.get("expense_account_guid") or vendor_data.get("expense_account")
    if expense_guid and len(str(expense_guid)) != 32:
        expense_guid = None
    if not expense_guid:
        return {"ok": False, "error": f"No expense account GUID for vendor: {vendor_data.get('display_name')}"}

    bill_date = bill["date"]
    logger.info(f"Using A/P account: {ap_name} ({ap_guid})")
    logger.info(f"Using checking account: {checking_name} ({checking_guid})")
    try:
        bill_guid = gnucash_db.create_bill(
            vendor_guid=vendor_guid,
            expense_account_guid=expense_guid,
            amount=bill["amount"],
            memo=bill.get("memo", ""),
            bill_date=bill_date,
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_date,
            due_date=bill_date,
            ap_account_guid=ap_guid,
        )
        gnucash_db.pay_bill(
            bill_guid=bill_guid,
            checking_account_guid=checking_guid,
            payment_date=bill_date,
            memo=bill.get("memo", ""),
            check_number=bill.get("check_number", ""),
        )
        logger.info(f"Processed bill: {bill['vendor_name']} ${bill['amount']:.2f}")
        return {"ok": True}
    except Exception as e:
        logger.error(
            f"Failed to process bill {bill['vendor_name']}: {e}. "
            f"Bill may have been partially created in GnuCash — check for duplicates before retrying."
        )
        return {"ok": False, "error": f"{e} (bill may be partially created in GnuCash — check before retrying)"}
```

- [ ] **Step 4: Run the four new tests — expect them to pass now**

```
uv run pytest tests/test_web_app.py::TestProcessOneBill::test_blocks_when_ap_account_not_configured tests/test_web_app.py::TestProcessOneBill::test_blocks_when_checking_account_not_configured tests/test_web_app.py::TestProcessOneBill::test_uses_configured_ap_account_guid tests/test_web_app.py::TestProcessOneBill::test_uses_configured_checking_account_guid -v
```

Expected: 4 passed

- [ ] **Step 5: Run the full `TestProcessOneBill` class — expect old tests to fail**

```
uv run pytest tests/test_web_app.py::TestProcessOneBill -v
```

Expected: the four new tests pass; the five original tests (`test_success_returns_ok`, `test_vendor_not_found_returns_error`, `test_no_expense_account_returns_error`, `test_gnucash_exception_returns_error`, `test_check_number_forwarded_to_pay_bill`) fail because `settings.ap_account_guid` and `settings.checking_account_guid` are `None` (guard fires before any vendor lookup).

### Phase C: Fix the existing tests

- [ ] **Step 6: Update `TestProcessOneBill` to fix the old tests**

Make these changes to the `TestProcessOneBill` class:

**a)** Add `AP_GUID = "e" * 32` to the class constants if not already present.

**b)** Replace `_patch_gnucash` with this updated version (removes `get_checking_accounts`, adds settings + `get_account_by_guid`):

```python
    def _patch_gnucash(self, monkeypatch, web_app):
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", self.AP_GUID)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        monkeypatch.setattr(web_app.gnucash_db, "create_bill",
                            lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "post_bill", lambda **kw: None)
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", lambda **kw: "pay_guid")
```

**c)** `test_gnucash_exception_returns_error` currently patches `get_checking_accounts` (lines 294–295) but doesn't set settings GUIDs — after the rewrite the guard fires first and the `"DB locked"` assertion fails. Replace that test with:

```python
    def test_gnucash_exception_returns_error(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", self.AP_GUID)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test", "guid": guid})

        def fail(**kw):
            raise ValueError("DB locked")

        monkeypatch.setattr(web_app.gnucash_db, "create_bill", fail)

        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "DB locked" in result["error"]
```

**d)** `test_vendor_not_found_returns_error` (line 268) sets no settings GUIDs — the guard fires before the vendor lookup. Replace it with:

```python
    def test_vendor_not_found_returns_error(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (None, "not_found")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", self.AP_GUID)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test", "guid": guid})

        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "Acme Electric" in result["error"]
```

**e)** `test_no_expense_account_returns_error` (line 278) has the same problem. Replace it with:

```python
    def test_no_expense_account_returns_error(self, monkeypatch):
        from bill_processor.web import app as web_app
        vendor_no_expense = {"gnucash_guid": self.VENDOR_GUID, "display_name": "Acme Electric"}
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (vendor_no_expense, "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", self.AP_GUID)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test", "guid": guid})

        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "expense account" in result["error"].lower()
```

**f)** The `test_check_number_forwarded_to_pay_bill` test also calls `_patch_gnucash` for some mocks but adds its own `pay_bill` capture. Update it to also set up settings and `get_account_by_guid` (since it no longer uses `_patch_gnucash` for those). Replace `test_check_number_forwarded_to_pay_bill` with:

```python
    def test_check_number_forwarded_to_pay_bill(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", self.AP_GUID)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test", "guid": guid})
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "post_bill", lambda **kw: None)

        captured = {}
        def capture_pay(**kw):
            captured.update(kw)
            return "pay_guid"
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", capture_pay)

        web_app._process_one_bill(self._bill(check_number="1042"))
        assert captured.get("check_number") == "1042"
```

- [ ] **Step 7: Run the full `TestProcessOneBill` class — all should pass**

```
uv run pytest tests/test_web_app.py::TestProcessOneBill -v
```

Expected: 9 passed

- [ ] **Step 8: Run full suite to check no regressions**

```
uv run pytest tests/ -q
```

Expected: all pass

- [ ] **Step 9: Commit**

```
git add web/app.py tests/test_web_app.py
git commit -m "feat: guard _process_one_bill on configured accounts; pass ap/checking GUIDs explicitly"
```

---

## Task 4: Add processing accounts settings page (routes + templates)

**Files:**
- Modify: `web/app.py`
- Create: `web/templates/settings_processing_accounts.html`
- Create: `web/templates/partials/processing_ap_section.html`
- Create: `web/templates/partials/processing_checking_section.html`
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Add `isolated_settings` fixture to `tests/test_web_app.py`**

Add after the existing `tmp_queue` fixture:

```python
@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Replace the global settings singleton with a fresh temp-file-backed instance."""
    from bill_processor.web import app as web_app
    from bill_processor.settings_manager import SettingsManager
    fresh = SettingsManager(settings_file=tmp_path / "test_settings.json")
    monkeypatch.setattr(web_app, "settings", fresh)
    return fresh
```

- [ ] **Step 2: Write the failing tests**

Add this class to the bottom of `tests/test_web_app.py`:

```python
class TestProcessingAccountsSettings:
    AP_GUID = "e" * 32
    CHECKING_GUID = "c" * 32

    def test_get_page_returns_200(self, client, isolated_settings, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_payable_accounts",
                            lambda: [{"guid": self.AP_GUID, "name": "Accounts Payable", "description": ""}])
        monkeypatch.setattr(web_app.gnucash_db, "get_checking_accounts",
                            lambda: [{"guid": self.CHECKING_GUID, "name": "Checking", "description": ""}])
        response = client.get("/settings/processing-accounts")
        assert response.status_code == 200

    def test_save_ap_account_persists_to_settings(self, client, isolated_settings, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_payable_accounts",
                            lambda: [{"guid": self.AP_GUID, "name": "Accounts Payable", "description": ""}])
        response = client.post("/settings/processing-accounts/ap-account",
                               data={"ap_account_guid": self.AP_GUID})
        assert response.status_code == 200
        assert isolated_settings.ap_account_guid == self.AP_GUID

    def test_save_checking_account_persists_to_settings(self, client, isolated_settings, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_checking_accounts",
                            lambda: [{"guid": self.CHECKING_GUID, "name": "Checking", "description": ""}])
        response = client.post("/settings/processing-accounts/checking-account",
                               data={"checking_account_guid": self.CHECKING_GUID})
        assert response.status_code == 200
        assert isolated_settings.checking_account_guid == self.CHECKING_GUID

    def test_save_invalid_ap_account_guid_returns_error(self, client, isolated_settings, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_payable_accounts",
                            lambda: [{"guid": self.AP_GUID, "name": "Accounts Payable", "description": ""}])
        response = client.post("/settings/processing-accounts/ap-account",
                               data={"ap_account_guid": "z" * 32})
        assert response.status_code == 200
        assert b"error" in response.content.lower() or b"invalid" in response.content.lower()
        assert isolated_settings.ap_account_guid is None  # unchanged

    def test_save_invalid_checking_account_guid_returns_error(self, client, isolated_settings, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_checking_accounts",
                            lambda: [{"guid": self.CHECKING_GUID, "name": "Checking", "description": ""}])
        response = client.post("/settings/processing-accounts/checking-account",
                               data={"checking_account_guid": "z" * 32})
        assert response.status_code == 200
        assert b"error" in response.content.lower() or b"invalid" in response.content.lower()
        assert isolated_settings.checking_account_guid is None  # unchanged
```

- [ ] **Step 3: Run tests to verify they fail**

```
uv run pytest tests/test_web_app.py::TestProcessingAccountsSettings -v
```

Expected: `404 Not Found` (routes don't exist yet)

- [ ] **Step 4: Create the A/P section partial**

Create `web/templates/partials/processing_ap_section.html`:

```html
<section class="settings-section" id="ap-section">
  <h3>Accounts Payable Account</h3>
  <p class="help-text">Select the A/P account used when posting bills.</p>
  {% if error_ap %}
  <p class="error-msg">&#10007; {{ error_ap }}</p>
  {% endif %}
  {% if saved_ap %}
  <p class="success-msg">&#10003; Saved</p>
  {% endif %}
  {% for acct in payable_accounts %}
  <label class="account-checkbox">
    <input type="radio" name="ap_account_guid" value="{{ acct.guid }}"
           {% if acct.guid == current_ap_guid %}checked{% endif %}
           hx-post="/settings/processing-accounts/ap-account"
           hx-include="[name='ap_account_guid']"
           hx-target="#ap-section"
           hx-swap="outerHTML">
    <span class="account-name">{{ acct.name }}</span>
  </label>
  {% endfor %}
  {% if not payable_accounts %}
  <p class="help-text">No A/P accounts found in GnuCash.</p>
  {% endif %}
</section>
```

- [ ] **Step 5: Create the checking section partial**

Create `web/templates/partials/processing_checking_section.html`:

```html
<section class="settings-section" id="checking-section">
  <h3>Checking Account</h3>
  <p class="help-text">Select the bank account used when paying bills.</p>
  {% if error_checking %}
  <p class="error-msg">&#10007; {{ error_checking }}</p>
  {% endif %}
  {% if saved_checking %}
  <p class="success-msg">&#10003; Saved</p>
  {% endif %}
  {% for acct in checking_accounts %}
  <label class="account-checkbox">
    <input type="radio" name="checking_account_guid" value="{{ acct.guid }}"
           {% if acct.guid == current_checking_guid %}checked{% endif %}
           hx-post="/settings/processing-accounts/checking-account"
           hx-include="[name='checking_account_guid']"
           hx-target="#checking-section"
           hx-swap="outerHTML">
    <span class="account-name">{{ acct.name }}</span>
  </label>
  {% endfor %}
  {% if not checking_accounts %}
  <p class="help-text">No bank accounts found in GnuCash.</p>
  {% endif %}
</section>
```

- [ ] **Step 6: Create the main settings page template**

Create `web/templates/settings_processing_accounts.html`:

```html
{% extends "base.html" %}
{% block title %}Processing Accounts - GnuCash Bill Processor{% endblock %}
{% block content %}
<div class="settings-container">
  <h2>Processing Accounts</h2>
  <p class="help-text">
    Choose the A/P and checking accounts used when bills are posted and paid.
    Both must be selected before bills can be processed.
  </p>

  {% include "partials/processing_ap_section.html" %}
  {% include "partials/processing_checking_section.html" %}

  <div class="settings-footer">
    <a href="/settings" class="btn-secondary">&#8592; Back to Settings</a>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 7: Add the three routes to `web/app.py`**

Find the settings routes section. Add these three routes after the existing `/settings/reset` route:

```python
@app.get("/settings/processing-accounts", response_class=HTMLResponse)
def get_processing_accounts_settings(request: Request):
    """Render the processing accounts selection page."""
    return templates.TemplateResponse(request, "settings_processing_accounts.html", {
        "payable_accounts": gnucash_db.get_payable_accounts(),
        "checking_accounts": gnucash_db.get_checking_accounts(),
        "current_ap_guid": settings.ap_account_guid,
        "current_checking_guid": settings.checking_account_guid,
    })


@app.post("/settings/processing-accounts/ap-account", response_class=HTMLResponse)
def save_ap_account(request: Request, ap_account_guid: str = Form(...)):
    """HTMX — save selected A/P account GUID and return updated section."""
    payable_accounts = gnucash_db.get_payable_accounts()
    valid_guids = {a["guid"] for a in payable_accounts}
    if ap_account_guid not in valid_guids:
        return templates.TemplateResponse(request, "partials/processing_ap_section.html", {
            "payable_accounts": payable_accounts,
            "current_ap_guid": settings.ap_account_guid,
            "error_ap": "Invalid account — please select from the list.",
            "saved_ap": False,
        })
    settings.ap_account_guid = ap_account_guid
    return templates.TemplateResponse(request, "partials/processing_ap_section.html", {
        "payable_accounts": payable_accounts,
        "current_ap_guid": ap_account_guid,
        "error_ap": None,
        "saved_ap": True,
    })


@app.post("/settings/processing-accounts/checking-account", response_class=HTMLResponse)
def save_checking_account(request: Request, checking_account_guid: str = Form(...)):
    """HTMX — save selected checking account GUID and return updated section."""
    checking_accounts = gnucash_db.get_checking_accounts()
    valid_guids = {a["guid"] for a in checking_accounts}
    if checking_account_guid not in valid_guids:
        return templates.TemplateResponse(request, "partials/processing_checking_section.html", {
            "checking_accounts": checking_accounts,
            "current_checking_guid": settings.checking_account_guid,
            "error_checking": "Invalid account — please select from the list.",
            "saved_checking": False,
        })
    settings.checking_account_guid = checking_account_guid
    return templates.TemplateResponse(request, "partials/processing_checking_section.html", {
        "checking_accounts": checking_accounts,
        "current_checking_guid": checking_account_guid,
        "error_checking": None,
        "saved_checking": True,
    })
```

- [ ] **Step 8: Run the tests — expect them to pass**

```
uv run pytest tests/test_web_app.py::TestProcessingAccountsSettings -v
```

Expected: 5 passed

- [ ] **Step 9: Run full suite**

```
uv run pytest tests/ -q
```

Expected: all pass

- [ ] **Step 10: Commit**

```
git add web/app.py web/templates/settings_processing_accounts.html web/templates/partials/processing_ap_section.html web/templates/partials/processing_checking_section.html tests/test_web_app.py
git commit -m "feat: add processing accounts settings page with HTMX save-on-click"
```

---

## Task 5: Dashboard button gating and navigation links

**Files:**
- Modify: `web/app.py` (GET / and GET /partials/queued-bills)
- Modify: `web/templates/partials/queued_bills.html`
- Modify: `web/templates/settings.html`
- Test: `tests/test_web_app.py`

- [ ] **Step 1: Write the failing tests**

Add this class to the bottom of `tests/test_web_app.py`:

```python
class TestDashboardButtonGating:
    """Process buttons are disabled when processing accounts are not configured."""

    def test_process_buttons_disabled_when_accounts_not_configured(
        self, client, tmp_queue, monkeypatch
    ):
        from bill_processor.web import app as web_app
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", None)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", None)
        tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")

        response = client.get("/partials/queued-bills")
        assert response.status_code == 200
        assert b"disabled" in response.content

    def test_process_buttons_enabled_when_accounts_configured(
        self, client, tmp_queue, monkeypatch
    ):
        from bill_processor.web import app as web_app
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", "c" * 32)
        tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")

        response = client.get("/partials/queued-bills")
        assert response.status_code == 200
        assert b"disabled" not in response.content
```

- [ ] **Step 2: Run tests to verify they fail**

```
uv run pytest tests/test_web_app.py::TestDashboardButtonGating -v
```

Expected: `test_process_buttons_disabled_when_accounts_not_configured` fails (no `disabled` in response yet); `test_process_buttons_enabled_when_accounts_configured` may pass trivially.

- [ ] **Step 3: Update `GET /partials/queued-bills` in `web/app.py`**

Replace the existing route (around line 442):

```python
@app.get("/partials/queued-bills", response_class=HTMLResponse)
def get_queued_bills_partial(request: Request):
    """Return the queued bills card (for HTMX polling)."""
    queue = queue_io.read_queue()
    return templates.TemplateResponse(request, "partials/queued_bills.html", {
        "queue": queue,
        "last_error": None,
        "processing_accounts_configured": settings.processing_accounts_configured,
    })
```

- [ ] **Step 4: Update `GET /` in `web/app.py`**

In the `GET /` route context dict (around line 114), add:

```python
        "processing_accounts_configured": settings.processing_accounts_configured,
```

alongside the existing keys.

- [ ] **Step 5: Update `queued_bills.html` template**

Replace `web/templates/partials/queued_bills.html` with:

```html
<div class="card" id="queued-bills"
     hx-get="/partials/queued-bills"
     hx-trigger="every 30s"
     hx-swap="outerHTML">
  <h2>Queued Bills</h2>
  {% if last_error %}
  <p class="error-msg">&#9888; {{ last_error }}</p>
  {% endif %}
  {% if queue %}
    <p class="status-warn">&#9888; {{ queue|length }} bill(s) waiting to be processed</p>
    <table>
      <thead><tr><th>Vendor</th><th>Amount</th><th>Memo</th><th>Date</th><th>Check #</th><th></th></tr></thead>
      <tbody>
        {% for bill in queue %}
        <tr>
          <td>{{ bill.vendor_name }}</td>
          <td>${{ "%.2f"|format(bill.amount) }}</td>
          <td>{{ bill.memo }}</td>
          <td>{{ bill.date }}</td>
          <td>{{ bill.check_number }}</td>
          <td>
            <button hx-post="/bills/queue/{{ bill._index }}/process"
                    hx-target="#queued-bills"
                    hx-swap="outerHTML"
                    {% if not processing_accounts_configured %}disabled{% endif %}>Process</button>
            <button hx-delete="/bills/queue/{{ bill._index }}"
                    hx-target="#queued-bills"
                    hx-swap="outerHTML"
                    hx-confirm="Remove this bill from the queue?">Remove</button>
            <form style="display:inline"
                  hx-patch="/bills/queue/{{ bill._index }}"
                  hx-target="#queued-bills"
                  hx-swap="outerHTML">
              <input type="hidden" name="vendor_name" value="{{ bill.vendor_name }}">
              <input type="hidden" name="amount" value="{{ bill.amount }}">
              <input type="hidden" name="memo" value="{{ bill.memo }}">
              <input type="hidden" name="bill_date" value="{{ bill.date }}">
              <input type="text" name="check_number" value="{{ bill.check_number }}"
                     placeholder="Check #" style="width:5rem">
              <button type="submit">Save</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    <div style="margin-top:0.75rem">
      <button class="btn-primary"
        hx-post="/bills/queue/process"
        hx-target="#queued-bills"
        hx-swap="outerHTML"
        {% if not processing_accounts_configured %}disabled{% endif %}>Process All</button>
      <a href="/settings/processing-accounts" style="margin-left:0.75rem; font-size:0.9em;">
        {% if not processing_accounts_configured %}&#9888; {% endif %}Configure processing accounts
      </a>
    </div>
  {% else %}
    <p class="status-ok">&#10003; No bills queued</p>
  {% endif %}
</div>
```

- [ ] **Step 6: Update all remaining `queued_bills.html` call sites in `web/app.py`**

Five additional routes render `queued_bills.html` but don't yet pass `processing_accounts_configured`. Add `"processing_accounts_configured": settings.processing_accounts_configured` to the context dict of each:

- Line 157: `remove_from_queue` (DELETE `/bills/queue/{index}`)
- Line 237: `process_all` (POST `/bills/queue/process`)
- Line 250: `process_one` error branch (POST `/bills/queue/{index}/process`)
- Line 258: `process_one` success branch (POST `/bills/queue/{index}/process`)
- Line 285: `edit_queue_item` (PATCH `/bills/queue/{index}`)

After this step every call site that renders `queued_bills.html` passes the flag. Without this, buttons will always appear disabled after any delete/edit/process-result action.

- [ ] **Step 7: Add "Processing Accounts →" link to `settings.html`**

In `web/templates/settings.html`, add a navigation link as the first element inside `<div class="settings-container">`, before the `<h2>` heading:

```html
  <div style="margin-bottom:1rem">
    <a href="/settings/processing-accounts" class="btn-secondary">Processing Accounts &#8594;</a>
  </div>
```

- [ ] **Step 8: Run the gating tests**

```
uv run pytest tests/test_web_app.py::TestDashboardButtonGating -v
```

Expected: 2 passed

- [ ] **Step 9: Run full suite**

```
uv run pytest tests/ -q
```

Expected: all pass

- [ ] **Step 10: Commit**

```
git add web/app.py web/templates/partials/queued_bills.html web/templates/settings.html tests/test_web_app.py
git commit -m "feat: gate process buttons on configured accounts; add navigation links"
```

---

## Final Verification

- [ ] Run the complete test suite one final time:

```
uv run pytest tests/ -v
```

Expected: all tests pass, no warnings beyond the known FastAPI `on_event` deprecation.

- [ ] Manual smoke test: start the server and verify:
  1. Dashboard process buttons are greyed out when no accounts configured
  2. "Configure processing accounts" link opens `/settings/processing-accounts`
  3. Selecting A/P and checking accounts saves them and shows ✓ Saved
  4. Dashboard process buttons become active after both are configured
  5. Processing a bill logs the A/P and checking account names at INFO level

```
uv run uvicorn bill_processor.web.app:app --reload --port 7432
```

# Test Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the test runner to execute all test files and add coverage for `queue_io.py`, `main.py`, and five untested web API routes.

**Architecture:** Four independent tasks in dependency order — runner fix first (validates baseline), then new test files, then web additions. All new tests follow existing patterns: `monkeypatch` + `tmp_path` for file I/O tests, `MagicMock` + `monkeypatch` for web tests, real test DB via `db_connection` fixture for `main.py` workflow tests.

**Tech Stack:** pytest, FastAPI TestClient, unittest.mock, pytest tmp_path/monkeypatch fixtures

---

## File Map

| Action | File |
|--------|------|
| Modify | `tests/run_tests.py` |
| Create | `tests/test_queue_io.py` |
| Create | `tests/test_main.py` |
| Modify | `tests/test_web_app.py` |

---

## Task 1: Fix `tests/run_tests.py`

**Files:**
- Modify: `tests/run_tests.py`

- [ ] **Step 1: Run the current runner to confirm only 19 tests execute**

```bash
uv run python tests/run_tests.py
```
Expected: `19 passed` from `test_bill_workflow.py` only, then `EOFError` on the prompt (non-interactive).

- [ ] **Step 2: Update the automated test invocation to run all test files**

Change line 20 in `tests/run_tests.py` from:
```python
        str(test_dir / "test_bill_workflow.py"),
```
to:
```python
        str(test_dir),
```

- [ ] **Step 3: Run the full suite to verify all existing tests pass**

```bash
uv run pytest tests/ -v -m "not manual" 2>&1 | tail -20
```
Expected: All tests pass. Count will be much higher than 19.

- [ ] **Step 4: Commit**

```bash
git add tests/run_tests.py
git commit -m "fix: run_tests.py now discovers all test files, not just test_bill_workflow"
```

---

## Task 2: Create `tests/test_queue_io.py`

**Files:**
- Create: `tests/test_queue_io.py`

- [ ] **Step 1: Write `test_queue_io.py` in full**

```python
"""Tests for web/queue_io.py — bill queue file I/O."""
import pytest
from datetime import date
from pathlib import Path

from bill_processor import config
from bill_processor.web import queue_io


@pytest.fixture
def queue_path(tmp_path, monkeypatch):
    path = tmp_path / "bills_to_process.txt"
    monkeypatch.setattr(config, "BILLS_INPUT_PATH", path)
    return path


class TestReadQueue:
    def test_missing_file_returns_empty_list(self, queue_path):
        assert queue_io.read_queue() == []

    def test_empty_file_returns_empty_list(self, queue_path):
        queue_path.write_text("")
        assert queue_io.read_queue() == []

    def test_single_bill_parsed(self, queue_path):
        queue_path.write_text("Acme Corp, 100.00, supplies, 2026-01-15\n")
        result = queue_io.read_queue()
        assert len(result) == 1
        assert result[0]["vendor_name"] == "Acme Corp"
        assert result[0]["amount"] == 100.00
        assert result[0]["memo"] == "supplies"
        assert result[0]["date"] == date(2026, 1, 15)
        assert result[0]["_index"] == 0

    def test_bill_with_check_number_parsed(self, queue_path):
        queue_path.write_text("Acme Corp, 100.00, supplies, 2026-01-15, 1234\n")
        result = queue_io.read_queue()
        assert result[0]["check_number"] == "1234"

    def test_bill_without_check_number_has_empty_string(self, queue_path):
        queue_path.write_text("Acme Corp, 100.00, supplies, 2026-01-15\n")
        result = queue_io.read_queue()
        assert result[0]["check_number"] == ""

    def test_malformed_lines_skipped(self, queue_path):
        queue_path.write_text("bad line\nAcme Corp, 100.00, supplies, 2026-01-15\n")
        result = queue_io.read_queue()
        assert len(result) == 1

    def test_index_reflects_file_line_position(self, queue_path):
        queue_path.write_text(
            "bad line\n"
            "Acme Corp, 100.00, supplies, 2026-01-15\n"
        )
        result = queue_io.read_queue()
        assert result[0]["_index"] == 1

    def test_multiple_bills_all_parsed(self, queue_path):
        queue_path.write_text(
            "Acme Corp, 100.00, supplies, 2026-01-15\n"
            "Bob Plumbing, 200.00, repair, 2026-02-01\n"
        )
        result = queue_io.read_queue()
        assert len(result) == 2
        assert result[0]["vendor_name"] == "Acme Corp"
        assert result[1]["vendor_name"] == "Bob Plumbing"
        assert result[0]["_index"] == 0
        assert result[1]["_index"] == 1


class TestAddBill:
    def test_appends_bill_line(self, queue_path):
        queue_io.add_bill("Acme Corp", 100.0, "supplies", date(2026, 1, 15))
        line = queue_path.read_text().strip()
        assert line == "Acme Corp, 100.00, supplies, 2026-01-15"

    def test_check_number_included_when_provided(self, queue_path):
        queue_io.add_bill("Acme Corp", 100.0, "supplies", date(2026, 1, 15), "1234")
        line = queue_path.read_text().strip()
        assert line == "Acme Corp, 100.00, supplies, 2026-01-15, 1234"

    def test_check_number_omitted_when_empty(self, queue_path):
        queue_io.add_bill("Acme Corp", 100.0, "supplies", date(2026, 1, 15), "")
        line = queue_path.read_text().strip()
        assert line == "Acme Corp, 100.00, supplies, 2026-01-15"

    def test_creates_file_if_missing(self, queue_path):
        assert not queue_path.exists()
        queue_io.add_bill("Acme Corp", 100.0, "supplies", date(2026, 1, 15))
        assert queue_path.exists()

    def test_appends_to_existing_file(self, queue_path):
        queue_path.write_text("Acme Corp, 100.00, supplies, 2026-01-15\n")
        queue_io.add_bill("Bob Plumbing", 200.0, "repair", date(2026, 2, 1))
        lines = [l for l in queue_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 2


class TestRemoveBill:
    def test_removes_correct_line(self, queue_path):
        queue_path.write_text(
            "Acme Corp, 100.00, supplies, 2026-01-15\n"
            "Bob Plumbing, 200.00, repair, 2026-02-01\n"
        )
        result = queue_io.remove_bill(0)
        assert result is True
        assert "Acme Corp" not in queue_path.read_text()
        assert "Bob Plumbing" in queue_path.read_text()

    def test_preserves_other_lines(self, queue_path):
        queue_path.write_text(
            "A, 10.00, m, 2026-01-01\n"
            "B, 20.00, m, 2026-01-02\n"
            "C, 30.00, m, 2026-01-03\n"
        )
        queue_io.remove_bill(1)
        remaining = [l for l in queue_path.read_text().splitlines() if l.strip()]
        assert len(remaining) == 2
        assert any("A" in l for l in remaining)
        assert any("C" in l for l in remaining)

    def test_returns_false_on_out_of_range_index(self, queue_path):
        queue_path.write_text("A, 10.00, m, 2026-01-01\n")
        assert queue_io.remove_bill(5) is False

    def test_returns_false_on_negative_index(self, queue_path):
        queue_path.write_text("A, 10.00, m, 2026-01-01\n")
        assert queue_io.remove_bill(-1) is False


class TestUpdateBill:
    def test_replaces_correct_line(self, queue_path):
        queue_path.write_text("Old Corp, 50.00, old memo, 2026-01-01\n")
        result = queue_io.update_bill(0, "New Corp", 99.99, "new memo", date(2026, 6, 15))
        assert result is True
        assert queue_path.read_text().strip() == "New Corp, 99.99, new memo, 2026-06-15"

    def test_preserves_other_lines(self, queue_path):
        queue_path.write_text(
            "A, 10.00, m, 2026-01-01\n"
            "B, 20.00, m, 2026-01-02\n"
        )
        queue_io.update_bill(0, "Updated", 15.00, "m", date(2026, 1, 1))
        lines = [l for l in queue_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 2
        assert "B" in lines[1]

    def test_returns_false_on_out_of_range(self, queue_path):
        queue_path.write_text("A, 10.00, m, 2026-01-01\n")
        assert queue_io.update_bill(5, "B", 20.0, "m", date(2026, 1, 1)) is False

    def test_check_number_roundtrip(self, queue_path):
        queue_io.add_bill("Acme", 100.0, "test", date(2026, 1, 1), "5678")
        assert "5678" in queue_path.read_text()
        queue_io.update_bill(0, "Acme", 100.0, "test", date(2026, 1, 1))
        line = queue_path.read_text().strip()
        assert "5678" not in line
        assert line == "Acme, 100.00, test, 2026-01-01"
```

- [ ] **Step 2: Run the new tests to verify they all pass**

```bash
uv run pytest tests/test_queue_io.py -v
```
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_queue_io.py
git commit -m "test: add test_queue_io.py covering all queue file CRUD operations"
```

---

## Task 3: Create `tests/test_main.py`

**Files:**
- Create: `tests/test_main.py`

**Context:** `process_bill()` takes a `VendorManager` as its first argument, so tests pass a `MagicMock` for it. The `db_connection` fixture from `conftest.py` patches `gnucash_db.config.GNUCASH_DB_PATH` to a temp copy of the real database, so actual GnuCash operations run against real (isolated) data. `process_input_file()` constructs `VendorManager` internally, so that is patched via `monkeypatch.setattr`.

- [ ] **Step 1: Write `test_main.py` in full**

```python
"""Tests for main.py — CLI bill processing workflow."""
import pytest
import sqlite3
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import main
from bill_processor import gnucash_db


def _make_mock_vm(vendor_guid, expense_guid, display_name="Test Vendor"):
    """Return a VendorManager mock wired up for a success path."""
    mock_vm = MagicMock()
    mock_vm.find_vendor.return_value = (
        {"gnucash_guid": vendor_guid, "display_name": display_name},
        "exact",
    )
    mock_vm.get_or_create_expense_account.return_value = expense_guid
    mock_vm.vendors = {"vendors": {}, "aliases": {}}
    return mock_vm


class TestProcessBill:
    def test_success_returns_true(self, db_connection, test_vendor_guid, test_accounts):
        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])
        with patch("main.confirm_proceed", return_value=True):
            result = main.process_bill(
                mock_vm,
                "Test Vendor",
                100.00,
                "test memo",
                date.today(),
                test_accounts["checking_account"],
            )
        assert result is True

    def test_check_number_passed_to_pay_bill(self, db_connection, test_vendor_guid, test_accounts):
        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])
        captured = {}
        original = gnucash_db.pay_bill

        def capturing(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        with patch("main.confirm_proceed", return_value=True):
            with patch.object(gnucash_db, "pay_bill", side_effect=capturing):
                main.process_bill(
                    mock_vm,
                    "Test Vendor",
                    100.00,
                    "test memo",
                    date.today(),
                    test_accounts["checking_account"],
                    check_number="9999",
                )
        assert captured.get("check_number") == "9999"

    def test_fuzzy_match_user_confirms_alias(self, db_connection, test_vendor_guid, test_accounts):
        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])
        mock_vm.find_vendor.return_value = (
            {"gnucash_guid": test_vendor_guid, "display_name": "Test Vendor"},
            "fuzzy",
        )
        vendor_key = "test_vendor"
        mock_vm.vendors = {
            "vendors": {vendor_key: {"gnucash_guid": test_vendor_guid, "display_name": "Test Vendor"}},
            "aliases": {},
        }
        with patch("main.confirm_proceed", return_value=True):
            result = main.process_bill(
                mock_vm,
                "Tset Vendor",
                100.00,
                "memo",
                date.today(),
                test_accounts["checking_account"],
            )
        assert result is True
        mock_vm.add_alias.assert_called_once()

    def test_fuzzy_match_user_declines_alias(self, db_connection, test_vendor_guid, test_accounts):
        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])
        mock_vm.find_vendor.return_value = (
            {"gnucash_guid": test_vendor_guid, "display_name": "Test Vendor"},
            "fuzzy",
        )
        mock_vm.vendors = {
            "vendors": {"test_vendor": {"gnucash_guid": test_vendor_guid, "display_name": "Test Vendor"}},
            "aliases": {},
        }
        with patch("main.confirm_proceed", return_value=False):
            result = main.process_bill(
                mock_vm,
                "Tset Vendor",
                100.00,
                "memo",
                date.today(),
                test_accounts["checking_account"],
            )
        assert result is True
        mock_vm.add_alias.assert_not_called()

    def test_vendor_not_found_user_skips_returns_false(self):
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (None, "not_found")
        with patch("main.confirm_proceed", return_value=False):
            result = main.process_bill(
                mock_vm,
                "Unknown Vendor",
                50.00,
                "memo",
                date.today(),
                "checking_guid_placeholder",
            )
        assert result is False

    def test_vendor_not_found_user_creates_returns_true(self, db_connection, test_vendor_guid, test_accounts):
        mock_vm = MagicMock()
        mock_vm.find_vendor.side_effect = [
            (None, "not_found"),
        ]
        new_vendor = {"gnucash_guid": test_vendor_guid, "display_name": "New Vendor"}
        mock_vm.create_new_vendor.return_value = new_vendor
        mock_vm.get_or_create_expense_account.return_value = test_accounts["expense_account"]

        confirm_responses = iter([True, True])
        with patch("main.confirm_proceed", side_effect=lambda _: next(confirm_responses)):
            result = main.process_bill(
                mock_vm,
                "New Vendor",
                75.00,
                "memo",
                date.today(),
                test_accounts["checking_account"],
            )
        assert result is True
        mock_vm.create_new_vendor.assert_called_once_with("New Vendor")


class TestProcessInputFile:
    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            main.process_input_file(tmp_path / "nonexistent.txt")

    def test_empty_file_returns_zero_counts(self, tmp_path):
        input_file = tmp_path / "bills.txt"
        input_file.write_text("")
        result = main.process_input_file(input_file)
        assert result == {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    def test_user_cancels_at_confirm_returns_skipped(self, tmp_path):
        input_file = tmp_path / "bills.txt"
        input_file.write_text("Acme Corp, 100.00, supplies, 2026-01-15\n")
        with patch("main.confirm_proceed", return_value=False):
            result = main.process_input_file(input_file)
        assert result["skipped"] == 1
        assert result["success"] == 0

    def test_single_bill_processes_successfully(
        self, db_connection, test_vendor_guid, test_accounts, tmp_path
    ):
        input_file = tmp_path / "bills.txt"
        input_file.write_text("Test Vendor, 100.00, test memo, 2026-01-15\n")

        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])

        with patch("main.VendorManager", return_value=mock_vm):
            with patch("main.confirm_proceed", return_value=True):
                with patch("builtins.input", return_value="1"):
                    with patch.object(
                        gnucash_db,
                        "get_checking_accounts",
                        return_value=[{"name": "Checking", "guid": test_accounts["checking_account"]}],
                    ):
                        result = main.process_input_file(input_file)

        assert result == {"total": 1, "success": 1, "failed": 0, "skipped": 0}

    def test_check_number_from_file_reaches_pay_bill(
        self, db_connection, test_vendor_guid, test_accounts, tmp_path
    ):
        input_file = tmp_path / "bills.txt"
        input_file.write_text("Test Vendor, 100.00, test memo, 2026-01-15, 4242\n")

        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])
        captured = {}
        original = gnucash_db.pay_bill

        def capturing(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        with patch("main.VendorManager", return_value=mock_vm):
            with patch("main.confirm_proceed", return_value=True):
                with patch("builtins.input", return_value="1"):
                    with patch.object(
                        gnucash_db,
                        "get_checking_accounts",
                        return_value=[{"name": "Checking", "guid": test_accounts["checking_account"]}],
                    ):
                        with patch.object(gnucash_db, "pay_bill", side_effect=capturing):
                            main.process_input_file(input_file)

        assert captured.get("check_number") == "4242"

    def test_user_cancels_account_selection_returns_skipped(self, tmp_path):
        input_file = tmp_path / "bills.txt"
        input_file.write_text("Acme Corp, 100.00, supplies, 2026-01-15\n")

        with patch("main.confirm_proceed", return_value=True):
            with patch("builtins.input", side_effect=KeyboardInterrupt):
                with patch.object(
                    gnucash_db,
                    "get_checking_accounts",
                    return_value=[{"name": "Checking", "guid": "abc"}],
                ):
                    result = main.process_input_file(input_file)

        assert result["skipped"] == 1
        assert result["success"] == 0
```

- [ ] **Step 2: Run the new tests to verify they all pass**

```bash
uv run pytest tests/test_main.py -v
```
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_main.py
git commit -m "test: add test_main.py covering process_bill and process_input_file"
```

---

## Task 4: Add missing route tests to `tests/test_web_app.py`

**Files:**
- Modify: `tests/test_web_app.py` (append five new test classes)

**Context:** All new classes follow the existing pattern: import `web_app` inside each test method, use `monkeypatch.setattr` to replace module-level objects, use the `client` fixture from the top of the file. `sync_one_vendor` does NOT validate the key — it always runs a full sync — so no 404 test is written for it.

- [ ] **Step 1: Append five new test classes to `tests/test_web_app.py`**

Add to the end of `tests/test_web_app.py`:

```python
# ---------------------------------------------------------------------------
# TestGetVendors
# ---------------------------------------------------------------------------

class TestGetVendors:
    def test_returns_vendor_list(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.vendors = {
            "vendors": {
                "acme_electric": {
                    "display_name": "Acme Electric",
                    "gnucash_guid": "a" * 32,
                }
            },
            "aliases": {},
        }
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setattr(web_app.gnucash_db, "get_all_vendors", lambda: [{"guid": "a" * 32}])
        response = client.get("/api/vendors")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert data[0]["key"] == "acme_electric"
        assert data[0]["display_name"] == "Acme Electric"
        assert data[0]["synced"] is True

    def test_returns_empty_list_when_no_vendors(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.vendors = {"vendors": {}, "aliases": {}}
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setattr(web_app.gnucash_db, "get_all_vendors", lambda: [])
        response = client.get("/api/vendors")
        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# TestCreateVendorSuccess
# ---------------------------------------------------------------------------

class TestCreateVendorSuccess:
    def test_valid_vendor_returns_key_and_guid(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        created_guid = "c" * 32
        monkeypatch.setattr(web_app.gnucash_db, "create_vendor", lambda **kw: created_guid)
        mock_vm = MagicMock()
        mock_vm.vendors = {"vendors": {}, "aliases": {}}
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        response = client.post("/api/vendors", json={
            "vendor_name": "Bob Plumbing",
            "display_name": "Bob Plumbing",
            "addr_line1": "123 Main St",
            "addr_city": "Cincinnati",
            "addr_state": "OH",
            "addr_zip": "45201",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["ok"] is True
        assert data["guid"] == created_guid
        assert "key" in data


# ---------------------------------------------------------------------------
# TestAccountTypeEndpoints
# ---------------------------------------------------------------------------

class TestAccountTypeEndpoints:
    EXPENSE_ACCOUNTS = [{"name": "Groceries", "guid": "a" * 32, "account_type": "EXPENSE"}]
    PAYABLE_ACCOUNTS = [{"name": "Accounts Payable", "guid": "b" * 32, "account_type": "PAYABLE"}]
    BANK_ACCOUNTS = [{"name": "Checking", "guid": "c" * 32, "account_type": "BANK"}]

    def test_expense_accounts_returns_list(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_accounts_by_type", lambda t: self.EXPENSE_ACCOUNTS)
        response = client.get("/api/accounts/expense")
        assert response.status_code == 200
        assert response.json() == self.EXPENSE_ACCOUNTS

    def test_payable_accounts_returns_list(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_accounts_by_type", lambda t: self.PAYABLE_ACCOUNTS)
        response = client.get("/api/accounts/payable")
        assert response.status_code == 200
        assert response.json() == self.PAYABLE_ACCOUNTS

    def test_bank_accounts_returns_list(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_accounts_by_type", lambda t: self.BANK_ACCOUNTS)
        response = client.get("/api/accounts/bank")
        assert response.status_code == 200
        assert response.json() == self.BANK_ACCOUNTS

    def test_expense_returns_empty_list_when_none(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_accounts_by_type", lambda t: [])
        response = client.get("/api/accounts/expense")
        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# TestVendorKeySync
# ---------------------------------------------------------------------------

class TestVendorKeySync:
    def test_sync_returns_ok(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        mock_sync = MagicMock()
        mock_sync.discover_schema.return_value = True
        monkeypatch.setattr(web_app, "VendorSyncUtility", lambda: mock_sync)
        response = client.post("/api/vendors/any_key/sync")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        mock_sync.sync_gnucash_to_json.assert_called_once()

    def test_schema_discovery_failure_returns_error(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        mock_sync = MagicMock()
        mock_sync.discover_schema.return_value = False
        monkeypatch.setattr(web_app, "VendorSyncUtility", lambda: mock_sync)
        response = client.post("/api/vendors/any_key/sync")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "Schema discovery failed" in data["error"]


# ---------------------------------------------------------------------------
# TestShutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    def test_returns_200(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        from unittest.mock import MagicMock
        # Replace threading in the app module so the daemon thread never fires.
        # Patching os.kill instead would race: monkeypatch restores it before
        # the 0.3s sleep expires, letting the real kill reach the test runner.
        monkeypatch.setattr(web_app, "threading", MagicMock())
        response = client.post("/api/shutdown")
        assert response.status_code == 200
        assert response.json()["ok"] is True
```

- [ ] **Step 2: Run only the new test classes to verify they pass**

```bash
uv run pytest tests/test_web_app.py::TestGetVendors tests/test_web_app.py::TestCreateVendorSuccess tests/test_web_app.py::TestAccountTypeEndpoints tests/test_web_app.py::TestVendorKeySync tests/test_web_app.py::TestShutdown -v
```
Expected: All new tests pass.

- [ ] **Step 3: Run the full test suite to confirm no regressions**

```bash
uv run pytest tests/ -v -m "not manual" 2>&1 | tail -10
```
Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_web_app.py
git commit -m "test: add TestGetVendors, TestCreateVendorSuccess, TestAccountTypeEndpoints, TestVendorKeySync, TestShutdown to test_web_app"
```

# gnucash_db Query & Utility Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 43 tests across three new files to bring `gnucash_db.py` coverage from ~28% toward ~50%, covering pure utility functions, account query functions, and vendor/bill query functions.

**Architecture:** Three independent test files — pure unit tests (no DB), account query tests, vendor/bill query tests — all calling existing production functions. No mocks anywhere; DB tests use the existing class-scoped `db_connection` fixture (copies real GnuCash DB, patches `bill_processor.config.GNUCASH_DB_PATH`). A shared `tests/helpers.py` module provides `_insert_test_vendor` (moved from `test_vendor_sync.py`) and a new `_insert_test_invoice` helper for bill query setup.

**Tech Stack:** pytest, sqlite3, uuid, re, datetime, `db_connection`/`test_db_path` fixtures from `tests/conftest.py`, functions from `bill_processor.gnucash_db`.

---

## Background

**Import convention:** All test files use `from bill_processor.gnucash_db import ...`. This is correct because `pyproject.toml` maps the project root to the `bill_processor` namespace (`package-dir = {"bill_processor" = "."}`).

**`db_connection` fixture:** Defined in `tests/conftest.py` (class-scoped). It copies the real GnuCash DB to a temp dir, patches `gnucash_db.config.GNUCASH_DB_PATH` to point to the copy, and yields the path. Functions in `gnucash_db.py` call `get_connection()` which uses that patched path.

**`_insert_test_vendor`:** Currently defined locally in `tests/test_vendor_sync.py` (line 251). This plan moves it to `tests/helpers.py` and imports it from there in both `test_vendor_sync.py` and `test_vendor_bill_queries.py`.

**`invoices` table schema note:** The `invoices` table has **no `is_posted` column**. Posted/unposted state is determined by `post_lot` being NULL (unposted) or non-NULL (posted). `get_bills_by_status` uses an INNER JOIN on the `vendors` table, so a matching vendor row must exist before inserting a test invoice.

**Running tests for this feature:**
```bash
uv run pytest tests/test_gnucash_db_utils.py -v
uv run pytest tests/test_account_queries.py -v
uv run pytest tests/test_vendor_bill_queries.py -v
uv run pytest tests/ -q
```

---

## Files

| File | Action |
|---|---|
| `pyproject.toml` | **Modify** — add `"tests"` to `pythonpath` |
| `tests/helpers.py` | **Modify** — add `_insert_test_vendor` and `_insert_test_invoice` |
| `tests/test_vendor_sync.py` | **Modify** — remove local `_insert_test_vendor`, import from helpers |
| `tests/test_gnucash_db_utils.py` | **Create** — 9 pure unit tests |
| `tests/test_account_queries.py` | **Create** — 15 DB query tests |
| `tests/test_vendor_bill_queries.py` | **Create** — 19 vendor/bill query tests |

---

## Task 1: Add "tests" to pytest pythonpath

**Files:**
- Modify: `pyproject.toml:33-35`

Enables `from helpers import ...` in new test files without `importlib.util` boilerplate.

- [ ] **Step 1: Update pyproject.toml**

Change line 35 from:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```
To:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = [".", "tests"]
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `uv run pytest tests/ -q`
Expected: All existing tests pass (no change to behavior — only adds `tests/` to sys.path).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add tests/ to pytest pythonpath for direct helper imports"
```

---

## Task 2: Move `_insert_test_vendor` to helpers.py and update test_vendor_sync.py

**Files:**
- Modify: `tests/helpers.py`
- Modify: `tests/test_vendor_sync.py:247-304` (remove local function, add import)

`helpers.py` already has `_insert_lock`. We are adding `_insert_test_vendor` verbatim from `test_vendor_sync.py`. Then `test_vendor_sync.py` imports it from `helpers`.

- [ ] **Step 1: Add `_insert_test_vendor` to `tests/helpers.py`**

Replace the entire contents of `tests/helpers.py` with:

```python
"""Shared test helpers — importable by any test file."""
import sqlite3
import uuid


def _insert_lock(db_path, hostname, pid):
    """Insert a lock row directly into gnclock to simulate a held lock."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO gnclock VALUES (?, ?)", (hostname, pid))
    conn.commit()
    conn.close()


def _insert_test_vendor(db_path, name, guid=None, vendor_id=None, **addr_fields):
    """Insert a minimal vendor row into the SQLite DB at db_path.

    Uses PRAGMA table_info to discover available columns so it works across
    GnuCash schema versions. Returns the inserted GUID.
    """
    guid = guid or uuid.uuid4().hex
    vendor_id = vendor_id or "099999"

    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        "SELECT guid FROM commodities WHERE mnemonic='USD' AND namespace='CURRENCY' LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        raise RuntimeError("USD commodity not found in test DB")
    currency_guid = row[0]

    # Discover available columns
    cur = conn.execute("PRAGMA table_info(vendors)")
    available = {r[1] for r in cur.fetchall()}

    base = {
        "guid": guid,
        "id": vendor_id,
        "name": name,
        "currency": currency_guid,
        "active": 1,
        "tax_override": 0,
        "notes": "",
        "addr_name": addr_fields.get("addr_name", ""),
        "addr_addr1": addr_fields.get("addr_addr1", ""),
        "addr_addr2": addr_fields.get("addr_addr2", ""),
        "addr_addr3": addr_fields.get("addr_addr3", ""),
        "addr_addr4": addr_fields.get("addr_addr4", ""),
        "addr_phone": addr_fields.get("addr_phone", ""),
        "addr_fax": addr_fields.get("addr_fax", ""),
        "addr_email": addr_fields.get("addr_email", ""),
        "tax_inc": "",
        # tax_table is excluded: it is a FK reference to the tax tables table.
        # SQLite does not enforce FKs by default, but excluding is safer.
    }

    insert_data = {k: v for k, v in base.items() if k in available}
    cols = ", ".join(insert_data.keys())
    placeholders = ", ".join("?" * len(insert_data))
    conn.execute(
        f"INSERT INTO vendors ({cols}) VALUES ({placeholders})",
        list(insert_data.values())
    )
    conn.commit()
    conn.close()
    return guid
```

- [ ] **Step 2: Update `tests/test_vendor_sync.py` — remove local function, add import**

Insert this import on a new line after line 8 (`import pytest`) and before line 10 (`from vendor_sync import ...`):

```python
from helpers import _insert_test_vendor
```

Then delete lines 247–304 (the separator comment block and the entire `_insert_test_vendor` function definition):

```python
# ---------------------------------------------------------------------------
# Helper — insert a vendor row directly into the test DB
# ---------------------------------------------------------------------------

def _insert_test_vendor(db_path, name, guid=None, vendor_id=None, **addr_fields):
    ...  # (entire function through line 304)
```

Also remove line 6 (`import uuid`) — confirmed: `uuid` is only referenced inside the deleted function (line 257: `guid = guid or uuid.uuid4().hex`). It is not used anywhere else in `test_vendor_sync.py`.

- [ ] **Step 3: Run test_vendor_sync.py to verify no regression**

Run: `uv run pytest tests/test_vendor_sync.py -v`
Expected: All 47 tests pass. If any fail, the import is incorrect — re-check step 2.

- [ ] **Step 4: Commit**

```bash
git add tests/helpers.py tests/test_vendor_sync.py
git commit -m "refactor: move _insert_test_vendor from test_vendor_sync.py to tests/helpers.py"
```

---

## Task 3: Add `_insert_test_invoice` to helpers.py

**Files:**
- Modify: `tests/helpers.py` (append new function)

- [ ] **Step 1: Add `_insert_test_invoice` to `tests/helpers.py`**

Append the following function to the end of `tests/helpers.py`:

```python


def _insert_test_invoice(db_path, vendor_guid, posted=False, invoice_id=None, guid=None):
    """Insert a minimal invoice (bill) row into the invoices table.

    Uses PRAGMA table_info to discover available columns so it works across
    GnuCash schema versions. Returns the inserted GUID.

    posted=False → post_lot=NULL (unposted bill)
    posted=True  → post_lot='placeholder' (non-NULL; no real lots row needed.
                   The LEFT JOIN in get_bills_by_status returns NULL for lot columns,
                   satisfying the `l.is_closed IS NULL` check for posted_unpaid queries.)

    The invoices table has NO is_posted column — posted state is controlled
    exclusively by post_lot being NULL or non-NULL.
    """
    guid = guid or uuid.uuid4().hex
    invoice_id = invoice_id or f"TINV{uuid.uuid4().hex[:6].upper()}"

    conn = sqlite3.connect(str(db_path))

    # Get USD currency GUID (mirrors _insert_test_vendor)
    cur = conn.execute(
        "SELECT guid FROM commodities WHERE mnemonic='USD' AND namespace='CURRENCY' LIMIT 1"
    )
    row = cur.fetchone()
    currency_guid = row[0] if row else "a" * 32

    # Discover available columns
    cur = conn.execute("PRAGMA table_info(invoices)")
    available = {r[1] for r in cur.fetchall()}

    base = {
        "guid": guid,
        "id": invoice_id,
        "date_opened": "2026-03-20 00:00:00",
        "owner_type": 4,  # 4 = vendor
        "owner_guid": vendor_guid,
        "currency": currency_guid,
        "active": 1,
        "post_lot": "placeholder" if posted else None,
        "notes": "",
        "charge_amt_num": 0,
        "charge_amt_denom": 1,
        "discount_amt_num": 0,
        "discount_amt_denom": 1,
    }

    insert_data = {k: v for k, v in base.items() if k in available}
    cols = ", ".join(insert_data.keys())
    placeholders = ", ".join("?" * len(insert_data))
    conn.execute(
        f"INSERT INTO invoices ({cols}) VALUES ({placeholders})",
        list(insert_data.values())
    )
    conn.commit()
    conn.close()
    return guid
```

- [ ] **Step 2: Verify helpers.py is importable**

Run from the `tests/` directory:

```bash
cd tests
uv run python -c "from helpers import _insert_test_vendor, _insert_test_invoice; print('OK')"
```

Expected output: `OK`

- [ ] **Step 3: Run full suite to confirm no regression**

Run: `uv run pytest tests/ -q`
Expected: All existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/helpers.py
git commit -m "feat: add _insert_test_invoice helper to tests/helpers.py"
```

---

## Task 4: Create `tests/test_gnucash_db_utils.py` (9 pure unit tests)

**Files:**
- Create: `tests/test_gnucash_db_utils.py`

Pure unit tests — no DB, no fixtures. The format functions fall back to ISO format when no DB schema is loaded (modern GnuCash DBs always use ISO format, so the assertions are safe).

- [ ] **Step 1: Create `tests/test_gnucash_db_utils.py`**

```python
"""Pure utility tests for gnucash_db.py — no DB, no fixtures required."""
import re
from datetime import date, datetime

import pytest

from bill_processor.gnucash_db import (
    generate_guid,
    format_gnucash_date,
    format_gnucash_timestamp,
)


class TestGenerateGuid:
    def test_returns_string(self):
        assert isinstance(generate_guid(), str)

    def test_returns_32_hex_chars(self):
        guid = generate_guid()
        assert len(guid) == 32
        assert all(c in "0123456789abcdef" for c in guid)

    def test_unique_each_call(self):
        assert generate_guid() != generate_guid()


class TestFormatGnucashDate:
    def test_date_returns_iso_string(self):
        result = format_gnucash_date(date(2026, 3, 20))
        assert result == "2026-03-20 00:00:00"

    def test_include_time_false_returns_date_only(self):
        result = format_gnucash_date(date(2026, 3, 20), include_time=False)
        assert result == "2026-03-20"

    def test_datetime_preserves_time(self):
        result = format_gnucash_date(datetime(2026, 3, 20, 14, 30, 0))
        assert result == "2026-03-20 14:30:00"

    def test_return_type_is_string(self):
        result = format_gnucash_date(date(2026, 1, 1))
        assert isinstance(result, str)


class TestFormatGnucashTimestamp:
    def test_returns_string(self):
        assert isinstance(format_gnucash_timestamp(), str)

    def test_matches_datetime_pattern(self):
        result = format_gnucash_timestamp()
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result)
```

- [ ] **Step 2: Run the new file**

Run: `uv run pytest tests/test_gnucash_db_utils.py -v`
Expected: 9 tests pass. If `test_date_returns_iso_string` fails with a compact-format result (e.g. `"20260320000000"`), the GnuCash DB uses compact format — update the assertion to match actual output and add a comment explaining it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_gnucash_db_utils.py
git commit -m "test: add pure utility tests for generate_guid and format functions (9 tests)"
```

---

## Task 5: Create `tests/test_account_queries.py` (15 DB query tests)

**Files:**
- Create: `tests/test_account_queries.py`

All classes use the `db_connection` fixture. Cross-check assertions use direct `sqlite3` queries against the same test DB to verify account types.

- [ ] **Step 1: Create `tests/test_account_queries.py`**

```python
"""Tests for account query functions in gnucash_db.py.

All classes use the db_connection fixture (class-scoped, copies real GnuCash DB).
Cross-check assertions use direct sqlite3 queries to verify return shapes and types.
"""
import sqlite3

import pytest

from bill_processor.gnucash_db import (
    get_checking_accounts,
    get_expense_accounts,
    get_asset_accounts,
    get_all_accounts,
    get_cash_accounts,
)


class TestGetCheckingAccounts:
    def test_returns_list(self, db_connection):
        result = get_checking_accounts()
        assert isinstance(result, list)

    def test_items_have_required_keys(self, db_connection):
        result = get_checking_accounts()
        if not result:
            pytest.skip("No checking accounts in test DB")
        for item in result:
            assert "guid" in item
            assert "name" in item
            assert "description" in item

    def test_all_bank_type(self, db_connection):
        result = get_checking_accounts()
        if not result:
            pytest.skip("No checking accounts in test DB")
        guids = [a["guid"] for a in result]
        conn = sqlite3.connect(str(db_connection))
        rows = conn.execute(
            f"SELECT account_type FROM accounts WHERE guid IN ({','.join('?'*len(guids))})",
            guids,
        ).fetchall()
        conn.close()
        assert all(r[0] == "BANK" for r in rows)


class TestGetExpenseAccounts:
    def test_returns_list(self, db_connection):
        result = get_expense_accounts()
        assert isinstance(result, list)

    def test_items_have_required_keys(self, db_connection):
        result = get_expense_accounts()
        if not result:
            pytest.skip("No expense accounts in test DB")
        for item in result:
            assert "guid" in item
            assert "name" in item
            assert "description" in item

    def test_all_expense_type(self, db_connection):
        result = get_expense_accounts()
        if not result:
            pytest.skip("No expense accounts in test DB")
        guids = [a["guid"] for a in result]
        conn = sqlite3.connect(str(db_connection))
        rows = conn.execute(
            f"SELECT account_type FROM accounts WHERE guid IN ({','.join('?'*len(guids))})",
            guids,
        ).fetchall()
        conn.close()
        assert all(r[0] == "EXPENSE" for r in rows)


class TestGetAssetAccounts:
    def test_returns_list(self, db_connection):
        result = get_asset_accounts()
        assert isinstance(result, list)

    def test_items_have_required_keys(self, db_connection):
        result = get_asset_accounts()
        if not result:
            pytest.skip("No asset accounts in test DB")
        for item in result:
            assert "guid" in item
            assert "name" in item
            assert "description" in item

    def test_all_asset_type(self, db_connection):
        result = get_asset_accounts()
        if not result:
            pytest.skip("No asset accounts in test DB")
        guids = [a["guid"] for a in result]
        conn = sqlite3.connect(str(db_connection))
        rows = conn.execute(
            f"SELECT account_type FROM accounts WHERE guid IN ({','.join('?'*len(guids))})",
            guids,
        ).fetchall()
        conn.close()
        assert all(r[0] == "ASSET" for r in rows)


class TestGetAllAccounts:
    def test_returns_list(self, db_connection):
        result = get_all_accounts()
        assert isinstance(result, list)

    def test_items_have_required_keys(self, db_connection):
        result = get_all_accounts()
        if not result:
            pytest.skip("No accounts in test DB")
        for item in result:
            assert "guid" in item
            assert "name" in item
            assert "description" in item
            assert "account_type" in item

    def test_excludes_placeholders(self, db_connection):
        result = get_all_accounts()
        if not result:
            pytest.skip("No accounts in test DB")
        guids = [a["guid"] for a in result]
        conn = sqlite3.connect(str(db_connection))
        rows = conn.execute(
            f"SELECT placeholder FROM accounts WHERE guid IN ({','.join('?'*len(guids))})",
            guids,
        ).fetchall()
        conn.close()
        assert all(r[0] != 1 for r in rows)


class TestGetCashAccounts:
    def test_returns_list(self, db_connection):
        result = get_cash_accounts()
        assert isinstance(result, list)

    def test_items_have_required_keys(self, db_connection):
        result = get_cash_accounts()
        if not result:
            pytest.skip("No cash accounts in test DB")
        for item in result:
            assert "guid" in item
            assert "name" in item

    def test_all_income_or_asset_type(self, db_connection):
        result = get_cash_accounts()
        if not result:
            pytest.skip("No cash accounts in test DB")
        guids = [a["guid"] for a in result]
        conn = sqlite3.connect(str(db_connection))
        rows = conn.execute(
            f"SELECT account_type FROM accounts WHERE guid IN ({','.join('?'*len(guids))})",
            guids,
        ).fetchall()
        conn.close()
        assert all(r[0] in ("INCOME", "ASSET") for r in rows)
```

- [ ] **Step 2: Run the new file**

Run: `uv run pytest tests/test_account_queries.py -v`
Expected: 15 tests pass (or skip if the test DB happens to have no accounts of that type). No failures.

- [ ] **Step 3: Commit**

```bash
git add tests/test_account_queries.py
git commit -m "test: add account query tests — checking, expense, asset, all, cash (15 tests)"
```

---

## Task 6: Create `tests/test_vendor_bill_queries.py` (19 DB query tests)

**Files:**
- Create: `tests/test_vendor_bill_queries.py`

Uses `db_connection` fixture and helpers from `tests/helpers.py`. Each test class that inserts rows uses a function-scoped `autouse` fixture (`_setup`) to insert unique rows per test method (UUIDs prevent collisions). `get_bills_by_status` requires INNER JOIN on vendors — always insert vendor before invoice.

**Fixture scope note:** The `_setup` autouse fixtures are function-scoped (default). They request `db_connection` (class-scoped). This is valid in pytest — a fixture may only request fixtures of **equal or higher** scope (class > function), not lower scope. The class-scoped `db_connection` is shared across all `_setup` invocations within a class, which is the desired behavior.

- [ ] **Step 1: Create `tests/test_vendor_bill_queries.py`**

```python
"""Tests for vendor and bill query functions in gnucash_db.py.

All classes use the db_connection fixture (class-scoped, copies real GnuCash DB).
Shared helpers from tests/helpers.py insert vendor and invoice rows directly via sqlite3.
"""
import sqlite3
import uuid

import pytest

from helpers import _insert_test_vendor, _insert_test_invoice
from bill_processor.gnucash_db import (
    get_all_vendors,
    find_vendor_by_name,
    find_vendor_by_id,
    find_vendor_by_guid,
    get_invoice_by_guid,
    get_bills_by_status,
    get_bill_total,
)


class TestGetAllVendors:
    @pytest.fixture(autouse=True)
    def _setup(self, db_connection):
        self.db_path = db_connection
        self.vendor_guid = _insert_test_vendor(
            db_connection, name=f"AllVendorsTest{uuid.uuid4().hex[:8]}"
        )

    def test_returns_list(self, db_connection):
        result = get_all_vendors()
        assert isinstance(result, list)

    def test_items_have_required_keys(self, db_connection):
        result = get_all_vendors()
        assert len(result) > 0
        for item in result:
            assert "guid" in item
            assert "id" in item
            assert "name" in item

    def test_inserted_vendor_present(self, db_connection):
        result = get_all_vendors()
        guids = [v["guid"] for v in result]
        assert self.vendor_guid in guids


class TestFindVendorByName:
    @pytest.fixture(autouse=True)
    def _setup(self, db_connection):
        self.db_path = db_connection
        self.vendor_name = "FindByNameVendor2026"
        self.vendor_guid = _insert_test_vendor(db_connection, name=self.vendor_name)

    def test_exact_match_found(self, db_connection):
        result = find_vendor_by_name(self.vendor_name)
        assert result is not None
        assert result["name"] == self.vendor_name

    def test_returns_guid(self, db_connection):
        result = find_vendor_by_name(self.vendor_name)
        assert result is not None
        assert result["guid"] == self.vendor_guid

    def test_not_found_returns_none(self, db_connection):
        assert find_vendor_by_name("VendorNeverExists99999") is None


class TestFindVendorById:
    @pytest.fixture(autouse=True)
    def _setup(self, db_connection):
        self.db_path = db_connection
        self.vendor_id = "TESTID2026"
        self.vendor_guid = _insert_test_vendor(
            db_connection,
            name=f"FindByIdVendor{uuid.uuid4().hex[:8]}",
            vendor_id=self.vendor_id,
        )

    def test_found_by_id(self, db_connection):
        result = find_vendor_by_id(self.vendor_id)
        assert result is not None
        assert result["id"] == self.vendor_id

    def test_not_found_returns_none(self, db_connection):
        assert find_vendor_by_id("NEVEREXISTS99999") is None


class TestFindVendorByGuid:
    @pytest.fixture(autouse=True)
    def _setup(self, db_connection):
        self.db_path = db_connection
        self.vendor_guid = _insert_test_vendor(
            db_connection, name=f"FindByGuidVendor{uuid.uuid4().hex[:8]}"
        )

    def test_found_by_guid(self, db_connection):
        result = find_vendor_by_guid(self.vendor_guid)
        assert result is not None
        assert result["guid"] == self.vendor_guid

    def test_not_found_returns_none(self, db_connection):
        assert find_vendor_by_guid("deadbeef" + "0" * 24) is None


class TestGetInvoiceByGuid:
    @pytest.fixture(autouse=True)
    def _setup(self, db_connection):
        self.db_path = db_connection
        vendor_guid = _insert_test_vendor(
            db_connection, name=f"InvoiceQueryVendor{uuid.uuid4().hex[:8]}"
        )
        self.invoice_guid = _insert_test_invoice(db_connection, vendor_guid=vendor_guid)

    def test_found_returns_dict(self, db_connection):
        result = get_invoice_by_guid(self.invoice_guid)
        assert result is not None

    def test_includes_vendor_name(self, db_connection):
        result = get_invoice_by_guid(self.invoice_guid)
        assert result is not None
        assert isinstance(result["vendor_name"], str)

    def test_not_found_returns_none(self, db_connection):
        assert get_invoice_by_guid("deadbeef" + "0" * 24) is None


class TestGetBillsByStatus:
    # get_bills_by_status uses INNER JOIN vendors — vendor row must exist first.
    @pytest.fixture(autouse=True)
    def _setup(self, db_connection):
        self.db_path = db_connection
        vendor_guid = _insert_test_vendor(
            db_connection, name=f"BillStatusVendor{uuid.uuid4().hex[:8]}"
        )
        self.invoice_guid = _insert_test_invoice(
            db_connection, vendor_guid=vendor_guid, posted=False
        )

    def test_unposted_bill_appears(self, db_connection):
        result = get_bills_by_status("unposted")
        assert self.invoice_guid in [b["guid"] for b in result]

    def test_unposted_items_have_required_keys(self, db_connection):
        result = get_bills_by_status("unposted")
        # Find our inserted row (other rows may exist in the test DB)
        our_bills = [b for b in result if b["guid"] == self.invoice_guid]
        assert len(our_bills) == 1
        bill = our_bills[0]
        assert "guid" in bill
        assert "id" in bill
        assert "vendor_name" in bill

    def test_all_includes_unposted(self, db_connection):
        result = get_bills_by_status("all")
        assert self.invoice_guid in [b["guid"] for b in result]

    def test_posted_unpaid_excludes_unposted(self, db_connection):
        result = get_bills_by_status("posted_unpaid")
        assert self.invoice_guid not in [b["guid"] for b in result]


class TestGetBillTotal:
    @pytest.fixture(autouse=True)
    def _setup(self, db_connection):
        self.db_path = db_connection
        vendor_guid = _insert_test_vendor(
            db_connection, name=f"BillTotalVendor{uuid.uuid4().hex[:8]}"
        )
        self.invoice_guid = _insert_test_invoice(db_connection, vendor_guid=vendor_guid)

    def test_unknown_guid_returns_zero(self, db_connection):
        assert get_bill_total("deadbeef" + "0" * 24) == 0.0

    def test_bill_with_no_entries_returns_zero(self, db_connection):
        # Invoice inserted with no entries — sum of zero rows = 0.0
        assert get_bill_total(self.invoice_guid) == 0.0
```

- [ ] **Step 2: Run the new file**

Run: `uv run pytest tests/test_vendor_bill_queries.py -v`
Expected: 19 tests pass. If any fail due to missing functions in `gnucash_db.py`, confirm the import names match exactly (e.g. `find_vendor_by_id` not `find_vendor_by_vendor_id`).

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest tests/ -q`
Expected: All tests pass. Count should be prior passing count + 43 (9 + 15 + 19).

- [ ] **Step 4: Commit**

```bash
git add tests/test_vendor_bill_queries.py
git commit -m "test: add vendor and bill query tests (19 tests)"
```

---

## Final Verification

Run: `uv run pytest tests/ -q`

Expected: All tests pass (prior 313 tests + 43 new = 356 total). No failures. No import errors.

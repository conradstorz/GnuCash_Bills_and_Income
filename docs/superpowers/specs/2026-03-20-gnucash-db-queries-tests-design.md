# gnucash_db Query & Utility Tests Design

## Goal

Add 43 tests across three new files to bring `gnucash_db.py` coverage from ~28% toward ~50%,
covering pure utility functions, account query functions, and vendor/bill query functions.

## Architecture

Three files, each independently runnable. No mocks — all DB-dependent tests use the
`db_connection` fixture (real GnuCash DB copy, class-scoped, in `tests/conftest.py`).
`_insert_test_vendor` moves from `test_vendor_sync.py` to `tests/helpers.py` so both
files share it. A new `_insert_test_invoice` helper is added to `helpers.py` for bill
query setup.

## Test Files

### `tests/test_gnucash_db_utils.py`

Pure unit tests — no DB, no fixtures. Tests the ISO-fallback behavior (schema unavailable
without a real DB connection, so format functions fall back to ISO format).

**Imports:** `datetime`, `re`, `pytest`, and from `bill_processor.gnucash_db`:
`generate_guid`, `format_gnucash_date`, `format_gnucash_timestamp`

**Import convention:** Use `from bill_processor.gnucash_db import ...` throughout all three
test files. This matches existing test files (e.g., `test_lock_management.py`,
`test_bill_workflow.py`) and works because the package-dir mapping in `pyproject.toml`
exposes `gnucash_db.py` as `bill_processor.gnucash_db`.

---

#### `TestGenerateGuid` (3 tests)

| Test | Assertion |
|---|---|
| `test_returns_string` | `isinstance(generate_guid(), str)` |
| `test_returns_32_hex_chars` | `len == 32` and all chars in `0-9a-f` |
| `test_unique_each_call` | Two successive calls return different values |

---

#### `TestFormatGnucashDate` (4 tests)

`format_gnucash_date(dt, include_time=True)` falls back to ISO format without a DB.

| Test | Input | Expected |
|---|---|---|
| `test_date_returns_iso_string` | `date(2026, 3, 20)` | `"2026-03-20 00:00:00"` |
| `test_include_time_false_returns_date_only` | `date(2026, 3, 20), include_time=False` | `"2026-03-20"` |
| `test_datetime_preserves_time` | `datetime(2026, 3, 20, 14, 30, 0)` | `"2026-03-20 14:30:00"` |
| `test_return_type_is_string` | any date | `isinstance(result, str)` |

---

#### `TestFormatGnucashTimestamp` (2 tests)

| Test | Assertion |
|---|---|
| `test_returns_string` | `isinstance(format_gnucash_timestamp(), str)` |
| `test_matches_datetime_pattern` | `re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", result)` |

---

### `tests/test_account_queries.py`

All classes use `db_connection` fixture. The real test DB always has accounts (conftest
already skips tests that require accounts if none are found).

**Imports:** `sqlite3`, `pytest`, and from `bill_processor.gnucash_db`:
`get_checking_accounts`, `get_expense_accounts`, `get_asset_accounts`,
`get_all_accounts`, `get_cash_accounts`

Return shapes:
- `get_checking/expense/asset_accounts` → `[{"guid": ..., "name": ..., "description": ...}]`
- `get_all_accounts` → `[{"guid": ..., "name": ..., "description": ..., "account_type": ...}]`
- `get_cash_accounts` → `[{"guid": ..., "name": ...}]`

---

#### `TestGetCheckingAccounts` (3 tests)

| Test | Assertion |
|---|---|
| `test_returns_list` | `isinstance(result, list)` |
| `test_items_have_required_keys` | all items have `guid`, `name`, `description` |
| `test_all_bank_type` | cross-check all returned GUIDs have `account_type = 'BANK'` via direct sqlite3 query |

---

#### `TestGetExpenseAccounts` (3 tests)

Same pattern as `TestGetCheckingAccounts` but for `EXPENSE` type.

| Test | Assertion |
|---|---|
| `test_returns_list` | `isinstance(result, list)` |
| `test_items_have_required_keys` | all items have `guid`, `name`, `description` |
| `test_all_expense_type` | cross-check GUIDs → `account_type = 'EXPENSE'` |

---

#### `TestGetAssetAccounts` (3 tests)

Same pattern for `ASSET` type.

| Test | Assertion |
|---|---|
| `test_returns_list` | `isinstance(result, list)` |
| `test_items_have_required_keys` | all items have `guid`, `name`, `description` |
| `test_all_asset_type` | cross-check GUIDs → `account_type = 'ASSET'` |

---

#### `TestGetAllAccounts` (3 tests)

| Test | Assertion |
|---|---|
| `test_returns_list` | `isinstance(result, list)` |
| `test_items_have_required_keys` | all items have `guid`, `name`, `description`, `account_type` |
| `test_excludes_placeholders` | cross-check: no returned GUID has `placeholder = 1` in DB |

---

#### `TestGetCashAccounts` (3 tests)

| Test | Assertion |
|---|---|
| `test_returns_list` | `isinstance(result, list)` |
| `test_items_have_required_keys` | all items have `guid`, `name` |
| `test_all_income_or_asset_type` | cross-check all returned GUIDs have `account_type IN ('INCOME', 'ASSET')` |

---

### `tests/test_vendor_bill_queries.py`

Uses `db_connection` fixture and the shared helpers from `tests/helpers.py`.

**Imports:** `sqlite3`, `uuid`, `pytest`, `_insert_test_vendor` and `_insert_test_invoice`
from `tests/helpers.py`, and from `bill_processor.gnucash_db`:
`get_all_vendors`, `find_vendor_by_name`, `find_vendor_by_id`, `find_vendor_by_guid`,
`get_invoice_by_guid`, `get_bills_by_status`, `get_bill_total`

---

#### `TestGetAllVendors` (3 tests)

| Test | Setup | Assertion |
|---|---|---|
| `test_returns_list` | `_insert_test_vendor` | `isinstance(result, list)` |
| `test_items_have_required_keys` | `_insert_test_vendor` | all items have `guid`, `id`, `name` |
| `test_inserted_vendor_present` | insert with known GUID | GUID found in `[v["guid"] for v in result]` |

---

#### `TestFindVendorByName` (3 tests)

| Test | Setup | Assertion |
|---|---|---|
| `test_exact_match_found` | insert `"FindByNameVendor2026"` | result is not None, `result["name"] == "FindByNameVendor2026"` |
| `test_returns_guid` | same insert | `result["guid"] == inserted_guid` |
| `test_not_found_returns_none` | no insert | `find_vendor_by_name("VendorNeverExists99999") is None` |

---

#### `TestFindVendorById` (2 tests)

| Test | Setup | Assertion |
|---|---|---|
| `test_found_by_id` | insert with `vendor_id="TESTID2026"` | result not None, `result["id"] == "TESTID2026"` |
| `test_not_found_returns_none` | no insert | `find_vendor_by_id("NEVEREXISTS99999") is None` |

---

#### `TestFindVendorByGuid` (2 tests)

| Test | Setup | Assertion |
|---|---|---|
| `test_found_by_guid` | insert with known guid | result not None, `result["guid"] == inserted_guid` |
| `test_not_found_returns_none` | no insert | `find_vendor_by_guid("deadbeef" + "0" * 24) is None` |

---

#### `TestGetInvoiceByGuid` (3 tests)

| Test | Setup | Assertion |
|---|---|---|
| `test_found_returns_dict` | insert vendor + invoice | result not None |
| `test_includes_vendor_name` | same | `result["vendor_name"]` is a string |
| `test_not_found_returns_none` | no insert | `get_invoice_by_guid("deadbeef" + "0" * 24) is None` |

---

#### `TestGetBillsByStatus` (4 tests)

`get_bills_by_status` uses an INNER JOIN on the vendors table, so a matching vendor row
must exist before inserting the invoice. Use a class-level `setup_method` that inserts
vendor + invoice once per test method (each call creates fresh rows with unique GUIDs,
so accumulation across methods is harmless since assertions are GUID-targeted):

```python
def setup_method(self):
    self.vendor_guid = _insert_test_vendor(db_path)
    self.invoice_guid = _insert_test_invoice(db_path, vendor_guid=self.vendor_guid, posted=False)
```

| Test | Setup | Assertion |
|---|---|---|
| `test_unposted_bill_appears` | `setup_method` inserts vendor + unposted invoice | inserted GUID in `[b["guid"] for b in get_bills_by_status("unposted")]` |
| `test_unposted_items_have_required_keys` | same | items have `guid`, `id`, `vendor_name` |
| `test_all_includes_unposted` | same | inserted GUID in `get_bills_by_status("all")` |
| `test_posted_unpaid_excludes_unposted` | same | inserted GUID NOT in `get_bills_by_status("posted_unpaid")` |

---

#### `TestGetBillTotal` (2 tests)

| Test | Setup | Assertion |
|---|---|---|
| `test_unknown_guid_returns_zero` | no insert | `get_bill_total("deadbeef" + "0" * 24) == 0.0` |
| `test_bill_with_no_entries_returns_zero` | insert invoice only (no entries) | `get_bill_total(invoice_guid) == 0.0` |

---

## Shared Helpers (`tests/helpers.py`)

### `_insert_test_vendor` — move from `test_vendor_sync.py`

Move the existing function verbatim from `test_vendor_sync.py` (where it is currently
defined locally, not via importlib). Update `test_vendor_sync.py` to import from
`tests/helpers.py` instead:

```python
from helpers import _insert_test_vendor
```

Note: `tests/helpers.py` already exists and contains `_insert_lock` (loaded by
`conftest.py` via `importlib.util`). `conftest.py` does not need changes — it only uses
`_insert_lock`. This task adds `_insert_test_vendor` and `_insert_test_invoice` to
`helpers.py`, growing it from 1 function to 3. Only `test_vendor_sync.py` needs updating
(replace the local function definition with the import above).

**Recommended:** add `"tests"` to `pythonpath` in `pyproject.toml` so helpers can be
imported directly without `importlib.util` boilerplate. New files (`test_vendor_bill_queries.py`)
use `from helpers import ...` directly.

### `_insert_test_invoice` — new helper

```python
def _insert_test_invoice(db_path, vendor_guid, posted=False, invoice_id=None, guid=None):
    """Insert a minimal invoice (bill) row into the invoices table.

    Uses PRAGMA table_info to discover available columns. Returns inserted GUID.
    posted=False → unposted (post_lot left NULL); posted=True → set post_lot to a non-NULL
    placeholder value to simulate a posted bill (the invoices table has no is_posted column;
    posted/unposted state is determined entirely by whether post_lot is NULL).
    """
```

Inserts into `invoices` table with:
- `guid`, `id`, `date_opened` (`"2026-03-20 00:00:00"`), `owner_type=4` (vendor),
  `owner_guid=vendor_guid`, `currency` (USD GUID from commodities),
  `post_lot=None` (when `posted=False`); `post_lot="placeholder"` when `posted=True`
- **No `is_posted` column** — the invoices table does not have this column; posted state
  is controlled exclusively by `post_lot` being NULL or non-NULL
- Uses `PRAGMA table_info(invoices)` for schema compatibility
- Returns the inserted GUID

**Currency lookup** (mirrors `_insert_test_vendor`):
```python
cur = conn.execute(
    "SELECT guid FROM commodities WHERE mnemonic='USD' AND namespace='CURRENCY' LIMIT 1"
).fetchone()
currency_guid = cur[0] if cur else "a" * 32
```

**`post_lot="placeholder"` behavior note:** When `posted=True`, the helper sets
`post_lot` to a non-NULL string that does not match any real row in the `lots` table.
`get_bills_by_status("posted_unpaid")` does `LEFT JOIN lots ON i.post_lot = l.guid` and
checks `l.is_closed = 0 OR l.is_closed IS NULL`. Because the GUID is fake, the LEFT JOIN
returns NULL for all lot columns, satisfying `l.is_closed IS NULL` — so such an invoice
**will appear** in `posted_unpaid` results. This is intentional for test purposes: it
avoids inserting a real lots row while still producing a detectable posted invoice. The
current test suite does not include a `test_posted_bill_appears_in_posted_unpaid` test, so
this side-effect does not cause false positives in the specified tests.

---

## pyproject.toml change

Add `"tests"` to `pythonpath` so `from helpers import _insert_test_vendor` works:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = [".", "tests"]
```

---

## Test Count Summary

| File | Tests |
|---|---|
| `test_gnucash_db_utils.py` | 9 |
| `test_account_queries.py` | 15 |
| `test_vendor_bill_queries.py` | 19 |
| **Total** | **43** |

---

## Verification

```bash
uv run pytest tests/test_gnucash_db_utils.py -v
uv run pytest tests/test_account_queries.py -v
uv run pytest tests/test_vendor_bill_queries.py -v
uv run pytest tests/ -q
```

All 43 new tests should pass. Full suite should remain green (313 + 43 = 356 passing).

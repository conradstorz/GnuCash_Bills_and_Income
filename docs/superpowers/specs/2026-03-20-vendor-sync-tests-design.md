# Vendor Sync Tests — Design Spec
**Date:** 2026-03-20
**Scope:** Add comprehensive tests for `vendor_sync.py` — all four layers from pure in-memory logic through full SchemaDiscovery integration.

---

## Background

`vendor_sync.py` is a bidirectional sync utility between `data/vendor_database.json` and the GnuCash SQLite `vendors` table. It is currently 828 lines with zero test coverage. Silent failures here can corrupt vendor data in either direction.

Key structural note: `sync_gnucash_to_json` and `sync_bidirectional` are defined as module-level functions that take `self`, then monkey-patched onto `VendorSyncUtility` at module load time (lines 741–742). Tests call them as normal instance methods.

Latent bug (not fixed — tests monkey-patch instead): `__init__` uses `Path(__file__).parent.parent / "data"` with a comment "Go up from src/ to project root", but the file lives at the project root, making the path resolve one level too high. Tests override `sync_util.vendor_db_path` after construction.

---

## Approach

- **Real SQLite** for all DB-touching tests — `db_connection` fixture (existing, `scope="class"`) copies the real GnuCash DB to `tmp_path` and patches `bill_processor.config.GNUCASH_DB_PATH` via direct attribute mutation on `gnucash_db.config`. Since `gnucash_db.config` and the `config` module imported by `vendor_sync.py` (`from bill_processor import config`) are the same module object in memory, `discover_schema()` sees the patched path automatically. No additional patching is needed in the tests.
- **Real SchemaDiscovery** — no mocking of `SchemaDiscovery`. The real DB copy has a genuine `vendors` table schema, so `discover_schema()` runs against it directly.
- **No mocks** anywhere — not for `generate_guid()`, `get_usd_guid()`, file I/O, or any DB operation.
- **Monkey-patch `vendor_db_path`** after construction in all tests that touch the JSON file.

---

## Files Changed

| File | Action |
|---|---|
| `tests/test_vendor_sync.py` | **Create** — ~40 tests across 12 classes |
| `tests/conftest.py` | **No changes** — all fixtures live in the test file |

---

## Fixtures (all in `test_vendor_sync.py`)

```python
@pytest.fixture
def vendor_json(tmp_path):
    """Write a minimal vendor_database.json to tmp_path and return the path."""
    db = tmp_path / "vendor_database.json"
    db.write_text(json.dumps({
        "vendors": {
            "acme": {"display_name": "Acme Corp", "gnucash_guid": "abc123"}
        },
        "aliases": {}
    }))
    return db

@pytest.fixture
def sync_util(tmp_path):
    """VendorSyncUtility with vendor_db_path monkey-patched to tmp_path.
    Function-scoped: each test gets a fresh instance with zeroed stats."""
    util = VendorSyncUtility()
    util.vendor_db_path = tmp_path / "vendor_database.json"
    return util

@pytest.fixture
def sync_util_with_schema(sync_util, db_connection):
    """sync_util with discover_schema() already called against the real test DB.

    MUST remain function-scoped (inherits from sync_util). Every test in
    TestCreateVendorInGnucash, TestSyncAllVendors, TestSyncGnucashToJson, and
    TestSyncBidirectional gets a fresh VendorSyncUtility with zeroed stats and a
    fresh vendor_db_path in tmp_path. The shared DB copy (class-scoped via
    db_connection) accumulates rows across tests in the same class — assertions
    must query by specific GUIDs, not by table row count.

    discover_schema() is called once per test (not once per class) due to
    function scope. This is acceptable given the real DB copy is pre-loaded.
    """
    result = sync_util.discover_schema()
    assert result, "discover_schema() failed — test DB may be missing vendors table"
    return sync_util
```

---

## Test Classes

### Layer 1 — Pure In-Memory (`TestValidateAndCleanupDuplicates`)

Set `sync_util.vendors_data` directly; no DB or file I/O.

| Test | Setup | Expected |
|---|---|---|
| `test_no_duplicates` | 3 vendors, all distinct GUIDs | `duplicates_found=0`, `duplicates_removed=0` |
| `test_single_duplicate_group` | 3 vendors share 1 GUID (keys: "a", "b", "c") | `"a"` kept, `"b"` and `"c"` removed from `vendors_data`; `duplicates_removed=2` |
| `test_multiple_duplicate_groups` | 2 separate GUID groups (2 vendors each) | each group cleaned; 2 total removed; `duplicates_removed=2` |
| `test_auto_fix_false_reports_only` | 2 vendors share GUID, `auto_fix=False` | `duplicates_found=1`, both keys still present in `vendors_data` |
| `test_vendor_without_guid_skipped` | vendor with no `gnucash_guid` key | not compared; no false positive |

### Layer 1 — Pure In-Memory (`TestResetVendorToUnsynced`)

| Test | Setup | Expected |
|---|---|---|
| `test_removes_sync_fields` | vendor with `gnucash_guid`, `gnucash_id`, `expense_account_guid` | all three fields removed, returns `True` |
| `test_preserves_other_fields` | vendor with `display_name`, `addr_line1` plus sync fields | `display_name` and `addr_line1` untouched after reset |
| `test_unknown_key_returns_false` | key not in `vendors_data` | returns `False` |
| `test_fields_already_absent_is_ok` | vendor with no sync fields | returns `True`, no KeyError |

### Layer 1 — Pure In-Memory (`TestUpdateVendorIds`)

| Test | Setup | Expected |
|---|---|---|
| `test_updates_guid_and_id` | vendor in `vendors_data`, call with `gnucash_data={'guid': 'g1', 'id': '000007'}` | `vendors_data[key]['gnucash_guid'] == 'g1'` and `['gnucash_id'] == '000007'`, returns `True` |
| `test_increments_stats` | call `update_vendor_ids` once | `stats['updated']` = 1 |
| `test_missing_key_returns_false` | key not in `vendors_data` | returns `False` |

### Layer 2 — File I/O (`TestLoadVendorDatabase`)

`sync_util` fixture (function-scoped). Each test writes its own JSON to `sync_util.vendor_db_path`.

| Test | Setup | Expected |
|---|---|---|
| `test_file_missing_returns_false` | don't write the file | returns `False` |
| `test_empty_vendors_returns_false` | write `{"vendors": {}, "aliases": {}}` | returns `False` |
| `test_loads_vendors_correctly` | write 2-vendor JSON | `vendors_data` has 2 keys; `stats['total']` = 2 |
| `test_auto_cleans_duplicates_on_load` | write 3 vendors where "b" and "c" share `gnucash_guid="dup"`, "a" has a distinct guid | returns `True`; `vendors_data` has exactly 2 keys (`"a"` + whichever of `"b"`/`"c"` is first); reading the file from disk shows only 2 vendor entries |
| `test_malformed_json_returns_false` | write literal string `{not valid json` | returns `False` |

### Layer 2 — File I/O (`TestSaveVendorDatabase`)

| Test | Setup | Expected |
|---|---|---|
| `test_saves_vendors_and_preserves_aliases` | write file with `aliases: {"foo": "bar"}`; set `vendors_data = {"v1": {"display_name": "V1"}}`; call `save_vendor_database()` | loaded saved file has `vendors["v1"]` and `aliases["foo"] == "bar"` |
| `test_creates_aliases_key_if_file_new` | `vendor_db_path` does not exist; set `vendors_data`; call `save_vendor_database()` | saved file parses to `{"vendors": {...}, "aliases": {}}` |
| `test_write_error_returns_false` | set `vendor_db_path` to a path inside a nonexistent directory | returns `False` |

### Layer 3 — DB Queries (`TestVendorExistsInGnucash`)

`db_connection` fixture. Insert a vendor row directly into the test DB before calling.

| Test | Setup | Expected |
|---|---|---|
| `test_existing_vendor_found` | insert vendor with `name="__TestCorp__"` | returns dict with keys `guid`, `id`, `name`; `name == "__TestCorp__"` |
| `test_nonexistent_vendor_returns_none` | query for name `"__NeverExists__"` | returns `None` |

### Layer 3 — DB Queries (`TestGetNextVendorId`)

`db_connection` fixture.

**Note:** The real test DB already has vendors with unknown max IDs. Insert a vendor with an extreme ID (`"999990"`) to guarantee it is the maximum, then assert the return value is `"999991"`.

| Test | Setup | Expected |
|---|---|---|
| `test_returns_max_plus_one` | insert vendor with `id="999990"` | returns `"999991"` |

### Layer 3 — DB Queries (`TestGetAllGnucashVendors`)

Module-level function `get_all_gnucash_vendors()`. Uses `db_connection`.

| Test | Setup | Expected |
|---|---|---|
| `test_returns_vendors_list` | test DB has at least one vendor | returns non-empty list of dicts; each dict has `guid` and `name` keys |
| `test_address_fields_present` | any vendor in DB | every dict has keys `addr_name`, `addr_addr1`, `addr_addr2`, `addr_addr3`, `addr_addr4`, `addr_phone`, `addr_fax`, `addr_email` (value may be empty string, not `None`) |

### Layer 3 — DB Queries (`TestValidateVendorReferences`)

`sync_util` + `db_connection`. Write JSON file to `sync_util.vendor_db_path` before each test (`validate_vendor_references()` calls `load_vendor_database()` internally).

| Test | Setup | Expected |
|---|---|---|
| `test_valid_reference` | look up a real vendor GUID from the test DB; write JSON with that GUID | vendor key in `result['valid']`; not in `result['invalid']` |
| `test_invalid_reference_auto_fix` | write JSON vendor with `gnucash_guid="deadbeef00000000"` (not in DB); `auto_fix=True` | in `result['invalid']` and `result['fixed']`; `gnucash_guid` key absent from `vendors_data` entry; JSON file on disk reflects removal |
| `test_invalid_reference_no_auto_fix` | same missing GUID; `auto_fix=False` | in `result['invalid']` only; `vendors_data` entry still has `gnucash_guid` |
| `test_stale_expense_account_guid_cleaned` | valid vendor GUID present in DB, but vendor also has `expense_account_guid="deadacct00000000"` not in `accounts` table; `auto_fix=True` | `expense_account_guid` removed from `vendors_data`; vendor key in `result['fixed']`; vendor key also in `result['valid']` (the vendor itself is valid) |
| `test_unsynced_vendor_skipped` | write JSON vendor with no `gnucash_guid` key | not in `result['valid']`, `result['invalid']`, or `result['fixed']` |

### Layer 4 — Full Stack (`TestBuildVendorInsert`)

`sync_util_with_schema`. Direct test of the schema-to-SQL bridge.

| Test | Setup | Expected |
|---|---|---|
| `test_returns_valid_sql_and_columns` | call `sync_util.build_vendor_insert()` | returns tuple `(sql, columns)` where `sql` is a string starting with `"INSERT INTO vendors"` and `columns` is a non-empty list containing at least `"guid"`, `"name"`, `"id"` |

### Layer 4 — Full Stack (`TestCreateVendorInGnucash`)

`sync_util_with_schema` fixture. Tests share the class-scoped DB copy — query by the specific GUID set on `vendor_data`, not by table row count.

| Test | Setup | Expected |
|---|---|---|
| `test_vendor_row_inserted` | call with `vendor_key="test_v"` and `vendor_data={"display_name": "Test Vendor"}` | `SELECT guid FROM vendors WHERE guid = vendor_data['gnucash_guid']` returns a row |
| `test_address_fields_saved` | `vendor_data` includes `addr_name="Test Vendor"`, `addr_line1="123 Main St"`, `phone="555-1234"` | DB row for that GUID has `addr_name="Test Vendor"`, `addr_addr1="123 Main St"`, `addr_phone="555-1234"` |
| `test_vendor_data_updated_with_guid` | call returns `True` | `vendor_data['gnucash_guid']` is a non-empty string; `vendor_data['gnucash_id']` is a non-empty string |
| `test_stats_created_incremented` | fresh `sync_util_with_schema` (function-scoped, stats start at 0); call once | `stats['created']` = 1 |

### Layer 4 — Full Stack (`TestSyncAllVendors`)

`sync_util_with_schema`. Write vendor JSON to `sync_util.vendor_db_path` before each test.

| Test | Setup | Expected |
|---|---|---|
| `test_dry_run_no_insertions` | write JSON with 1 vendor (`display_name="__DryRun__"`); call `sync_all_vendors(dry_run=True)` | returns `True`; `SELECT COUNT(*) FROM vendors WHERE name="__DryRun__"` = 0 |
| `test_creates_missing_vendor` | write JSON with 1 vendor not present in DB | row appears in DB after call; `stats['created']` = 1 |
| `test_skips_existing_vendor` | insert a vendor named `"__SkipMe__"` into DB; write JSON with same `display_name` and a `gnucash_guid` already set | `stats['skipped']` = 1; only 1 row with that name in DB |
| `test_updates_json_ids_for_existing_vendor` | insert vendor `"__UpdateMe__"` into DB; write JSON with same `display_name` but no `gnucash_guid` key | after call, `sync_util.vendors_data` entry has `gnucash_guid` set to the DB row's GUID |

### Layer 4 — Full Stack (`TestSyncGnucashToJson`)

`sync_util_with_schema`. Insert vendor rows into DB directly; call `sync_util.sync_gnucash_to_json()`.

| Test | Setup | Expected |
|---|---|---|
| `test_imports_new_vendor` | insert vendor `"NewFromGC2026"` into DB; `vendor_db_path` does not exist (no JSON file) | `load_vendor_database()` fails gracefully (vendors_data reset to {}); after sync, JSON file written with an entry whose `gnucash_guid` matches the inserted row's GUID |
| `test_updates_existing_by_guid` | insert vendor `"GCUpdatedName2026"` into DB with GUID `"gcguid001"`; write JSON with key `"old_key"` and `gnucash_guid="gcguid001"` but `display_name="OldName"` | after sync, `vendors_data["old_key"]["display_name"] == "GCUpdatedName2026"` (name overwritten from DB) |
| `test_preserves_expense_account_on_update` | JSON vendor has `expense_account="Utilities"` and `expense_account_guid="acctguid001"` with GUID matching a DB vendor | after sync, both `expense_account` and `expense_account_guid` still present in the updated JSON entry |
| `test_fresh_install_no_json_file` | `vendor_db_path` does not exist; insert 1 vendor `"FreshInstallVendor"` into DB | sync succeeds, JSON file created, contains 1 vendor entry |

### Layer 4 — Full Stack (`TestSyncBidirectional`)

`sync_util_with_schema`.

| Test | Setup | Expected |
|---|---|---|
| `test_dry_run_returns_true` | write minimal vendor JSON; call `sync_util.sync_bidirectional(dry_run=True)` | returns `True`; no new rows inserted |
| `test_success_path` | write JSON with 1 vendor not in DB | returns `True`; vendor row created in DB; `stats['errors']` = 0 |

### Layer 4 — Public API (`TestValidateAndFixVendorReferences`)

Module-level function `validate_and_fix_vendor_references()`. Uses `db_connection`.

**Note:** This function constructs its own `VendorSyncUtility` internally — `vendor_db_path` is not patchable from outside. Use a real or writable path, or skip tests that require file writing by focusing on the return-value contract.

| Test | Setup | Expected |
|---|---|---|
| `test_returns_dict_shape` | call with any DB state | return value is a dict with keys `'valid'`, `'invalid'`, `'fixed'` (all lists) |
| `test_verbose_true_does_not_crash` | call `validate_and_fix_vendor_references(verbose=True)` | no exception raised |

---

## Windows URI Note

`discover_schema()` → `get_connection()` constructs a URI using `db_path.as_posix()` (fixed in a prior session). No additional handling needed in tests.

---

## Notes

- `validate_vendor_references()` calls `load_vendor_database()` internally — write the JSON file to `sync_util.vendor_db_path` *before* calling it.
- `TestCreateVendorInGnucash` and other Layer 4 classes share a DB copy via class-scoped `db_connection`. Use unique `display_name` values (e.g., `"__TestVendorXxx__"`) to avoid collisions between tests in the same class.
- `sync_gnucash_to_json` is a module-level function monkey-patched onto the class; call it as `sync_util.sync_gnucash_to_json()`.
- `sync_util_with_schema` must remain **function-scoped** (not class- or session-scoped) to keep `stats` isolated between tests. The cost of calling `discover_schema()` per test is acceptable.
- For `TestValidateAndFixVendorReferences`: the function creates its own `VendorSyncUtility` with a hardcoded (buggy) `vendor_db_path`. Tests focus on the return-value contract and the `verbose` branch rather than file side-effects.
- `sync_gnucash_to_json` generates JSON keys via `strip_vendor_name(vendor_name)`. Vendor names used in `TestSyncGnucashToJson` must not consist entirely of characters stripped by that function (e.g., punctuation, underscores). Use plain alphanumeric names like `"NewFromGC2026"` rather than `"__NewFromGC__"` to avoid a silently empty key.

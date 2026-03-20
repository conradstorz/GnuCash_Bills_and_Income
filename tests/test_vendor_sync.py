"""Tests for vendor_sync.py — four layers from pure in-memory logic
through full SchemaDiscovery integration against a real GnuCash DB copy.
"""
import json
import sqlite3
import uuid

import pytest

from vendor_sync import (
    VendorSyncUtility,
    get_all_gnucash_vendors,
    validate_and_fix_vendor_references,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sync_util(tmp_path):
    """VendorSyncUtility with vendor_db_path monkey-patched to tmp_path.
    Function-scoped: each test gets a fresh instance with zeroed stats.
    """
    util = VendorSyncUtility()
    util.vendor_db_path = tmp_path / "vendor_database.json"
    return util


@pytest.fixture
def sync_util_with_schema(sync_util, db_connection):
    """sync_util with discover_schema() already called against the real test DB.

    MUST remain function-scoped (inherits scope from sync_util) so every test
    gets zeroed stats. The shared class-scoped DB accumulates rows — assertions
    must query by specific GUIDs, not by table row count.

    Pytest scoping note: a function-scoped fixture CAN depend on a class-scoped
    fixture (db_connection). ScopeMismatch only occurs in the opposite direction
    (wider scope requesting narrower scope). No error will be raised here.

    db_connection patches bill_processor.config.GNUCASH_DB_PATH. vendor_sync.py
    imports `from bill_processor import config`, so the same module object is
    patched — discover_schema() and get_connection() use the test DB automatically.
    """
    result = sync_util.discover_schema()
    assert result, "discover_schema() failed — test DB may be missing vendors table"
    return sync_util


# ---------------------------------------------------------------------------
# Layer 1 — Pure in-memory (no DB, no files)
# ---------------------------------------------------------------------------

class TestValidateAndCleanupDuplicates:

    def test_no_duplicates(self, sync_util):
        sync_util.vendors_data = {
            "a": {"display_name": "Alpha", "gnucash_guid": "guid_a"},
            "b": {"display_name": "Beta",  "gnucash_guid": "guid_b"},
            "c": {"display_name": "Gamma", "gnucash_guid": "guid_c"},
        }
        result = sync_util.validate_and_cleanup_duplicates()
        assert result["duplicates_found"] == 0
        assert result["duplicates_removed"] == 0

    def test_single_duplicate_group(self, sync_util):
        sync_util.vendors_data = {
            "a": {"display_name": "Alpha", "gnucash_guid": "shared_guid"},  # inserted first → kept
            "b": {"display_name": "Beta",  "gnucash_guid": "shared_guid"},
            "c": {"display_name": "Gamma", "gnucash_guid": "shared_guid"},
        }
        result = sync_util.validate_and_cleanup_duplicates()
        assert result["duplicates_found"] == 2
        assert result["duplicates_removed"] == 2
        # "a" was inserted first (dict insertion order, Python 3.7+) so it is kept
        assert "a" in sync_util.vendors_data
        assert "b" not in sync_util.vendors_data
        assert "c" not in sync_util.vendors_data

    def test_multiple_duplicate_groups(self, sync_util):
        sync_util.vendors_data = {
            "a": {"display_name": "Alpha", "gnucash_guid": "guid_1"},  # first in group → kept
            "b": {"display_name": "Beta",  "gnucash_guid": "guid_1"},
            "c": {"display_name": "Gamma", "gnucash_guid": "guid_2"},  # first in group → kept
            "d": {"display_name": "Delta", "gnucash_guid": "guid_2"},
        }
        result = sync_util.validate_and_cleanup_duplicates()
        assert result["duplicates_removed"] == 2
        assert len(sync_util.vendors_data) == 2
        assert "a" in sync_util.vendors_data
        assert "c" in sync_util.vendors_data
        assert "b" not in sync_util.vendors_data
        assert "d" not in sync_util.vendors_data

    def test_auto_fix_false_reports_only(self, sync_util):
        sync_util.vendors_data = {
            "a": {"display_name": "Alpha", "gnucash_guid": "shared_guid"},
            "b": {"display_name": "Beta",  "gnucash_guid": "shared_guid"},
        }
        result = sync_util.validate_and_cleanup_duplicates(auto_fix=False)
        assert result["duplicates_found"] == 1
        assert result["duplicates_removed"] == 0
        assert "a" in sync_util.vendors_data
        assert "b" in sync_util.vendors_data

    def test_vendor_without_guid_skipped(self, sync_util):
        sync_util.vendors_data = {
            "a": {"display_name": "Alpha"},  # no gnucash_guid key
            "b": {"display_name": "Beta"},   # no gnucash_guid key
        }
        result = sync_util.validate_and_cleanup_duplicates()
        assert result["duplicates_found"] == 0
        assert len(sync_util.vendors_data) == 2


class TestResetVendorToUnsynced:

    def test_removes_sync_fields(self, sync_util):
        sync_util.vendors_data = {
            "v1": {
                "display_name": "Vendor 1",
                "gnucash_guid": "abc",
                "gnucash_id": "000001",
                "expense_account_guid": "xyz",
            }
        }
        result = sync_util.reset_vendor_to_unsynced("v1")
        assert result is True
        assert "gnucash_guid" not in sync_util.vendors_data["v1"]
        assert "gnucash_id" not in sync_util.vendors_data["v1"]
        assert "expense_account_guid" not in sync_util.vendors_data["v1"]

    def test_preserves_other_fields(self, sync_util):
        sync_util.vendors_data = {
            "v1": {
                "display_name": "Vendor 1",
                "addr_line1": "123 Main St",
                "gnucash_guid": "abc",
            }
        }
        sync_util.reset_vendor_to_unsynced("v1")
        assert sync_util.vendors_data["v1"]["display_name"] == "Vendor 1"
        assert sync_util.vendors_data["v1"]["addr_line1"] == "123 Main St"

    def test_unknown_key_returns_false(self, sync_util):
        sync_util.vendors_data = {}
        assert sync_util.reset_vendor_to_unsynced("nonexistent") is False

    def test_fields_already_absent_is_ok(self, sync_util):
        sync_util.vendors_data = {"v1": {"display_name": "Vendor 1"}}
        assert sync_util.reset_vendor_to_unsynced("v1") is True


class TestUpdateVendorIds:

    def test_updates_guid_and_id(self, sync_util):
        sync_util.vendors_data = {"v1": {"display_name": "Vendor 1"}}
        result = sync_util.update_vendor_ids("v1", {"guid": "new_guid", "id": "000007"})
        assert result is True
        assert sync_util.vendors_data["v1"]["gnucash_guid"] == "new_guid"
        assert sync_util.vendors_data["v1"]["gnucash_id"] == "000007"

    def test_increments_stats(self, sync_util):
        sync_util.vendors_data = {"v1": {"display_name": "Vendor 1"}}
        sync_util.update_vendor_ids("v1", {"guid": "g", "id": "1"})
        assert sync_util.stats["updated"] == 1

    def test_missing_key_returns_false(self, sync_util):
        sync_util.vendors_data = {}
        assert sync_util.update_vendor_ids("nonexistent", {"guid": "g", "id": "1"}) is False

# ---------------------------------------------------------------------------
# Layer 2 — File I/O (no DB)
# ---------------------------------------------------------------------------

class TestLoadVendorDatabase:

    def test_file_missing_returns_false(self, sync_util):
        # vendor_db_path was not written — file does not exist
        assert sync_util.load_vendor_database() is False

    def test_empty_vendors_returns_false(self, sync_util):
        sync_util.vendor_db_path.write_text(json.dumps({"vendors": {}, "aliases": {}}))
        assert sync_util.load_vendor_database() is False

    def test_loads_vendors_correctly(self, sync_util):
        data = {
            "vendors": {
                "acme": {"display_name": "Acme Corp", "gnucash_guid": "guid_a"},
                "beta": {"display_name": "Beta Co",  "gnucash_guid": "guid_b"},
            },
            "aliases": {}
        }
        sync_util.vendor_db_path.write_text(json.dumps(data))
        assert sync_util.load_vendor_database() is True
        assert len(sync_util.vendors_data) == 2
        assert sync_util.stats["total"] == 2

    def test_auto_cleans_duplicates_on_load(self, sync_util):
        data = {
            "vendors": {
                "a": {"display_name": "Alpha", "gnucash_guid": "unique_guid"},
                "b": {"display_name": "Beta",  "gnucash_guid": "dup_guid"},
                "c": {"display_name": "Gamma", "gnucash_guid": "dup_guid"},
            },
            "aliases": {}
        }
        sync_util.vendor_db_path.write_text(json.dumps(data))
        assert sync_util.load_vendor_database() is True
        # In-memory: only 2 unique entries remain
        assert len(sync_util.vendors_data) == 2
        # File on disk was rewritten with the cleaned data
        saved = json.loads(sync_util.vendor_db_path.read_text())
        assert len(saved["vendors"]) == 2

    def test_malformed_json_returns_false(self, sync_util):
        sync_util.vendor_db_path.write_text("{not valid json")
        assert sync_util.load_vendor_database() is False


class TestSaveVendorDatabase:

    def test_saves_vendors_and_preserves_aliases(self, sync_util):
        existing = {"vendors": {}, "aliases": {"foo": "bar"}}
        sync_util.vendor_db_path.write_text(json.dumps(existing))
        sync_util.vendors_data = {"v1": {"display_name": "V1"}}
        sync_util.save_vendor_database()
        saved = json.loads(sync_util.vendor_db_path.read_text())
        assert "v1" in saved["vendors"]
        assert saved["aliases"]["foo"] == "bar"

    def test_creates_aliases_key_if_file_new(self, sync_util):
        # vendor_db_path does not exist yet
        sync_util.vendors_data = {"v1": {"display_name": "V1"}}
        sync_util.save_vendor_database()
        saved = json.loads(sync_util.vendor_db_path.read_text())
        assert saved["aliases"] == {}

    def test_write_error_returns_false(self, sync_util, tmp_path):
        # Point vendor_db_path inside a nonexistent subdirectory
        sync_util.vendor_db_path = tmp_path / "nonexistent_dir" / "vendor_database.json"
        sync_util.vendors_data = {"v1": {"display_name": "V1"}}
        assert sync_util.save_vendor_database() is False

# ---------------------------------------------------------------------------
# Helper — insert a vendor row directly into the test DB
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Layer 3 — DB queries (db_connection fixture)
# ---------------------------------------------------------------------------

class TestVendorExistsInGnucash:

    def test_existing_vendor_found(self, sync_util, db_connection):
        _insert_test_vendor(db_connection, "TestCorp2026")
        result = sync_util.vendor_exists_in_gnucash("TestCorp2026")
        assert result is not None
        assert result["name"] == "TestCorp2026"
        assert "guid" in result
        assert "id" in result

    def test_nonexistent_vendor_returns_none(self, sync_util, db_connection):
        result = sync_util.vendor_exists_in_gnucash("VendorThatNeverExists99999")
        assert result is None


class TestGetNextVendorId:

    def test_returns_max_plus_one(self, sync_util, db_connection):
        # Insert with extreme ID to guarantee it is the MAX in the test DB
        _insert_test_vendor(db_connection, "MaxIdVendor2026", vendor_id="999990")
        result = sync_util.get_next_vendor_id()
        assert result == "999991"


class TestGetAllGnucashVendors:

    def test_returns_vendors_list(self, db_connection):
        _insert_test_vendor(db_connection, "ListTestVendor2026")
        vendors = get_all_gnucash_vendors()
        assert isinstance(vendors, list)
        assert len(vendors) > 0
        assert all("guid" in v and "name" in v for v in vendors)

    def test_address_fields_present(self, db_connection):
        _insert_test_vendor(db_connection, "AddrFieldVendor2026")
        vendors = get_all_gnucash_vendors()
        required = {
            "addr_name", "addr_addr1", "addr_addr2", "addr_addr3", "addr_addr4",
            "addr_phone", "addr_fax", "addr_email",
        }
        for v in vendors:
            assert required.issubset(v.keys())
            # Values must be empty strings, not None
            for key in required:
                assert v[key] is not None


class TestValidateVendorReferences:

    def _write_json(self, sync_util, vendors_dict):
        """Helper: write vendors_dict as a vendor_database.json file."""
        sync_util.vendor_db_path.write_text(json.dumps({
            "vendors": vendors_dict,
            "aliases": {}
        }))

    def test_valid_reference(self, sync_util, db_connection):
        guid = _insert_test_vendor(db_connection, "ValidRefVendor2026")
        self._write_json(sync_util, {
            "valid_vendor": {"display_name": "ValidRefVendor2026", "gnucash_guid": guid}
        })
        result = sync_util.validate_vendor_references(auto_fix=True)
        assert "valid_vendor" in result["valid"]
        assert "valid_vendor" not in result["invalid"]

    def test_invalid_reference_auto_fix(self, sync_util, db_connection):
        fake_guid = "deadbeef" + "0" * 24
        self._write_json(sync_util, {
            "stale_vendor": {"display_name": "StaleVendor", "gnucash_guid": fake_guid}
        })
        result = sync_util.validate_vendor_references(auto_fix=True)
        assert "stale_vendor" in result["invalid"]
        assert "stale_vendor" in result["fixed"]
        # gnucash_guid removed from in-memory data
        assert "gnucash_guid" not in sync_util.vendors_data.get("stale_vendor", {})
        # File on disk updated
        saved = json.loads(sync_util.vendor_db_path.read_text())
        assert "gnucash_guid" not in saved["vendors"].get("stale_vendor", {})

    def test_invalid_reference_no_auto_fix(self, sync_util, db_connection):
        fake_guid = "deadbeef" + "0" * 24
        self._write_json(sync_util, {
            "stale_vendor": {"display_name": "StaleVendor", "gnucash_guid": fake_guid}
        })
        result = sync_util.validate_vendor_references(auto_fix=False)
        assert "stale_vendor" in result["invalid"]
        assert "stale_vendor" not in result["fixed"]
        # vendors_data unchanged
        assert sync_util.vendors_data["stale_vendor"]["gnucash_guid"] == fake_guid

    def test_stale_expense_account_guid_cleaned(self, sync_util, db_connection):
        guid = _insert_test_vendor(db_connection, "ExpenseAcctVendor2026")
        stale_acct_guid = "deadacct" + "0" * 24
        self._write_json(sync_util, {
            "expense_vendor": {
                "display_name": "ExpenseAcctVendor2026",
                "gnucash_guid": guid,
                "expense_account_guid": stale_acct_guid,
            }
        })
        result = sync_util.validate_vendor_references(auto_fix=True)
        # Vendor itself is valid (GUID exists in DB)
        assert "expense_vendor" in result["valid"]
        # Stale expense_account_guid was removed
        assert "expense_vendor" in result["fixed"]
        assert "expense_account_guid" not in sync_util.vendors_data["expense_vendor"]

    def test_unsynced_vendor_skipped(self, sync_util, db_connection):
        # Vendor has no gnucash_guid — not yet synced
        self._write_json(sync_util, {
            "unsynced": {"display_name": "UnsyncedVendor"}
        })
        result = sync_util.validate_vendor_references(auto_fix=True)
        assert "unsynced" not in result["valid"]
        assert "unsynced" not in result["invalid"]
        assert "unsynced" not in result["fixed"]

# ---------------------------------------------------------------------------
# Layer 4 — Full stack with SchemaDiscovery (sync_util_with_schema fixture)
# ---------------------------------------------------------------------------

class TestBuildVendorInsert:

    def test_returns_valid_sql_and_columns(self, sync_util_with_schema):
        sql, columns = sync_util_with_schema.build_vendor_insert()
        assert isinstance(sql, str)
        assert sql.strip().upper().startswith("INSERT INTO VENDORS")
        assert isinstance(columns, list)
        assert len(columns) > 0
        for required_col in ("guid", "name", "id"):
            assert required_col in columns


class TestCreateVendorInGnucash:

    def test_vendor_row_inserted(self, sync_util_with_schema, db_connection):
        vendor_data = {"display_name": "CreateTestVendor2026"}
        sync_util_with_schema.create_vendor_in_gnucash("create_test", vendor_data)
        guid = vendor_data.get("gnucash_guid")
        assert guid, "gnucash_guid was not set on vendor_data"
        conn = sqlite3.connect(str(db_connection))
        row = conn.execute("SELECT guid FROM vendors WHERE guid = ?", (guid,)).fetchone()
        conn.close()
        assert row is not None

    def test_address_fields_saved(self, sync_util_with_schema, db_connection):
        vendor_data = {
            "display_name": "AddrSaveVendor2026",
            "addr_name": "AddrSaveVendor2026",
            "addr_line1": "456 Oak Ave",
            "phone": "555-9876",
        }
        sync_util_with_schema.create_vendor_in_gnucash("addr_save_test", vendor_data)
        guid = vendor_data.get("gnucash_guid")
        conn = sqlite3.connect(str(db_connection))
        row = conn.execute(
            "SELECT addr_name, addr_addr1, addr_phone FROM vendors WHERE guid = ?",
            (guid,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "AddrSaveVendor2026"
        assert row[1] == "456 Oak Ave"
        assert row[2] == "555-9876"

    def test_vendor_data_updated_with_guid(self, sync_util_with_schema):
        vendor_data = {"display_name": "GuidUpdateVendor2026"}
        result = sync_util_with_schema.create_vendor_in_gnucash("guid_update_test", vendor_data)
        assert result is True
        assert vendor_data.get("gnucash_guid")
        assert vendor_data.get("gnucash_id")

    def test_stats_created_incremented(self, sync_util_with_schema):
        vendor_data = {"display_name": "StatsVendor2026"}
        sync_util_with_schema.create_vendor_in_gnucash("stats_test", vendor_data)
        assert sync_util_with_schema.stats["created"] == 1

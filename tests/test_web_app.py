"""Tests for the FastAPI REST API."""
import tempfile
import os
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from bill_processor.web.app import app
    return TestClient(app)


@pytest.fixture
def tmp_queue(tmp_path, monkeypatch):
    queue_file = tmp_path / "bills_to_process.txt"
    queue_file.write_text("")
    from bill_processor import config
    monkeypatch.setattr(config, "BILLS_INPUT_PATH", queue_file)
    return queue_file


@pytest.fixture
def isolated_settings(monkeypatch):
    from bill_processor import settings_manager
    from bill_processor.web import app as web_app
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name
    try:
        fresh = settings_manager.SettingsManager(settings_file=Path(tmp_path))
        monkeypatch.setattr(web_app, "settings", fresh)
        yield fresh
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Status & Health
# ---------------------------------------------------------------------------

def test_status_returns_ok(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "vendor_sync" in data
    assert "queued_bills" in data


def test_db_health_returns_status(client):
    response = client.get("/api/db/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


# ---------------------------------------------------------------------------
# Bills queue CRUD
# ---------------------------------------------------------------------------

def test_get_bills_returns_list(client, tmp_queue):
    response = client.get("/api/bills")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_add_bill_to_queue(client, tmp_queue):
    response = client.post("/api/bills", json={
        "vendor_name": "Acme Electric",
        "amount": 123.45,
        "memo": "Test bill",
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 201
    assert response.json()["ok"] is True
    assert "Acme Electric" in tmp_queue.read_text()
    assert "123.45" in tmp_queue.read_text()


def test_add_bill_with_check_number(client, tmp_queue):
    response = client.post("/api/bills", json={
        "vendor_name": "Acme Electric",
        "amount": 123.45,
        "memo": "Test bill",
        "bill_date": "2026-03-01",
        "check_number": "1042",
    })
    assert response.status_code == 201
    assert "1042" in tmp_queue.read_text()


def test_add_bill_without_check_number_omits_fifth_field(client, tmp_queue):
    response = client.post("/api/bills", json={
        "vendor_name": "Acme Electric",
        "amount": 123.45,
        "memo": "Test bill",
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 201
    assert tmp_queue.read_text().strip().endswith("2026-03-01")


def test_add_bill_empty_name_returns_422(client, tmp_queue):
    response = client.post("/api/bills", json={
        "vendor_name": "",
        "amount": 100.00,
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 422


def test_delete_bill_from_queue(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
    response = client.delete("/api/bills/0")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert tmp_queue.read_text().strip() == ""


def test_update_bill_in_queue(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
    response = client.put("/api/bills/0", json={
        "vendor_name": "Acme Electric",
        "amount": 200.00,
        "memo": "Updated",
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "200.0" in tmp_queue.read_text()


def test_update_bill_adds_check_number(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
    response = client.put("/api/bills/0", json={
        "vendor_name": "Acme Electric",
        "amount": 123.45,
        "memo": "test",
        "bill_date": "2026-03-01",
        "check_number": "2001",
    })
    assert response.status_code == 200
    assert "2001" in tmp_queue.read_text()


def test_update_bill_clears_check_number(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01, 1042\n")
    response = client.put("/api/bills/0", json={
        "vendor_name": "Acme Electric",
        "amount": 123.45,
        "memo": "test",
        "bill_date": "2026-03-01",
        "check_number": "",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text().strip()
    assert "1042" not in content
    assert content.endswith("2026-03-01")


# ---------------------------------------------------------------------------
# Bill processing
# ---------------------------------------------------------------------------

def test_create_vendor_empty_name_returns_error(client):
    response = client.post("/api/vendors", json={"vendor_name": "", "display_name": ""})
    assert response.status_code == 422


def test_process_single_missing_index_returns_404(client, tmp_queue):
    response = client.post("/api/bills/99/post")
    assert response.status_code == 404


def test_post_all_empty_queue_returns_ok(client, tmp_queue):
    response = client.post("/api/bills/post-all")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["succeeded"] == []
    assert data["failed"] == []


# ---------------------------------------------------------------------------
# TestFormatBillLine — unchanged; tests queue_io helper directly
# ---------------------------------------------------------------------------

class TestFormatBillLine:
    def test_with_check_number_appends_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15), "1042")
        assert result == "Acme Electric, 150.50, memo, 2026-03-15, 1042\n"

    def test_without_check_number_omits_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15))
        assert result == "Acme Electric, 150.50, memo, 2026-03-15\n"

    def test_empty_check_number_omits_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15), "")
        assert result == "Acme Electric, 150.50, memo, 2026-03-15\n"


# ---------------------------------------------------------------------------
# TestProcessOneBill — unchanged; tests internal helper directly
# ---------------------------------------------------------------------------

class TestProcessOneBill:
    VENDOR_GUID = "a" * 32
    EXPENSE_GUID = "b" * 32
    CHECKING_GUID = "c" * 32
    BILL_GUID = "d" * 32

    def _bill(self, check_number=""):
        return {
            "vendor_name": "Acme Electric",
            "amount": 123.45,
            "memo": "electric bill",
            "date": date(2026, 3, 1),
            "check_number": check_number,
            "_index": 0,
            "_raw": "Acme Electric, 123.45, electric bill, 2026-03-01",
        }

    def _good_vendor(self):
        return {"gnucash_guid": self.VENDOR_GUID, "display_name": "Acme Electric"}

    def _patch_gnucash(self, monkeypatch, web_app):
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setitem(web_app.settings._settings, "expense_account_guid", self.EXPENSE_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "post_bill", lambda **kw: None)
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", lambda **kw: "pay_guid")

    def test_success_returns_ok(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        self._patch_gnucash(monkeypatch, web_app)
        result = web_app._process_one_bill(self._bill())
        assert result == {"ok": True}

    def test_vendor_not_found_returns_error(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (None, "not_found")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "Acme Electric" in result["error"]

    def test_no_expense_account_returns_error(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setitem(web_app.settings._settings, "expense_account_guid", None)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "expense account" in result["error"].lower()

    def test_gnucash_exception_returns_error(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setitem(web_app.settings._settings, "expense_account_guid", self.EXPENSE_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        def fail(**kw):
            raise ValueError("DB locked")
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", fail)
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "DB locked" in result["error"]

    def test_check_number_forwarded_to_pay_bill(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        self._patch_gnucash(monkeypatch, web_app)
        captured = {}
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", lambda **kw: captured.update(kw) or "pay_guid")
        web_app._process_one_bill(self._bill(check_number="1042"))
        assert captured.get("check_number") == "1042"

    def test_uses_configured_ap_account_guid(self, monkeypatch):
        from bill_processor.web import app as web_app
        AP_GUID = "e" * 32
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Accounts Payable", "guid": guid})
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", AP_GUID)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setitem(web_app.settings._settings, "expense_account_guid", self.EXPENSE_GUID)
        captured = {}
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "post_bill", lambda **kw: captured.update(kw))
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", lambda **kw: "pay_guid")
        web_app._process_one_bill(self._bill())
        assert captured.get("ap_account_guid") == AP_GUID

    def test_blocks_when_ap_account_not_configured(self, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", None)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "Processing accounts not configured" in result["error"]

    def test_blocks_when_checking_account_not_configured(self, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", None)
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "Processing accounts not configured" in result["error"]


# ---------------------------------------------------------------------------
# TestProcessQueueRoutes — queue manipulation logic unchanged; response is JSON
# ---------------------------------------------------------------------------

class TestProcessQueueRoutes:

    def test_process_single_success_removes_bill(self, client, tmp_queue, monkeypatch):
        from bill_processor.web import app as web_app
        tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
        monkeypatch.setattr(web_app, "_process_one_bill", lambda bill: {"ok": True})
        response = client.post("/api/bills/0/post")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert tmp_queue.read_text().strip() == ""

    def test_process_single_failure_keeps_bill(self, client, tmp_queue, monkeypatch):
        from bill_processor.web import app as web_app
        tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
        monkeypatch.setattr(web_app, "_process_one_bill",
                            lambda bill: {"ok": False, "error": "Vendor not found"})
        response = client.post("/api/bills/0/post")
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert "Acme Electric" in tmp_queue.read_text()

    def test_process_single_failure_returns_error_message(self, client, tmp_queue, monkeypatch):
        from bill_processor.web import app as web_app
        tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
        monkeypatch.setattr(web_app, "_process_one_bill",
                            lambda bill: {"ok": False, "error": "DB locked"})
        response = client.post("/api/bills/0/post")
        assert response.status_code == 200
        assert "DB locked" in response.json()["error"]

    def test_process_all_success_clears_queue(self, client, tmp_queue, monkeypatch):
        from bill_processor.web import app as web_app
        tmp_queue.write_text(
            "Acme Electric, 123.45, test, 2026-03-01\n"
            "Bob Plumbing, 200.00, repair, 2026-03-02\n"
        )
        monkeypatch.setattr(web_app, "_process_one_bill", lambda bill: {"ok": True})
        response = client.post("/api/bills/post-all")
        assert response.status_code == 200
        assert tmp_queue.read_text().strip() == ""
        data = response.json()
        assert len(data["succeeded"]) == 2
        assert data["failed"] == []

    def test_process_all_partial_failure_keeps_failed_bills(self, client, tmp_queue, monkeypatch):
        from bill_processor.web import app as web_app
        tmp_queue.write_text(
            "Acme Electric, 123.45, test, 2026-03-01\n"
            "Unknown Vendor, 50.00, misc, 2026-03-02\n"
        )
        def selective(bill):
            return {"ok": True} if bill["vendor_name"] == "Acme Electric" else {"ok": False, "error": "Vendor not found"}
        monkeypatch.setattr(web_app, "_process_one_bill", selective)
        response = client.post("/api/bills/post-all")
        assert response.status_code == 200
        remaining = tmp_queue.read_text()
        assert "Acme Electric" not in remaining
        assert "Unknown Vendor" in remaining
        data = response.json()
        assert "Acme Electric" in data["succeeded"]
        assert any(f["vendor_name"] == "Unknown Vendor" for f in data["failed"])


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class TestSettings:
    AP_GUID = "e" * 32
    CHECKING_GUID = "c" * 32

    def test_get_settings_returns_dict(self, client, isolated_settings):
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert "ap_account_guid" in data
        assert "checking_account_guid" in data

    def test_put_ap_account_guid_persists(self, client, isolated_settings, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "AP", "guid": guid})
        response = client.put("/api/settings", json={"ap_account_guid": self.AP_GUID})
        assert response.status_code == 200
        assert isolated_settings.ap_account_guid == self.AP_GUID

    def test_put_checking_account_guid_persists(self, client, isolated_settings, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Checking", "guid": guid})
        response = client.put("/api/settings", json={"checking_account_guid": self.CHECKING_GUID})
        assert response.status_code == 200
        assert isolated_settings.checking_account_guid == self.CHECKING_GUID


# ---------------------------------------------------------------------------
# Vendor search candidates
# ---------------------------------------------------------------------------

class TestVendorSearchCandidates:
    GOOGLE_RESULT = [
        {
            "name": "The Home Depot",
            "addr_line1": "4011 Eastgate Dr",
            "city": "Cincinnati",
            "state": "OH",
            "zip": "45245",
            "source": "google",
        }
    ]
    OSM_RESULT = [
        {
            "name": "Home Depot",
            "addr_line1": "100 Main St",
            "city": "Columbus",
            "state": "OH",
            "zip": "43215",
            "source": "openstreetmap",
        }
    ]

    def test_returns_google_candidates(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        mock_lookup = MagicMock()
        mock_lookup.lookup_google_places.return_value = self.GOOGLE_RESULT
        monkeypatch.setattr(web_app, "addr_lookup", mock_lookup)
        response = client.get("/api/vendors/search-candidates?name=Home+Depot")
        assert response.status_code == 200
        data = response.json()
        assert len(data["candidates"]) == 1
        c = data["candidates"][0]
        assert c["display_name"] == "The Home Depot"
        assert c["addr_line1"] == "4011 Eastgate Dr"
        assert c["addr_city"] == "Cincinnati"
        assert c["addr_state"] == "OH"
        assert c["addr_zip"] == "45245"
        mock_lookup.lookup_google_places.assert_called_once_with("Home Depot", return_all=True)

    def test_falls_back_to_osm_when_google_empty(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        mock_lookup = MagicMock()
        mock_lookup.lookup_google_places.return_value = []
        mock_lookup.lookup_openstreetmap.return_value = self.OSM_RESULT
        monkeypatch.setattr(web_app, "addr_lookup", mock_lookup)
        response = client.get("/api/vendors/search-candidates?name=Home+Depot")
        assert response.status_code == 200
        assert len(response.json()["candidates"]) == 1
        assert response.json()["candidates"][0]["display_name"] == "Home Depot"
        mock_lookup.lookup_google_places.assert_called_once_with("Home Depot", return_all=True)
        mock_lookup.lookup_openstreetmap.assert_called_once_with("Home Depot", return_all=True)

    def test_empty_query_returns_empty_list(self, client):
        response = client.get("/api/vendors/search-candidates")
        assert response.status_code == 200
        assert response.json() == {"candidates": []}

    def test_lookup_returns_none_returns_empty_list(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        mock_lookup = MagicMock()
        mock_lookup.lookup_google_places.return_value = None
        mock_lookup.lookup_openstreetmap.return_value = None
        monkeypatch.setattr(web_app, "addr_lookup", mock_lookup)
        response = client.get("/api/vendors/search-candidates?name=Unknown+Vendor")
        assert response.status_code == 200
        assert response.json() == {"candidates": []}

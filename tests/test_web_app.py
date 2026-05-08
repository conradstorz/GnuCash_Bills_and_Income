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

    def test_all_three_steps_called_in_order(self, monkeypatch):
        """_process_one_bill() must invoke create_bill, post_bill, AND pay_bill in that order."""
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        self._patch_gnucash(monkeypatch, web_app)
        call_order = []
        monkeypatch.setattr(web_app.gnucash_db, "create_bill",
                            lambda **kw: (call_order.append("create_bill"), self.BILL_GUID)[1])
        monkeypatch.setattr(web_app.gnucash_db, "post_bill",
                            lambda **kw: call_order.append("post_bill"))
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill",
                            lambda **kw: (call_order.append("pay_bill"), "pay_guid")[1])
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is True
        assert call_order == ["create_bill", "post_bill", "pay_bill"], (
            f"Expected create->post->pay order, got: {call_order}"
        )

    def test_create_bill_receives_expense_account_from_settings(self, monkeypatch):
        """create_bill() must receive the expense_account_guid from settings."""
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        self._patch_gnucash(monkeypatch, web_app)
        captured = {}
        monkeypatch.setattr(web_app.gnucash_db, "create_bill",
                            lambda **kw: (captured.update(kw), self.BILL_GUID)[1])
        web_app._process_one_bill(self._bill())
        assert captured.get("expense_account_guid") == self.EXPENSE_GUID

    def test_post_bill_receives_bill_guid_from_create_bill(self, monkeypatch):
        """post_bill() must receive the bill_guid returned by create_bill()."""
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        self._patch_gnucash(monkeypatch, web_app)
        captured = {}
        monkeypatch.setattr(web_app.gnucash_db, "post_bill",
                            lambda **kw: captured.update(kw))
        web_app._process_one_bill(self._bill())
        assert captured.get("bill_guid") == self.BILL_GUID, (
            "post_bill must receive the bill_guid returned by create_bill"
        )

    def test_pay_bill_receives_bill_guid_from_create_bill(self, monkeypatch):
        """pay_bill() must receive the same bill_guid that was passed to post_bill()."""
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        self._patch_gnucash(monkeypatch, web_app)
        captured = {}
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill",
                            lambda **kw: (captured.update(kw), "pay_guid")[1])
        web_app._process_one_bill(self._bill())
        assert captured.get("bill_guid") == self.BILL_GUID, (
            "pay_bill must receive the bill_guid returned by create_bill"
        )


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


# ---------------------------------------------------------------------------
# Accounts routes
# ---------------------------------------------------------------------------

class TestGetAllAccounts:
    ACCOUNTS = [
        {"name": "Cash in Wallet", "guid": "a" * 32},
        {"name": "Savings", "guid": "b" * 32},
    ]

    def test_returns_accounts_list(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_cash_accounts", lambda: self.ACCOUNTS)
        response = client.get("/api/accounts")
        assert response.status_code == 200
        assert response.json() == self.ACCOUNTS

    def test_returns_empty_list_when_no_accounts(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_cash_accounts", lambda: [])
        response = client.get("/api/accounts")
        assert response.status_code == 200
        assert response.json() == []


class TestGetCashAccounts:
    ACCOUNTS = [
        {"name": "Cash in Wallet", "guid": "a" * 32},
        {"name": "Savings", "guid": "b" * 32},
    ]

    def test_returns_enabled_subset(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_cash_accounts", lambda: self.ACCOUNTS)
        monkeypatch.setitem(
            web_app.settings._settings,
            "enabled_cash_account_guids",
            ["a" * 32],
        )
        response = client.get("/api/accounts/cash")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["guid"] == "a" * 32

    def test_returns_all_when_no_filter_configured(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_cash_accounts", lambda: self.ACCOUNTS)
        monkeypatch.setitem(web_app.settings._settings, "enabled_cash_account_guids", [])
        response = client.get("/api/accounts/cash")
        assert response.status_code == 200
        assert len(response.json()) == 2


class TestValidateAccount:
    ACCOUNTS = [
        {"name": "Cash in Wallet", "guid": "a" * 32},
        {"name": "Savings", "guid": "b" * 32},
    ]

    def test_valid_account_name_returns_true_and_guid(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_cash_accounts", lambda: self.ACCOUNTS)
        response = client.get("/api/accounts/validate?name=Cash+in+Wallet")
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["guid"] == "a" * 32

    def test_case_insensitive_match(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_cash_accounts", lambda: self.ACCOUNTS)
        response = client.get("/api/accounts/validate?name=cash+in+wallet")
        assert response.status_code == 200
        assert response.json()["valid"] is True

    def test_unknown_account_returns_false_and_null_guid(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_cash_accounts", lambda: self.ACCOUNTS)
        response = client.get("/api/accounts/validate?name=Nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert data["guid"] is None

    def test_empty_name_returns_false(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_cash_accounts", lambda: self.ACCOUNTS)
        response = client.get("/api/accounts/validate")
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert data["guid"] is None


# ---------------------------------------------------------------------------
# Vendor fuzzy search route
# ---------------------------------------------------------------------------

class TestVendorSearch:
    VENDORS = {
        "acme_electric": {"display_name": "Acme Electric"},
        "bob_plumbing": {"display_name": "Bob Plumbing"},
    }

    def _mock_vm(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.vendors = {"vendors": self.VENDORS}
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        return mock_vm

    def test_empty_query_returns_empty_results(self, client, monkeypatch):
        self._mock_vm(monkeypatch)
        response = client.get("/api/vendors/search")
        assert response.status_code == 200
        assert response.json() == {"results": []}

    def test_whitespace_only_query_returns_empty_results(self, client, monkeypatch):
        self._mock_vm(monkeypatch)
        response = client.get("/api/vendors/search?q=+++")
        assert response.status_code == 200
        assert response.json() == {"results": []}

    def test_matching_query_returns_results(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        self._mock_vm(monkeypatch)
        # fuzzy_match_vendor is a module-level import; patch it
        monkeypatch.setattr(
            web_app,
            "fuzzy_match_vendor",
            lambda q, vendors, threshold: (
                "acme_electric",
                95,
                [("acme_electric", 95)],
            ),
        )
        response = client.get("/api/vendors/search?q=Acme")
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) >= 1
        keys = [r["key"] for r in data["results"]]
        assert "acme_electric" in keys

    def test_no_match_returns_empty_results(self, client, monkeypatch):
        from bill_processor.web import app as web_app
        self._mock_vm(monkeypatch)
        monkeypatch.setattr(
            web_app,
            "fuzzy_match_vendor",
            lambda q, vendors, threshold: (None, 0, []),
        )
        response = client.get("/api/vendors/search?q=zzzzunknown")
        assert response.status_code == 200
        assert response.json() == {"results": []}


# ---------------------------------------------------------------------------
# PUT /api/vendors/{key}
# ---------------------------------------------------------------------------

class TestUpdateVendor:
    BASE_VENDORS = {
        "vendors": {
            "acme_electric": {
                "display_name": "Acme Electric",
                "gnucash_guid": "g" * 32,
                "addr_line1": "1 Main St",
                "addr_city": "Cincinnati",
                "addr_state": "OH",
                "addr_zip": "45200",
            }
        },
        "aliases": {},
    }

    def _mock_vm(self, monkeypatch, vendors=None):
        import copy
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.vendors = copy.deepcopy(vendors or self.BASE_VENDORS)
        mock_vm.save = MagicMock()
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        return mock_vm

    def test_update_display_name_succeeds(self, client, monkeypatch):
        mock_vm = self._mock_vm(monkeypatch)
        response = client.put("/api/vendors/acme_electric", json={"display_name": "ACME Electric LLC"})
        assert response.status_code == 200
        assert response.json()["ok"] is True
        mock_vm.save.assert_called_once()
        assert mock_vm.vendors["vendors"]["acme_electric"]["display_name"] == "ACME Electric LLC"

    def test_unknown_key_returns_404(self, client, monkeypatch):
        self._mock_vm(monkeypatch)
        response = client.put("/api/vendors/no_such_vendor", json={"display_name": "X"})
        assert response.status_code == 404

    def test_update_address_fields(self, client, monkeypatch):
        mock_vm = self._mock_vm(monkeypatch)
        response = client.put("/api/vendors/acme_electric", json={
            "addr_line1": "99 Oak Ave",
            "addr_city": "Dayton",
            "addr_state": "OH",
            "addr_zip": "45400",
        })
        assert response.status_code == 200
        v = mock_vm.vendors["vendors"]["acme_electric"]
        assert v["addr_line1"] == "99 Oak Ave"
        assert v["addr_city"] == "Dayton"
        assert v["addr_zip"] == "45400"

    def test_update_aliases_replaces_existing(self, client, monkeypatch):
        import copy
        vendors = copy.deepcopy(self.BASE_VENDORS)
        vendors["aliases"] = {"old_alias": "acme_electric"}
        mock_vm = self._mock_vm(monkeypatch, vendors=vendors)
        response = client.put("/api/vendors/acme_electric", json={"aliases": ["new_alias"]})
        assert response.status_code == 200
        aliases = mock_vm.vendors["aliases"]
        assert "old_alias" not in aliases
        assert aliases.get("new_alias") == "acme_electric"


# ---------------------------------------------------------------------------
# POST /api/vendors/sync-all
# ---------------------------------------------------------------------------

class TestVendorSyncAll:
    def _mock_sync(self, monkeypatch, *, discover_ok=True, raises=None):
        from bill_processor.web import app as web_app
        mock_sync = MagicMock()
        mock_sync.discover_schema.return_value = discover_ok
        if raises:
            mock_sync.discover_schema.side_effect = raises
        mock_sync.sync_gnucash_to_json.return_value = None
        monkeypatch.setattr(web_app, "VendorSyncUtility", lambda: mock_sync)
        return mock_sync

    def test_success_returns_ok(self, client, monkeypatch):
        self._mock_sync(monkeypatch)
        response = client.post("/api/vendors/sync-all")
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_schema_discovery_failure_returns_error(self, client, monkeypatch):
        self._mock_sync(monkeypatch, discover_ok=False)
        response = client.post("/api/vendors/sync-all")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "schema" in data["error"].lower()

    def test_exception_returns_error_message(self, client, monkeypatch):
        self._mock_sync(monkeypatch, raises=RuntimeError("Connection failed"))
        response = client.post("/api/vendors/sync-all")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "Connection failed" in data["error"]

    def test_sync_gnucash_to_json_called_on_success(self, client, monkeypatch):
        mock_sync = self._mock_sync(monkeypatch)
        client.post("/api/vendors/sync-all")
        mock_sync.sync_gnucash_to_json.assert_called_once()


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

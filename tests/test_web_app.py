"""Tests for the FastAPI web application."""
import tempfile
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
    """Patch BILLS_INPUT_PATH to a temp file."""
    queue_file = tmp_path / "bills_to_process.txt"
    queue_file.write_text("")
    from bill_processor import config
    monkeypatch.setattr(config, "BILLS_INPUT_PATH", queue_file)
    return queue_file


def test_status_returns_ok(client):
    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert "vendor_sync" in data
    assert "queued_bills" in data


def test_dashboard_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"GnuCash Bill Processor" in response.content


def test_add_bill_to_queue(client, tmp_queue):
    response = client.post("/bills/queue", data={
        "vendor_name": "Acme Electric",
        "amount": "123.45",
        "memo": "Test bill",
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text()
    assert "Acme Electric" in content
    assert "123.45" in content


def test_delete_bill_from_queue(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
    response = client.delete("/bills/queue/0")
    assert response.status_code == 200
    assert tmp_queue.read_text().strip() == ""


def test_edit_bill_in_queue(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
    response = client.patch("/bills/queue/0", data={
        "vendor_name": "Acme Electric",
        "amount": "200.00",
        "memo": "Updated",
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text()
    assert "200.00" in content


def test_vendor_search_returns_html(client):
    response = client.get("/vendors/search", params={"vendor_name": "acme"})
    assert response.status_code == 200
    # Returns HTML fragment (empty or with results)
    assert "text/html" in response.headers["content-type"]


def test_vendor_search_empty_query(client):
    response = client.get("/vendors/search", params={"vendor_name": ""})
    assert response.status_code == 200
    # Empty query returns empty response
    assert response.content == b""


def test_new_vendor_form_renders(client):
    response = client.get("/vendors/new-form", params={"name": "TestVendor"})
    assert response.status_code == 200
    assert b"TestVendor" in response.content


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
    # and the rendered vendor name.
    assert '"display_name": "Kroger"' in response.text


def test_new_vendor_form_city_zip_have_refinement_triggers(client):
    """City and ZIP inputs carry HTMX refinement triggers."""
    response = client.get("/vendors/new-form", params={"name": "Kroger"})
    assert response.status_code == 200
    html = response.text
    assert 'hx-trigger="keyup changed delay:500ms"' in html
    assert 'hx-include="#new-vendor-form input"' in html


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
    # All three clearing operations must be in the cancel onclick
    assert "new-vendor-section" in html
    assert "vendor-dropdown" in html
    assert "vendor-input" in html
    assert "innerHTML=''" in html  # section and dropdown are cleared this way
    assert ".value=''" in html  # vendor-input is blanked this way


def test_address_lookup_returns_json(client):
    """Address lookup returns JSON with candidates list and message."""
    response = client.post("/vendors/lookup-address", data={"vendor_name": "Acme Electric"})
    assert response.status_code == 200
    data = response.json()
    assert "candidates" in data
    assert "message" in data
    assert isinstance(data["candidates"], list)


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


def test_add_bill_with_check_number(client, tmp_queue):
    response = client.post("/bills/queue", data={
        "vendor_name": "Acme Electric",
        "amount": "123.45",
        "memo": "Test bill",
        "bill_date": "2026-03-01",
        "check_number": "1042",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text()
    assert "1042" in content


def test_add_bill_without_check_number_omits_fifth_field(client, tmp_queue):
    response = client.post("/bills/queue", data={
        "vendor_name": "Acme Electric",
        "amount": "123.45",
        "memo": "Test bill",
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text().strip()
    # Should end with the date, no trailing comma
    assert content.endswith("2026-03-01")


def test_edit_bill_adds_check_number(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
    response = client.patch("/bills/queue/0", data={
        "vendor_name": "Acme Electric",
        "amount": "123.45",
        "memo": "test",
        "bill_date": "2026-03-01",
        "check_number": "2001",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text()
    assert "2001" in content


def test_edit_bill_clears_check_number(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01, 1042\n")
    response = client.patch("/bills/queue/0", data={
        "vendor_name": "Acme Electric",
        "amount": "123.45",
        "memo": "test",
        "bill_date": "2026-03-01",
        "check_number": "",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text().strip()
    assert "1042" not in content
    assert content.endswith("2026-03-01")


def test_create_vendor_empty_name_returns_json_error(client):
    """Creating a vendor with empty name returns JSON error."""
    response = client.post("/vendors/create", data={
        "vendor_name": "",
        "display_name": "",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "required" in data["error"].lower()


def test_process_all_empty_queue(client, tmp_queue):
    """Processing an empty queue returns 200 and the queue card."""
    response = client.post("/bills/queue/process")
    assert response.status_code == 200
    assert b"queued-bills" in response.content


def test_process_single_missing_index(client, tmp_queue):
    """Processing a non-existent index returns 200 with error in queue card."""
    response = client.post("/bills/queue/99/process")
    assert response.status_code == 200
    assert b"queued-bills" in response.content


def test_sync_vendors_returns_html(client):
    """Vendor sync returns 200 with HTML sync status card."""
    response = client.post("/vendors/sync")
    assert response.status_code == 200
    assert b"sync-status" in response.content


def test_shutdown_endpoint_exists(client):
    """Shutdown endpoint exists and returns a response (even if server stops)."""
    # Use raise_server_exceptions=False so test doesn't fail on shutdown signal
    from fastapi.testclient import TestClient
    from bill_processor.web.app import app as fastapi_app
    test_client = TestClient(fastapi_app, raise_server_exceptions=False)
    response = test_client.post("/shutdown")
    assert response.status_code in (200, 503, 500)


def test_queued_bills_partial_route(client, tmp_queue):
    """GET /partials/queued-bills returns the queue card HTML."""
    response = client.get("/partials/queued-bills")
    assert response.status_code == 200
    assert b"queued-bills" in response.content


class TestFormatBillLine:
    def test_with_check_number_appends_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        from datetime import date
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15), "1042")
        assert result == "Acme Electric, 150.50, memo, 2026-03-15, 1042\n"

    def test_without_check_number_omits_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        from datetime import date
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15))
        assert result == "Acme Electric, 150.50, memo, 2026-03-15\n"

    def test_empty_check_number_omits_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        from datetime import date
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15), "")
        assert result == "Acme Electric, 150.50, memo, 2026-03-15\n"


class TestProcessOneBill:
    """Unit tests for _process_one_bill() — mocks GnuCash I/O to test routing logic."""

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
        return {
            "gnucash_guid": self.VENDOR_GUID,
            "display_name": "Acme Electric",
            "expense_account_guid": self.EXPENSE_GUID,
        }

    def _patch_gnucash(self, monkeypatch, web_app):
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        monkeypatch.setattr(web_app.gnucash_db, "create_bill",
                            lambda **kw: self.BILL_GUID)
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
        vendor_no_expense = {"gnucash_guid": self.VENDOR_GUID, "display_name": "Acme Electric"}
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (vendor_no_expense, "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
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
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "post_bill", lambda **kw: None)

        captured = {}

        def capture_pay(**kw):
            captured.update(kw)
            return "pay_guid"

        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", capture_pay)

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

        captured = {}
        def capture_post(**kw):
            captured.update(kw)
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "post_bill", capture_post)
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", lambda **kw: "pay_guid")

        web_app._process_one_bill(self._bill())
        assert captured.get("ap_account_guid") == AP_GUID

    def test_uses_configured_checking_account_guid(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Checking", "guid": guid})
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)

        captured = {}
        def capture_pay(**kw):
            captured.update(kw)
            return "pay_guid"
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "post_bill", lambda **kw: None)
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", capture_pay)

        web_app._process_one_bill(self._bill())
        assert captured.get("checking_account_guid") == self.CHECKING_GUID

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


class TestProcessQueueRoutes:
    """Integration tests for /bills/queue/process and /bills/queue/{index}/process."""

    def test_process_single_success_removes_bill(self, client, tmp_queue, monkeypatch):
        """A successfully processed bill is removed from the queue."""
        from bill_processor.web import app as web_app
        tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
        monkeypatch.setattr(web_app, "_process_one_bill", lambda bill: {"ok": True})

        response = client.post("/bills/queue/0/process")
        assert response.status_code == 200
        assert tmp_queue.read_text().strip() == ""

    def test_process_single_failure_keeps_bill(self, client, tmp_queue, monkeypatch):
        """A processing failure leaves the bill in the queue."""
        from bill_processor.web import app as web_app
        tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
        monkeypatch.setattr(web_app, "_process_one_bill",
                            lambda bill: {"ok": False, "error": "Vendor not found"})

        response = client.post("/bills/queue/0/process")
        assert response.status_code == 200
        assert "Acme Electric" in tmp_queue.read_text()

    def test_process_all_success_clears_queue(self, client, tmp_queue, monkeypatch):
        """Processing all bills successfully empties the queue."""
        from bill_processor.web import app as web_app
        tmp_queue.write_text(
            "Acme Electric, 123.45, test, 2026-03-01\n"
            "Bob Plumbing, 200.00, repair, 2026-03-02\n"
        )
        monkeypatch.setattr(web_app, "_process_one_bill", lambda bill: {"ok": True})

        response = client.post("/bills/queue/process")
        assert response.status_code == 200
        assert tmp_queue.read_text().strip() == ""

    def test_process_all_partial_failure_keeps_failed_bills(self, client, tmp_queue, monkeypatch):
        """Only successfully processed bills are removed; failed ones stay."""
        from bill_processor.web import app as web_app
        tmp_queue.write_text(
            "Acme Electric, 123.45, test, 2026-03-01\n"
            "Unknown Vendor, 50.00, misc, 2026-03-02\n"
        )

        def selective_process(bill):
            if bill["vendor_name"] == "Acme Electric":
                return {"ok": True}
            return {"ok": False, "error": "Vendor not found"}

        monkeypatch.setattr(web_app, "_process_one_bill", selective_process)

        response = client.post("/bills/queue/process")
        assert response.status_code == 200
        remaining = tmp_queue.read_text()
        assert "Acme Electric" not in remaining
        assert "Unknown Vendor" in remaining


@pytest.fixture
def isolated_settings(monkeypatch):
    """Fresh SettingsManager backed by a temp file, swapped into web_app.settings."""
    import tempfile, os
    from pathlib import Path as _Path
    from bill_processor import settings_manager
    from bill_processor.web import app as web_app
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name
    try:
        fresh = settings_manager.SettingsManager(settings_file=_Path(tmp_path))
        monkeypatch.setattr(web_app, "settings", fresh)
        yield fresh
    finally:
        os.unlink(tmp_path)


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


def test_vendor_dropdown_add_item_uses_after_request_not_onclick(client):
    """The '+ Add' item clears the dropdown via hx-on::after-request, not onclick."""
    response = client.get("/vendors/search", params={"vendor_name": "TestQuery"})
    assert response.status_code == 200
    html = response.text
    # New attribute must be present
    assert "hx-on::after-request" in html
    # The old synchronous onclick that cleared the dropdown must be gone from the add item.
    assert "onclick=\"document.getElementById('vendor-dropdown').innerHTML=''\"" not in html

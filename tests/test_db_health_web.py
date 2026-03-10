"""Tests for DB health check integration in GET /."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from bill_processor.web.app import app

client = TestClient(app)

HEALTHY = {"status": "ok", "message": "Database is accessible.", "path": "/fake/db.gnucash",
           "hostname": None, "pid": None}
MISSING = {"status": "missing",
           "message": "Database file not found at the configured path.",
           "path": "D:\\fake\\db.gnucash", "hostname": None, "pid": None}
LOCKED  = {"status": "locked",
           "message": "Database is locked by GnuCash@HOST (PID 999).",
           "path": "D:\\fake\\db.gnucash", "hostname": "GnuCash@HOST", "pid": 999}


class TestGetDashboardHealthCheck:
    def test_healthy_db_renders_dashboard(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=HEALTHY), \
             patch("bill_processor.web.queue_io.read_queue", return_value=[]), \
             patch("bill_processor.gnucash_db.get_all_vendors", return_value=[]), \
             patch("bill_processor.vendor_manager.VendorManager") as mock_vm, \
             patch("bill_processor.gnucash_db.get_unpaid_bills", return_value=[]), \
             patch("bill_processor.gnucash_db.get_cash_accounts", return_value=[]), \
             patch("bill_processor.gnucash_db.get_checking_accounts", return_value=[]):
            mock_vm.return_value.vendors = {"vendors": {}}
            response = client.get("/")
        assert response.status_code == 200
        assert "Database Unavailable" not in response.text
        assert "GnuCash Bill Processor" in response.text

    def test_missing_db_renders_error_page(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.get("/")
        assert response.status_code == 200
        assert "Database Unavailable" in response.text
        assert MISSING["path"] in response.text

    def test_locked_db_renders_error_page(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=LOCKED):
            response = client.get("/")
        assert response.status_code == 200
        assert "Database Unavailable" in response.text
        assert "GnuCash@HOST" in response.text
        assert "999" in response.text

    def test_missing_db_shows_browse_button(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.get("/")
        assert "Browse for database file" in response.text

    def test_locked_db_does_not_show_browse_button(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=LOCKED):
            response = client.get("/")
        assert "Browse for database file" not in response.text

    def test_error_page_has_refresh_link(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.get("/")
        assert "Refresh" in response.text

    def test_error_page_has_shutdown_button(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.get("/")
        assert "Shut Down" in response.text


class TestDbBrowse:
    def test_returns_path_when_file_selected(self):
        mock_result = MagicMock()
        mock_result.stdout = "D:\\fake\\test.gnucash\n"
        mock_result.returncode = 0
        with patch("bill_processor.web.app.subprocess.run", return_value=mock_result):
            response = client.get("/db/browse")
        assert response.status_code == 200
        data = response.json()
        assert data["path"] == "D:\\fake\\test.gnucash"

    def test_returns_empty_path_when_cancelled(self):
        mock_result = MagicMock()
        mock_result.stdout = "\n"
        mock_result.returncode = 0
        with patch("bill_processor.web.app.subprocess.run", return_value=mock_result):
            response = client.get("/db/browse")
        assert response.status_code == 200
        assert response.json()["path"] == ""

    def test_returns_empty_path_on_subprocess_error(self):
        with patch("bill_processor.web.app.subprocess.run",
                   side_effect=Exception("subprocess failed")):
            response = client.get("/db/browse")
        assert response.status_code == 200
        assert response.json()["path"] == ""

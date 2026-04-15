"""Tests for DB health JSON REST API endpoints."""
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
ACCOUNT_MISSING = {"status": "account_missing",
                   "message": "Required account 'SAMUSE Cash-on-hand' not found in database.",
                   "path": "D:\\fake\\db.gnucash", "hostname": None, "pid": None}


class TestGetDbHealth:
    def test_healthy_db_returns_ok_status(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=HEALTHY):
            response = client.get("/api/db/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_missing_db_returns_missing_status(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.get("/api/db/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "missing"

    def test_locked_db_returns_locked_status(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=LOCKED):
            response = client.get("/api/db/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "locked"
        assert data["hostname"] == "GnuCash@HOST"
        assert data["pid"] == 999

    def test_account_missing_returns_account_missing_status(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=ACCOUNT_MISSING):
            response = client.get("/api/db/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "account_missing"

    def test_response_contains_status_key(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=HEALTHY):
            response = client.get("/api/db/health")
        assert response.status_code == 200
        assert "status" in response.json()

    def test_response_contains_path(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.get("/api/db/health")
        data = response.json()
        assert data["path"] == MISSING["path"]

    def test_response_contains_message(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=HEALTHY):
            response = client.get("/api/db/health")
        data = response.json()
        assert "message" in data


class TestGetApiStatus:
    def test_healthy_db_reports_db_ok_true(self):
        with patch("bill_processor.gnucash_db.test_connection", return_value=True), \
             patch("bill_processor.web.queue_io.read_queue", return_value=[]), \
             patch("bill_processor.gnucash_db.get_all_vendors", return_value=[]), \
             patch("bill_processor.vendor_manager.VendorManager") as mock_vm:
            mock_vm.return_value.vendors = {"vendors": {}, "aliases": {}}
            response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["db_ok"] is True

    def test_unhealthy_db_reports_db_ok_false(self):
        with patch("bill_processor.gnucash_db.test_connection", return_value=False), \
             patch("bill_processor.web.queue_io.read_queue", return_value=[]), \
             patch("bill_processor.gnucash_db.get_all_vendors", return_value=[]), \
             patch("bill_processor.vendor_manager.VendorManager") as mock_vm:
            mock_vm.return_value.vendors = {"vendors": {}, "aliases": {}}
            response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["db_ok"] is False

    def test_response_contains_required_keys(self):
        with patch("bill_processor.gnucash_db.test_connection", return_value=True), \
             patch("bill_processor.web.queue_io.read_queue", return_value=[]), \
             patch("bill_processor.gnucash_db.get_all_vendors", return_value=[]), \
             patch("bill_processor.vendor_manager.VendorManager") as mock_vm:
            mock_vm.return_value.vendors = {"vendors": {}, "aliases": {}}
            response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "vendor_sync" in data
        assert "queued_bills" in data
        assert "db_ok" in data

    def test_queued_bills_count_reflects_queue(self):
        fake_bill = {"_index": 0, "vendor_name": "Test", "amount": 10.0,
                     "memo": "", "date": "2026-01-15", "check_number": ""}
        with patch("bill_processor.gnucash_db.test_connection", return_value=True), \
             patch("bill_processor.web.queue_io.read_queue", return_value=[fake_bill, fake_bill]), \
             patch("bill_processor.gnucash_db.get_all_vendors", return_value=[]), \
             patch("bill_processor.vendor_manager.VendorManager") as mock_vm:
            mock_vm.return_value.vendors = {"vendors": {}, "aliases": {}}
            response = client.get("/api/status")
        assert response.json()["queued_bills"] == 2


class TestDbBrowse:
    def test_returns_path_when_file_selected(self):
        mock_result = MagicMock()
        mock_result.stdout = "D:\\fake\\test.gnucash\n"
        mock_result.returncode = 0
        with patch("bill_processor.web.app.subprocess.run", return_value=mock_result):
            response = client.get("/api/db/browse")
        assert response.status_code == 200
        data = response.json()
        assert data["path"] == "D:\\fake\\test.gnucash"

    def test_returns_empty_path_when_cancelled(self):
        mock_result = MagicMock()
        mock_result.stdout = "\n"
        mock_result.returncode = 0
        with patch("bill_processor.web.app.subprocess.run", return_value=mock_result):
            response = client.get("/api/db/browse")
        assert response.status_code == 200
        assert response.json()["path"] == ""

    def test_returns_empty_path_on_subprocess_error(self):
        with patch("bill_processor.web.app.subprocess.run",
                   side_effect=Exception("subprocess failed")):
            response = client.get("/api/db/browse")
        assert response.status_code == 200
        assert response.json()["path"] == ""


class TestPostDbPath:
    def test_valid_gnucash_file_returns_ok(self, tmp_path):
        fake_db = tmp_path / "real.gnucash"
        fake_db.touch()
        with patch("bill_processor.web.app.settings") as mock_settings:
            response = client.post(
                "/api/db/path",
                json={"path": str(fake_db)},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_nonexistent_file_returns_400(self, tmp_path):
        missing = tmp_path / "nonexistent.gnucash"
        response = client.post(
            "/api/db/path",
            json={"path": str(missing)},
        )
        assert response.status_code == 400

    def test_wrong_extension_returns_400(self, tmp_path):
        wrong = tmp_path / "file.sqlite"
        wrong.touch()
        response = client.post(
            "/api/db/path",
            json={"path": str(wrong)},
        )
        assert response.status_code == 400

    def test_empty_path_returns_400(self):
        response = client.post(
            "/api/db/path",
            json={"path": ""},
        )
        assert response.status_code == 400

    def test_error_response_has_detail(self, tmp_path):
        missing = tmp_path / "nonexistent.gnucash"
        response = client.post(
            "/api/db/path",
            json={"path": str(missing)},
        )
        data = response.json()
        assert "detail" in data

    def test_valid_path_updates_settings(self, tmp_path):
        fake_db = tmp_path / "real.gnucash"
        fake_db.touch()
        from bill_processor.web.app import settings as app_settings
        original_path = app_settings.gnucash_db_path
        try:
            response = client.post("/api/db/path", json={"path": str(fake_db)})
            assert response.status_code == 200
            assert app_settings.gnucash_db_path == fake_db
        finally:
            app_settings.gnucash_db_path = original_path

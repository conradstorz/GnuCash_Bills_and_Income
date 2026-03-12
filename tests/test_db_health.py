"""Tests for check_db_health() in gnucash_db.py."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from bill_processor import gnucash_db, config


def _make_samuse_conn(found: bool):
    """Return a mock context-manager connection whose fetchone returns a row or None."""
    row = {"guid": "a" * 32} if found else None
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    conn = MagicMock()
    conn.execute.return_value = cursor
    conn.__enter__ = lambda s: conn
    conn.__exit__ = MagicMock(return_value=False)
    return conn


class TestCheckDbHealth:
    def test_returns_ok_when_file_exists_and_not_locked(self, tmp_path):
        fake_db = tmp_path / "test.gnucash"
        fake_db.touch()
        with patch("bill_processor.config.GNUCASH_DB_PATH", fake_db), \
             patch("bill_processor.gnucash_db.is_locked_by_others", return_value=(False, None, None)), \
             patch("bill_processor.gnucash_db.get_connection", return_value=_make_samuse_conn(True)):
            result = gnucash_db.check_db_health()
        assert result["status"] == "ok"
        assert result["path"] == str(fake_db)
        assert result["hostname"] is None
        assert result["pid"] is None

    def test_returns_missing_when_file_not_found(self, tmp_path):
        missing = tmp_path / "nonexistent.gnucash"
        with patch("bill_processor.config.GNUCASH_DB_PATH", missing):
            result = gnucash_db.check_db_health()
        assert result["status"] == "missing"
        assert result["path"] == str(missing)
        assert "not found" in result["message"].lower() or "missing" in result["message"].lower()

    def test_returns_locked_when_locked_by_others(self, tmp_path):
        fake_db = tmp_path / "test.gnucash"
        fake_db.touch()
        with patch("bill_processor.config.GNUCASH_DB_PATH", fake_db), \
             patch("bill_processor.gnucash_db.is_locked_by_others",
                   return_value=(True, "GnuCash@DESKTOP-XYZ", 4821)):
            result = gnucash_db.check_db_health()
        assert result["status"] == "locked"
        assert result["hostname"] == "GnuCash@DESKTOP-XYZ"
        assert result["pid"] == 4821
        assert "4821" in result["message"] or "DESKTOP-XYZ" in result["message"]

    def test_returns_account_missing_when_samuse_account_not_found(self, tmp_path):
        fake_db = tmp_path / "test.gnucash"
        fake_db.touch()
        with patch("bill_processor.config.GNUCASH_DB_PATH", fake_db), \
             patch("bill_processor.gnucash_db.is_locked_by_others", return_value=(False, None, None)), \
             patch("bill_processor.gnucash_db.get_connection", return_value=_make_samuse_conn(False)):
            result = gnucash_db.check_db_health()
        assert result["status"] == "account_missing"
        assert config.CASH_ON_HAND_ACCOUNT_NAME in result["message"]
        assert result["hostname"] is None
        assert result["pid"] is None

    def test_missing_check_does_not_call_lock_check(self, tmp_path):
        missing = tmp_path / "nonexistent.gnucash"
        with patch("bill_processor.config.GNUCASH_DB_PATH", missing), \
             patch("bill_processor.gnucash_db.is_locked_by_others") as mock_lock:
            gnucash_db.check_db_health()
        mock_lock.assert_not_called()

    def test_ok_result_contains_path(self, tmp_path):
        fake_db = tmp_path / "test.gnucash"
        fake_db.touch()
        with patch("bill_processor.config.GNUCASH_DB_PATH", fake_db), \
             patch("bill_processor.gnucash_db.is_locked_by_others", return_value=(False, None, None)), \
             patch("bill_processor.gnucash_db.get_connection", return_value=_make_samuse_conn(True)):
            result = gnucash_db.check_db_health()
        assert "path" in result
        assert result["path"] == str(fake_db)

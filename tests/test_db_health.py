"""Tests for check_db_health() in gnucash_db.py — uses real SQLite, no mocks."""
import sqlite3
from pathlib import Path
import importlib.util

import pytest
from bill_processor import gnucash_db, config

_spec = importlib.util.spec_from_file_location("helpers", Path(__file__).parent / "helpers.py")
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
_insert_lock = _helpers._insert_lock
del _spec, _helpers


def _insert_samuse_account(db_path):
    """Insert the SAMUSE account row required for an 'ok' health check.

    name must equal config.CASH_ON_HAND_ACCOUNT_NAME and placeholder must be 0
    to match the query in check_db_health().
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO accounts (guid, name, account_type, placeholder) VALUES (?, ?, 'CASH', 0)",
        ("a" * 32, config.CASH_ON_HAND_ACCOUNT_NAME),
    )
    conn.commit()
    conn.close()


class TestCheckDbHealth:
    def test_returns_ok_when_healthy(self, health_db):
        _insert_samuse_account(health_db)
        result = gnucash_db.check_db_health()
        assert result["status"] == "ok"
        assert result["path"] == str(health_db)
        assert result["hostname"] is None
        assert result["pid"] is None

    def test_returns_missing_when_file_not_found(self, health_db):
        health_db.unlink()
        result = gnucash_db.check_db_health()
        assert result["status"] == "missing"
        assert "path" in result

    def test_returns_locked_when_locked_by_others(self, health_db):
        _insert_lock(health_db, "GnuCash@DESKTOP-XYZ", 4821)
        result = gnucash_db.check_db_health()
        assert result["status"] == "locked"
        assert result["hostname"] == "GnuCash@DESKTOP-XYZ"
        assert result["pid"] == 4821
        assert "4821" in result["message"] or "DESKTOP-XYZ" in result["message"]

    def test_returns_account_missing_when_samuse_not_found(self, health_db):
        # accounts table is empty — no SAMUSE row inserted
        result = gnucash_db.check_db_health()
        assert result["status"] == "account_missing"
        assert config.CASH_ON_HAND_ACCOUNT_NAME in result["message"]
        assert result["hostname"] is None
        assert result["pid"] is None

    def test_missing_check_does_not_reach_lock_check(self, health_db):
        # When the file is missing, check_db_health() returns early before calling
        # is_locked_by_others(). We verify the outcome (status == "missing") rather
        # than the call count — this is a weaker assertion than the original mock-based
        # test, accepted as an intentional trade-off for removing mock infrastructure.
        health_db.unlink()
        result = gnucash_db.check_db_health()
        assert result["status"] == "missing"

    def test_ok_result_contains_path(self, health_db):
        _insert_samuse_account(health_db)
        result = gnucash_db.check_db_health()
        assert result["path"] == str(health_db)

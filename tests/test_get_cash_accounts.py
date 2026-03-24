"""Tests for the DB-querying get_cash_accounts() in gnucash_db.py."""
import sqlite3
import pytest
from unittest.mock import patch, MagicMock
from bill_processor import gnucash_db, config


def _make_fake_conn(rows):
    """Return a mock connection whose execute().fetchall() yields rows."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__iter__ = lambda self: iter(rows)
    conn.execute.return_value = cursor
    conn.__enter__ = lambda self: conn
    conn.__exit__ = MagicMock(return_value=False)
    return conn


def _row(guid, name):
    """Simulate a sqlite3.Row-like dict."""
    return {"guid": guid, "name": name}


class TestGetCashAccounts:
    def test_returns_income_accounts(self):
        rows = [_row("a" * 32, "Service Income")]
        conn = _make_fake_conn(rows)
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            result = gnucash_db.get_cash_accounts()
        assert len(result) == 1
        assert result[0]["name"] == "Service Income"
        assert result[0]["guid"] == "a" * 32

    def test_returns_asset_accounts(self):
        rows = [_row("b" * 32, "Cash on Hand")]
        conn = _make_fake_conn(rows)
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            result = gnucash_db.get_cash_accounts()
        assert any(r["name"] == "Cash on Hand" for r in result)

    def test_returns_empty_list_when_no_accounts(self):
        conn = _make_fake_conn([])
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            result = gnucash_db.get_cash_accounts()
        assert result == []

    def test_queries_income_and_asset_types(self):
        conn = _make_fake_conn([])
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            gnucash_db.get_cash_accounts()
        # Check SQL contains account_type IN clause
        sql = conn.execute.call_args[0][0].upper()
        assert "ACCOUNT_TYPE IN" in sql
        # Check parameters include INCOME and ASSET types
        params = conn.execute.call_args[0][1] if len(conn.execute.call_args[0]) > 1 else ()
        assert config.ACCOUNT_TYPE_INCOME in params
        assert config.ACCOUNT_TYPE_ASSET in params

    def test_excludes_placeholder_accounts(self):
        conn = _make_fake_conn([])
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            gnucash_db.get_cash_accounts()
        sql = conn.execute.call_args[0][0].upper()
        assert "PLACEHOLDER" in sql
        # Verify placeholder parameter is set to FALSE (0)
        params = conn.execute.call_args[0][1] if len(conn.execute.call_args[0]) > 1 else ()
        assert config.PLACEHOLDER_FALSE in params

    def test_result_dicts_have_name_and_guid(self):
        rows = [_row("c" * 32, "Rental Income")]
        conn = _make_fake_conn(rows)
        with patch("bill_processor.gnucash_db.get_connection", return_value=conn):
            result = gnucash_db.get_cash_accounts()
        assert "name" in result[0]
        assert "guid" in result[0]


class TestGetPayableAccounts:
    def test_returns_list_of_dicts(self, db_connection):
        from bill_processor import gnucash_db
        result = gnucash_db.get_payable_accounts()
        assert isinstance(result, list)

    def test_each_item_has_required_keys(self, db_connection):
        from bill_processor import gnucash_db
        result = gnucash_db.get_payable_accounts()
        for item in result:
            assert "guid" in item
            assert "name" in item
            assert "description" in item

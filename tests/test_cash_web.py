"""Tests for cash-on-hand web routes in web/app.py."""

import pytest
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from bill_processor.web.app import app

client = TestClient(app)


class TestCashAddRow:
    def test_returns_200(self):
        with patch("bill_processor.gnucash_db.get_cash_accounts", return_value=[
            {"name": "Service Income", "guid": "a" * 32}
        ]):
            response = client.get("/cash/add-row")
        assert response.status_code == 200

    def test_returns_table_row(self):
        with patch("bill_processor.gnucash_db.get_cash_accounts", return_value=[]):
            response = client.get("/cash/add-row")
        assert "<tr" in response.text
        assert 'name="account_guid"' in response.text
        assert 'name="memo"' in response.text
        assert 'name="amount"' in response.text

    def test_includes_cash_accounts_in_dropdown(self):
        # Patch _get_enabled_cash_accounts directly — the route calls this helper which
        # applies a settings filter on top of get_cash_accounts(), so mocking the lower
        # layer alone is insufficient.
        accounts = [{"name": "My Income", "guid": "b" * 32}]
        with patch("bill_processor.web.app._get_enabled_cash_accounts", return_value=accounts):
            response = client.get("/cash/add-row")
        assert "My Income" in response.text


class TestClientsSearch:
    def test_returns_200(self):
        response = client.get("/clients/search?memo=ali")
        assert response.status_code == 200

    def test_empty_query_returns_empty(self):
        # Route returns {"suggestions": [...]}; empty query returns top memos by design.
        # Mock get_memo_suggestions to isolate from memo_history.json state.
        with patch("bill_processor.web.cash_io.get_memo_suggestions", return_value=[]):
            response = client.get("/clients/search?memo=")
        data = response.json()
        assert data == {"suggestions": []}

    def test_returns_matching_clients(self):
        # Route now uses get_memo_suggestions (memo history), not CLIENTS_PATH (clients.json).
        with patch("bill_processor.web.cash_io.get_memo_suggestions", return_value=["Alice", "Albert"]):
            response = client.get("/clients/search?memo=al")
        data = response.json()
        assert "Alice" in data["suggestions"] or "Albert" in data["suggestions"]
        assert "Bob" not in data["suggestions"]

    def test_clients_datalist_returns_datalist_element(self):
        with patch("bill_processor.web.cash_io.CLIENTS_PATH") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = '{"clients": ["Alice", "Bob"]}'
            response = client.get("/clients/datalist")
        assert response.status_code == 200
        assert '<datalist' in response.text
        assert 'id="client-list"' in response.text
        assert "Alice" in response.text


class TestCashSubmit:
    def test_empty_form_returns_error_message(self):
        with patch("bill_processor.gnucash_db.get_cash_accounts", return_value=[]), \
             patch("bill_processor.gnucash_db.get_checking_accounts", return_value=[]):
            response = client.post("/cash/submit", data={})
        assert response.status_code == 200
        assert "required" in response.text.lower() or "line item" in response.text.lower()

    def test_valid_submission_returns_success(self):
        form_data = {
            "entry_date": "2026-03-09",
            "account_guid": "a" * 32,
            "memo": "Alice",
            "amount": "100.00",
        }
        with patch("bill_processor.gnucash_db.create_cash_entry", return_value="z" * 32), \
             patch("bill_processor.gnucash_db.get_cash_accounts", return_value=[]), \
             patch("bill_processor.gnucash_db.get_checking_accounts", return_value=[]):
            response = client.post("/cash/submit", data=form_data)
        assert response.status_code == 200
        assert "100.00" in response.text or "SAMUSE" in response.text

    def test_locked_db_shows_error_not_crash(self):
        form_data = {
            "entry_date": "2026-03-09",
            "account_guid": "a" * 32,
            "memo": "Alice",
            "amount": "100.00",
        }
        with patch("bill_processor.gnucash_db.create_cash_entry",
                   side_effect=RuntimeError("GnuCash database is locked by GnuCash@HOST (PID 9999)")), \
             patch("bill_processor.gnucash_db.get_cash_accounts", return_value=[]), \
             patch("bill_processor.gnucash_db.get_checking_accounts", return_value=[]):
            response = client.post("/cash/submit", data=form_data)
        assert response.status_code == 200
        assert "locked" in response.text.lower()

    def test_deposit_failure_included_in_success_message(self):
        """Batch succeeds but deposit fails — user sees both outcomes."""
        form_data = {
            "entry_date": "2026-03-09",
            "account_guid": "a" * 32,
            "memo": "Alice",
            "amount": "50.00",
            "deposit_account_guid": "b" * 32,
            "deposit_amount": "30.00",
            "deposit_date": "2026-03-10",
        }
        with patch("bill_processor.gnucash_db.create_cash_entry", return_value="z" * 32), \
             patch("bill_processor.gnucash_db.create_cash_deposit",
                   side_effect=RuntimeError("DB locked")), \
             patch("bill_processor.gnucash_db.get_cash_accounts", return_value=[]), \
             patch("bill_processor.gnucash_db.get_checking_accounts", return_value=[]):
            response = client.post("/cash/submit", data=form_data)
        assert response.status_code == 200
        # Should show success for batch AND deposit error
        text = response.text.lower()
        assert "50.00" in response.text
        assert "failed" in text or "locked" in text

    def test_deposit_success_included_in_message(self):
        """Both batch and deposit succeed."""
        form_data = {
            "entry_date": "2026-03-09",
            "account_guid": "a" * 32,
            "memo": "Alice",
            "amount": "50.00",
            "deposit_account_guid": "b" * 32,
            "deposit_amount": "30.00",
            "deposit_date": "2026-03-10",
        }
        with patch("bill_processor.gnucash_db.create_cash_entry", return_value="z" * 32), \
             patch("bill_processor.gnucash_db.create_cash_deposit", return_value="y" * 32), \
             patch("bill_processor.gnucash_db.get_cash_accounts", return_value=[]), \
             patch("bill_processor.gnucash_db.get_checking_accounts", return_value=[]):
            response = client.post("/cash/submit", data=form_data)
        assert response.status_code == 200
        assert "30.00" in response.text or "deposit" in response.text.lower()

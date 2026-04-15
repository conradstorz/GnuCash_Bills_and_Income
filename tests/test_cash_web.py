"""Tests for cash API routes in web/app.py."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from bill_processor.web.app import app

client = TestClient(app)


class TestMemoSearch:
    def test_returns_200(self):
        response = client.get("/api/memos?q=ali")
        assert response.status_code == 200

    def test_empty_query_returns_suggestions_key(self):
        with patch("bill_processor.web.cash_io.get_memo_suggestions", return_value=[]):
            response = client.get("/api/memos?q=")
        assert response.json() == {"suggestions": []}

    def test_returns_matching_memos(self):
        with patch("bill_processor.web.cash_io.get_memo_suggestions", return_value=["Alice", "Albert"]):
            response = client.get("/api/memos?q=al")
        data = response.json()
        assert "Alice" in data["suggestions"] or "Albert" in data["suggestions"]


class TestCashSubmit:
    def test_empty_entries_returns_422(self):
        response = client.post("/api/cash/submit", json={
            "entry_date": "2026-03-09",
            "entries": [],
        })
        assert response.status_code == 422

    def test_valid_submission_returns_batch_result(self):
        with patch("bill_processor.gnucash_db.create_cash_entry", return_value="z" * 32):
            response = client.post("/api/cash/submit", json={
                "entry_date": "2026-03-09",
                "entries": [{"account_guid": "a" * 32, "memo": "Alice", "amount": 100.0}],
            })
        assert response.status_code == 200
        data = response.json()
        assert data["batch"]["ok"] is True
        assert data["batch"]["total"] == 100.0

    def test_locked_db_returns_500(self):
        with patch("bill_processor.gnucash_db.create_cash_entry",
                   side_effect=RuntimeError("GnuCash database is locked")):
            response = client.post("/api/cash/submit", json={
                "entry_date": "2026-03-09",
                "entries": [{"account_guid": "a" * 32, "memo": "Alice", "amount": 100.0}],
            })
        assert response.status_code == 500
        assert "locked" in response.json()["detail"].lower()

    def test_deposit_failure_included_in_response(self):
        with patch("bill_processor.gnucash_db.create_cash_entry", return_value="z" * 32), \
             patch("bill_processor.gnucash_db.create_cash_deposit",
                   side_effect=RuntimeError("DB locked")):
            response = client.post("/api/cash/submit", json={
                "entry_date": "2026-03-09",
                "entries": [{"account_guid": "a" * 32, "memo": "Alice", "amount": 50.0}],
                "deposit_account_guid": "b" * 32,
                "deposit_amount": 30.0,
                "deposit_date": "2026-03-10",
            })
        assert response.status_code == 200
        data = response.json()
        assert data["batch"]["ok"] is True
        assert data["deposit"]["ok"] is False
        assert "locked" in data["deposit"]["error"].lower()

    def test_deposit_success_included_in_response(self):
        with patch("bill_processor.gnucash_db.create_cash_entry", return_value="z" * 32), \
             patch("bill_processor.gnucash_db.create_cash_deposit", return_value="y" * 32):
            response = client.post("/api/cash/submit", json={
                "entry_date": "2026-03-09",
                "entries": [{"account_guid": "a" * 32, "memo": "Alice", "amount": 50.0}],
                "deposit_account_guid": "b" * 32,
                "deposit_amount": 30.0,
                "deposit_date": "2026-03-10",
            })
        assert response.status_code == 200
        data = response.json()
        assert data["batch"]["ok"] is True
        assert data["deposit"]["ok"] is True


class TestAddressLookup:
    def test_returns_candidates_and_message(self, monkeypatch):
        import bill_processor.web.app as web_app
        monkeypatch.setattr(web_app.addr_lookup, "lookup_google_places", lambda q, **kw: [])
        monkeypatch.setattr(web_app.addr_lookup, "lookup_openstreetmap", lambda q, **kw: [])
        response = client.post("/api/vendors/lookup-address", json={"vendor_name": "Acme Electric"})
        assert response.status_code == 200
        data = response.json()
        assert "candidates" in data
        assert "message" in data
        assert isinstance(data["candidates"], list)

    def test_combines_city_and_zip_in_query(self, monkeypatch):
        import bill_processor.web.app as web_app
        captured = []
        monkeypatch.setattr(web_app.addr_lookup, "lookup_google_places",
                            lambda q, **kw: captured.append(q) or [])
        monkeypatch.setattr(web_app.addr_lookup, "lookup_openstreetmap",
                            lambda q, **kw: [])
        client.post("/api/vendors/lookup-address", json={
            "display_name": "Kroger",
            "addr_city": "Cincinnati",
            "addr_zip": "45202",
        })
        assert captured == ["Kroger Cincinnati 45202"]

    def test_skips_empty_refinement_fields(self, monkeypatch):
        import bill_processor.web.app as web_app
        captured = []
        monkeypatch.setattr(web_app.addr_lookup, "lookup_google_places",
                            lambda q, **kw: captured.append(q) or [])
        monkeypatch.setattr(web_app.addr_lookup, "lookup_openstreetmap",
                            lambda q, **kw: [])
        client.post("/api/vendors/lookup-address", json={
            "display_name": "Kroger",
            "addr_city": "",
            "addr_zip": "45202",
        })
        assert captured == ["Kroger 45202"]

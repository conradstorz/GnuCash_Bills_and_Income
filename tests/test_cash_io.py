"""Tests for web/cash_io.py client list management."""
import json
import pytest
from bill_processor.web import cash_io


def test_read_clients_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(cash_io, "CLIENTS_PATH", tmp_path / "nonexistent.json")
    assert cash_io.read_clients() == []


def test_read_clients_returns_sorted(tmp_path, monkeypatch):
    f = tmp_path / "clients.json"
    f.write_text(json.dumps({"clients": ["Zara", "Alice", "Bob"]}))
    monkeypatch.setattr(cash_io, "CLIENTS_PATH", f)
    assert cash_io.read_clients() == ["Alice", "Bob", "Zara"]


def test_search_clients_starts_with(tmp_path, monkeypatch):
    f = tmp_path / "clients.json"
    f.write_text(json.dumps({"clients": ["Alice Smith", "Alice Jones", "Bob"]}))
    monkeypatch.setattr(cash_io, "CLIENTS_PATH", f)
    result = cash_io.search_clients("ali")
    assert "Alice Smith" in result
    assert "Alice Jones" in result
    assert "Bob" not in result


def test_search_clients_empty_query(tmp_path, monkeypatch):
    f = tmp_path / "clients.json"
    f.write_text(json.dumps({"clients": ["Alice"]}))
    monkeypatch.setattr(cash_io, "CLIENTS_PATH", f)
    assert cash_io.search_clients("") == []


def test_search_clients_contains_fallback(tmp_path, monkeypatch):
    f = tmp_path / "clients.json"
    f.write_text(json.dumps({"clients": ["Bob Smith", "Alice Bob"]}))
    monkeypatch.setattr(cash_io, "CLIENTS_PATH", f)
    result = cash_io.search_clients("bob")
    # "Bob Smith" starts with "bob", "Alice Bob" contains "bob"
    assert result[0] == "Bob Smith"
    assert "Alice Bob" in result

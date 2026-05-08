"""Tests for web/bill_account_resolver.py."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from bill_processor.web.bill_account_resolver import BillAccountResolver


@pytest.fixture
def registry_path(tmp_path):
    data = {
        "presets": {
            "utility": {
                "expense_acct":  {"name": "Expenses:Utilities", "guid": "exp-1"},
                "checking_acct": {"name": "Assets:Checking",    "guid": "chk-1"},
                "payables_acct": {"name": "Liabilities:AP",     "guid": "ap-1"},
            }
        },
        "labels": {
            "main_checking": {"name": "Assets:Checking",        "guid": "chk-1"},
            "ap":            {"name": "Liabilities:AP",         "guid": "ap-1"},
            "gas_expense":   {"name": "Expenses:Utilities:Gas", "guid": "gas-1"},
        },
    }
    p = tmp_path / "labels.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def resolver(registry_path):
    return BillAccountResolver(registry_path=registry_path)


class TestResolveAllEmpty:
    def test_returns_none_when_all_empty(self, resolver):
        assert resolver.resolve("", "", "", "") is None


class TestResolvePreset:
    def test_preset_resolves_all_three_guids(self, resolver):
        result = resolver.resolve("utility", "", "", "")
        assert result == {"expense_guid": "exp-1", "checking_guid": "chk-1", "ap_guid": "ap-1"}

    def test_unknown_bill_type_raises_value_error(self, resolver):
        with pytest.raises(ValueError, match="Unknown bill type: 'foo'"):
            resolver.resolve("foo", "", "", "")


class TestResolveOverride:
    def test_label_override_replaces_preset_account(self, resolver):
        result = resolver.resolve("utility", "gas_expense", "", "")
        assert result["expense_guid"] == "gas-1"
        assert result["checking_guid"] == "chk-1"

    def test_bare_name_override_triggers_db_lookup(self, resolver):
        with patch("bill_processor.gnucash_db.get_account_by_name") as mock:
            mock.return_value = {"guid": "db-guid", "name": "Expenses:Custom"}
            result = resolver.resolve("utility", "Expenses:Custom", "", "")
        assert result["expense_guid"] == "db-guid"

    def test_unknown_label_without_preset_triggers_db_lookup(self, resolver):
        with patch("bill_processor.gnucash_db.get_account_by_name") as mock:
            mock.return_value = {"guid": "db-guid2", "name": "Assets:Other"}
            result = resolver.resolve("", "unknown_label", "main_checking", "ap")
        assert result["expense_guid"] == "db-guid2"


class TestResolveNoPreset:
    def test_all_labels_no_preset(self, resolver):
        result = resolver.resolve("", "gas_expense", "main_checking", "ap")
        assert result == {"expense_guid": "gas-1", "checking_guid": "chk-1", "ap_guid": "ap-1"}

    def test_missing_account_raises_value_error(self, resolver):
        with pytest.raises(ValueError, match="expense_acct"):
            resolver.resolve("", "", "main_checking", "ap")


class TestMissingGuid:
    def test_empty_guid_in_preset_triggers_db_lookup(self, tmp_path):
        data = {
            "presets": {
                "noguids": {
                    "expense_acct":  {"name": "Expenses:Test", "guid": ""},
                    "checking_acct": {"name": "Assets:Test",   "guid": ""},
                    "payables_acct": {"name": "Liabilities:AP","guid": ""},
                }
            },
            "labels": {},
        }
        p = tmp_path / "labels.json"
        p.write_text(json.dumps(data))
        r = BillAccountResolver(registry_path=p)
        with patch("bill_processor.gnucash_db.get_account_by_name") as mock:
            mock.return_value = {"guid": "looked-up", "name": "..."}
            result = r.resolve("noguids", "", "", "")
        assert result["expense_guid"] == "looked-up"

    def test_db_lookup_failure_raises_value_error(self, tmp_path):
        data = {
            "presets": {
                "bad": {
                    "expense_acct":  {"name": "Expenses:Missing", "guid": ""},
                    "checking_acct": {"name": "Assets:Missing",   "guid": ""},
                    "payables_acct": {"name": "Liabilities:AP",   "guid": ""},
                }
            },
            "labels": {},
        }
        p = tmp_path / "labels.json"
        p.write_text(json.dumps(data))
        r = BillAccountResolver(registry_path=p)
        with patch("bill_processor.gnucash_db.get_account_by_name", return_value=None):
            with pytest.raises(ValueError, match="Account not found"):
                r.resolve("bad", "", "", "")


class TestSyncGuids:
    def test_sync_populates_missing_guids(self, tmp_path):
        data = {
            "presets": {
                "utility": {
                    "expense_acct":  {"name": "Expenses:Utilities", "guid": ""},
                    "checking_acct": {"name": "Assets:Checking",    "guid": "chk-1"},
                    "payables_acct": {"name": "Liabilities:AP",     "guid": "ap-1"},
                }
            },
            "labels": {
                "gas": {"name": "Expenses:Gas", "guid": ""},
            },
        }
        p = tmp_path / "labels.json"
        p.write_text(json.dumps(data))
        r = BillAccountResolver(registry_path=p)

        def fake_lookup(name):
            return {"guid": f"synced-{name.replace(':', '-')}", "name": name}

        with patch("bill_processor.gnucash_db.get_account_by_name", side_effect=fake_lookup):
            report = r.sync_guids()

        saved = json.loads(p.read_text())
        assert saved["presets"]["utility"]["expense_acct"]["guid"] == "synced-Expenses-Utilities"
        assert saved["labels"]["gas"]["guid"] == "synced-Expenses-Gas"
        assert report["updated"] >= 2
        assert report["failed"] == []

    def test_sync_records_failures(self, tmp_path):
        data = {
            "presets": {
                "bad": {
                    "expense_acct":  {"name": "Expenses:Missing", "guid": ""},
                    "checking_acct": {"name": "Assets:Check",     "guid": "ok"},
                    "payables_acct": {"name": "Liabilities:AP",   "guid": "ok"},
                }
            },
            "labels": {},
        }
        p = tmp_path / "labels.json"
        p.write_text(json.dumps(data))
        r = BillAccountResolver(registry_path=p)
        with patch("bill_processor.gnucash_db.get_account_by_name", return_value=None):
            report = r.sync_guids()
        assert len(report["failed"]) >= 1
        assert "Expenses:Missing" in report["failed"][0]["name"]

"""Tests for main.py — CLI bill processing workflow."""
import pytest
import sqlite3
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import main
from bill_processor import gnucash_db


def _make_mock_vm(vendor_guid, expense_guid, display_name="Test Vendor"):
    """Return a VendorManager mock wired up for a success path."""
    mock_vm = MagicMock()
    mock_vm.find_vendor.return_value = (
        {"gnucash_guid": vendor_guid, "display_name": display_name},
        "exact",
    )
    mock_vm.get_or_create_expense_account.return_value = expense_guid
    mock_vm.vendors = {"vendors": {}, "aliases": {}}
    return mock_vm


class TestProcessBill:
    def test_success_returns_true(self, db_connection, test_vendor_guid, test_accounts):
        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])
        with patch("main.confirm_proceed", return_value=True):
            result = main.process_bill(
                mock_vm,
                "Test Vendor",
                100.00,
                "test memo",
                date.today(),
                test_accounts["checking_account"],
            )
        assert result is True

    def test_check_number_passed_to_pay_bill(self, db_connection, test_vendor_guid, test_accounts):
        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])
        captured = {}
        original = gnucash_db.pay_bill

        def capturing(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        with patch("main.confirm_proceed", return_value=True):
            with patch.object(gnucash_db, "pay_bill", side_effect=capturing):
                main.process_bill(
                    mock_vm,
                    "Test Vendor",
                    100.00,
                    "test memo",
                    date.today(),
                    test_accounts["checking_account"],
                    check_number="9999",
                )
        assert captured.get("check_number") == "9999"

    def test_fuzzy_match_user_confirms_alias(self, db_connection, test_vendor_guid, test_accounts):
        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])
        mock_vm.find_vendor.return_value = (
            {"gnucash_guid": test_vendor_guid, "display_name": "Test Vendor"},
            "fuzzy",
        )
        vendor_key = "test_vendor"
        mock_vm.vendors = {
            "vendors": {vendor_key: {"gnucash_guid": test_vendor_guid, "display_name": "Test Vendor"}},
            "aliases": {},
        }
        with patch("main.confirm_proceed", return_value=True):
            result = main.process_bill(
                mock_vm,
                "Tset Vendor",
                100.00,
                "memo",
                date.today(),
                test_accounts["checking_account"],
            )
        assert result is True
        mock_vm.add_alias.assert_called_once()

    def test_fuzzy_match_user_declines_alias(self, db_connection, test_vendor_guid, test_accounts):
        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])
        mock_vm.find_vendor.return_value = (
            {"gnucash_guid": test_vendor_guid, "display_name": "Test Vendor"},
            "fuzzy",
        )
        mock_vm.vendors = {
            "vendors": {"test_vendor": {"gnucash_guid": test_vendor_guid, "display_name": "Test Vendor"}},
            "aliases": {},
        }
        with patch("main.confirm_proceed", return_value=False):
            result = main.process_bill(
                mock_vm,
                "Tset Vendor",
                100.00,
                "memo",
                date.today(),
                test_accounts["checking_account"],
            )
        assert result is True
        mock_vm.add_alias.assert_not_called()

    def test_vendor_not_found_user_skips_returns_false(self):
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (None, "not_found")
        with patch("main.confirm_proceed", return_value=False):
            result = main.process_bill(
                mock_vm,
                "Unknown Vendor",
                50.00,
                "memo",
                date.today(),
                "checking_guid_placeholder",
            )
        assert result is False

    def test_vendor_not_found_user_creates_returns_true(self, db_connection, test_vendor_guid, test_accounts):
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (None, "not_found")
        new_vendor = {"gnucash_guid": test_vendor_guid, "display_name": "New Vendor"}
        mock_vm.create_new_vendor.return_value = new_vendor
        mock_vm.get_or_create_expense_account.return_value = test_accounts["expense_account"]

        confirm_responses = iter([True, True])
        with patch("main.confirm_proceed", side_effect=lambda _: next(confirm_responses)):
            result = main.process_bill(
                mock_vm,
                "New Vendor",
                75.00,
                "memo",
                date.today(),
                test_accounts["checking_account"],
            )
        assert result is True
        mock_vm.create_new_vendor.assert_called_once_with("New Vendor")


class TestProcessInputFile:
    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            main.process_input_file(tmp_path / "nonexistent.txt")

    def test_empty_file_returns_zero_counts(self, tmp_path):
        input_file = tmp_path / "bills.txt"
        input_file.write_text("")
        result = main.process_input_file(input_file)
        assert result == {"total": 0, "success": 0, "failed": 0, "skipped": 0}

    def test_user_cancels_at_confirm_returns_skipped(self, tmp_path):
        input_file = tmp_path / "bills.txt"
        input_file.write_text("Acme Corp, 100.00, supplies, 2026-01-15\n")
        with patch("main.confirm_proceed", return_value=False):
            result = main.process_input_file(input_file)
        assert result["skipped"] == 1
        assert result["success"] == 0

    def test_single_bill_processes_successfully(
        self, db_connection, test_vendor_guid, test_accounts, tmp_path
    ):
        input_file = tmp_path / "bills.txt"
        input_file.write_text("Test Vendor, 100.00, test memo, 2026-01-15\n")

        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])

        with patch("main.VendorManager", return_value=mock_vm):
            with patch("main.confirm_proceed", return_value=True):
                with patch("builtins.input", return_value="1"):
                    with patch.object(
                        gnucash_db,
                        "get_checking_accounts",
                        return_value=[{"name": "Checking", "guid": test_accounts["checking_account"]}],
                    ):
                        result = main.process_input_file(input_file)

        assert result == {"total": 1, "success": 1, "failed": 0, "skipped": 0}

    def test_check_number_from_file_reaches_pay_bill(
        self, db_connection, test_vendor_guid, test_accounts, tmp_path
    ):
        input_file = tmp_path / "bills.txt"
        input_file.write_text("Test Vendor, 100.00, test memo, 2026-01-15, 4242\n")

        mock_vm = _make_mock_vm(test_vendor_guid, test_accounts["expense_account"])
        captured = {}
        original = gnucash_db.pay_bill

        def capturing(**kwargs):
            captured.update(kwargs)
            return original(**kwargs)

        with patch("main.VendorManager", return_value=mock_vm):
            with patch("main.confirm_proceed", return_value=True):
                with patch("builtins.input", return_value="1"):
                    with patch.object(
                        gnucash_db,
                        "get_checking_accounts",
                        return_value=[{"name": "Checking", "guid": test_accounts["checking_account"]}],
                    ):
                        with patch.object(gnucash_db, "pay_bill", side_effect=capturing):
                            main.process_input_file(input_file)

        assert captured.get("check_number") == "4242"

    def test_user_cancels_account_selection_returns_skipped(self, tmp_path):
        input_file = tmp_path / "bills.txt"
        input_file.write_text("Acme Corp, 100.00, supplies, 2026-01-15\n")

        with patch("main.confirm_proceed", return_value=True):
            with patch("builtins.input", side_effect=KeyboardInterrupt):
                with patch.object(
                    gnucash_db,
                    "get_checking_accounts",
                    return_value=[{"name": "Checking", "guid": "abc"}],
                ):
                    result = main.process_input_file(input_file)

        assert result["skipped"] == 1
        assert result["success"] == 0

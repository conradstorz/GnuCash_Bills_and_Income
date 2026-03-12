"""
Tests for cash-on-hand entry functions in gnucash_db.py.
"""
import pytest
import sqlite3
from datetime import date, timedelta
from bill_processor import gnucash_db, config


class TestGetSamuseAccountGuid:
    def test_returns_string_guid(self, db_connection):
        guid = gnucash_db.get_samuse_account_guid()
        assert isinstance(guid, str)
        assert len(guid) == 32
        assert all(c in '0123456789abcdef' for c in guid)

    def test_account_exists_in_db(self, db_connection):
        guid = gnucash_db.get_samuse_account_guid()
        with gnucash_db.get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT guid, name FROM accounts WHERE guid = ?", (guid,)
            ).fetchone()
        assert row is not None

    def test_raises_if_account_missing(self, db_connection, monkeypatch):
        monkeypatch.setattr(config, "CASH_ON_HAND_ACCOUNT_NAME", "NONEXISTENT_XYZ")
        gnucash_db._samuse_guid_cache = None
        with pytest.raises(ValueError, match="SAMUSE|NONEXISTENT"):
            gnucash_db.get_samuse_account_guid()
        gnucash_db._samuse_guid_cache = None


class TestCreateCashEntry:
    def test_creates_transaction(self, db_connection, test_accounts, cash_entry_data):
        with gnucash_db.get_connection(readonly=True) as conn:
            before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            after = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert after == before + 1

    def test_creates_correct_number_of_splits(self, db_connection, test_accounts, cash_entry_data):
        n = len(cash_entry_data["line_items"])
        with gnucash_db.get_connection(readonly=True) as conn:
            before = conn.execute("SELECT COUNT(*) FROM splits").fetchone()[0]
        gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            after = conn.execute("SELECT COUNT(*) FROM splits").fetchone()[0]
        assert after == before + n + 1

    def test_splits_sum_to_zero(self, db_connection, test_accounts, cash_entry_data):
        txn_guid = gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            rows = conn.execute(
                "SELECT value_num FROM splits WHERE tx_guid = ?", (txn_guid,)
            ).fetchall()
        total = sum(r[0] if isinstance(r, tuple) else r["value_num"] for r in rows)
        assert total == 0

    def test_samuse_split_equals_sum_of_line_items(self, db_connection, test_accounts, cash_entry_data):
        expected = int(round(sum(i["amount"] for i in cash_entry_data["line_items"]) * 100))
        samuse_guid = gnucash_db.get_samuse_account_guid()
        txn_guid = gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT value_num FROM splits WHERE tx_guid = ? AND account_guid = ?",
                (txn_guid, samuse_guid)
            ).fetchone()
        assert row is not None
        val = row[0] if isinstance(row, tuple) else row["value_num"]
        assert val == expected

    def test_line_item_splits_correct_values(self, db_connection, test_accounts, cash_entry_data):
        samuse_guid = gnucash_db.get_samuse_account_guid()
        txn_guid = gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            splits = conn.execute(
                "SELECT account_guid, value_num, memo FROM splits WHERE tx_guid = ?",
                (txn_guid,)
            ).fetchall()
        def val(r, key, idx): return r[idx] if isinstance(r, tuple) else r[key]
        split_map = {val(s, "account_guid", 0): s for s in splits if val(s, "account_guid", 0) != samuse_guid}
        for item in cash_entry_data["line_items"]:
            expected_cents = int(round(-item["amount"] * 100))
            s = split_map.get(item["account_guid"])
            assert s is not None
            assert val(s, "value_num", 1) == expected_cents

    def test_returns_transaction_guid(self, db_connection, test_accounts, cash_entry_data):
        result = gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        assert isinstance(result, str)
        assert len(result) == 32

    def test_raises_on_empty_line_items(self, db_connection):
        with pytest.raises(ValueError, match="line_items|empty"):
            gnucash_db.create_cash_entry(
                entry_date=date.today(),
                line_items=[],
                description="Empty",
            )


class TestCreateCashDeposit:
    def test_creates_transaction(self, db_connection, test_accounts):
        with gnucash_db.get_connection(readonly=True) as conn:
            before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        gnucash_db.create_cash_deposit(
            deposit_date=date.today() + timedelta(days=1),
            bank_account_guid=test_accounts["checking_account"],
            amount=75.00,
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            after = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert after == before + 1

    def test_creates_exactly_two_splits(self, db_connection, test_accounts):
        with gnucash_db.get_connection(readonly=True) as conn:
            before = conn.execute("SELECT COUNT(*) FROM splits").fetchone()[0]
        gnucash_db.create_cash_deposit(
            deposit_date=date.today() + timedelta(days=1),
            bank_account_guid=test_accounts["checking_account"],
            amount=75.00,
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            after = conn.execute("SELECT COUNT(*) FROM splits").fetchone()[0]
        assert after == before + 2

    def test_splits_sum_to_zero(self, db_connection, test_accounts):
        txn_guid = gnucash_db.create_cash_deposit(
            deposit_date=date.today() + timedelta(days=1),
            bank_account_guid=test_accounts["checking_account"],
            amount=75.00,
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            rows = conn.execute(
                "SELECT value_num FROM splits WHERE tx_guid = ?", (txn_guid,)
            ).fetchall()
        total = sum(r[0] if isinstance(r, tuple) else r["value_num"] for r in rows)
        assert total == 0

    def test_samuse_split_is_negative(self, db_connection, test_accounts):
        samuse_guid = gnucash_db.get_samuse_account_guid()
        txn_guid = gnucash_db.create_cash_deposit(
            deposit_date=date.today() + timedelta(days=1),
            bank_account_guid=test_accounts["checking_account"],
            amount=75.00,
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT value_num FROM splits WHERE tx_guid = ? AND account_guid = ?",
                (txn_guid, samuse_guid)
            ).fetchone()
        assert row is not None
        val = row[0] if isinstance(row, tuple) else row["value_num"]
        assert val == -7500

    def test_raises_on_zero_amount(self, db_connection, test_accounts):
        with pytest.raises(ValueError, match="amount|positive"):
            gnucash_db.create_cash_deposit(
                deposit_date=date.today(),
                bank_account_guid=test_accounts["checking_account"],
                amount=0.0,
            )

    def test_raises_on_negative_amount(self, db_connection, test_accounts):
        with pytest.raises(ValueError, match="amount|positive"):
            gnucash_db.create_cash_deposit(
                deposit_date=date.today(),
                bank_account_guid=test_accounts["checking_account"],
                amount=-50.0,
            )

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
    def _splits_for(self, txn_guid):
        with gnucash_db.get_connection(readonly=True) as conn:
            rows = conn.execute(
                "SELECT account_guid, value_num, memo FROM splits WHERE tx_guid = ?",
                (txn_guid,),
            ).fetchall()
        out = []
        for r in rows:
            if isinstance(r, tuple):
                out.append({"account_guid": r[0], "value_num": r[1], "memo": r[2]})
            else:
                out.append({"account_guid": r["account_guid"], "value_num": r["value_num"], "memo": r["memo"]})
        return out

    def test_creates_one_transaction_per_row(self, db_connection, test_accounts, cash_entry_data):
        n = len(cash_entry_data["line_items"])
        with gnucash_db.get_connection(readonly=True) as conn:
            before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            after = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert after == before + n

    def test_creates_two_splits_per_row(self, db_connection, test_accounts, cash_entry_data):
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
        assert after == before + 2 * n

    def test_returns_list_of_guids(self, db_connection, test_accounts, cash_entry_data):
        result = gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        assert isinstance(result, list)
        assert len(result) == len(cash_entry_data["line_items"])
        for guid in result:
            assert isinstance(guid, str)
            assert len(guid) == 32
            assert all(c in "0123456789abcdef" for c in guid)

    def test_each_transaction_balances_with_two_splits(self, db_connection, test_accounts, cash_entry_data):
        guids = gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        for guid in guids:
            splits = self._splits_for(guid)
            assert len(splits) == 2
            assert sum(s["value_num"] for s in splits) == 0

    def test_each_transaction_has_samuse_and_row_account(self, db_connection, test_accounts, cash_entry_data):
        samuse_guid = gnucash_db.get_samuse_account_guid()
        guids = gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        for item, guid in zip(cash_entry_data["line_items"], guids):
            splits = self._splits_for(guid)
            by_acct = {s["account_guid"]: s for s in splits}
            expected_cents = int(round(item["amount"] * 100))
            assert samuse_guid in by_acct
            assert by_acct[samuse_guid]["value_num"] == expected_cents
            assert item["account_guid"] in by_acct
            assert by_acct[item["account_guid"]]["value_num"] == -expected_cents

    def test_transaction_description_is_row_memo(self, db_connection, test_accounts, cash_entry_data):
        guids = gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        for item, guid in zip(cash_entry_data["line_items"], guids):
            with gnucash_db.get_connection(readonly=True) as conn:
                row = conn.execute(
                    "SELECT description FROM transactions WHERE guid = ?", (guid,)
                ).fetchone()
            desc = row[0] if isinstance(row, tuple) else row["description"]
            assert desc == item["memo"]

    def test_blank_memo_falls_back_to_default_description(self, db_connection, test_accounts):
        line_items = [{"account_guid": test_accounts["expense_account"], "memo": "   ", "amount": 12.00}]
        guids = gnucash_db.create_cash_entry(
            entry_date=date.today(),
            line_items=line_items,
            description="",
        )
        with gnucash_db.get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT description FROM transactions WHERE guid = ?", (guids[0],)
            ).fetchone()
        desc = row[0] if isinstance(row, tuple) else row["description"]
        assert desc == config.DEFAULT_MEMO

    def test_transfer_row_transaction_is_isolated(self, db_connection, test_accounts):
        # Mixed session: two revenue rows plus one "changer" transfer row.
        # The changer row's transaction must contain ONLY the changer account
        # and SAMUSE Cash-on-hand — no revenue splits.
        samuse_guid = gnucash_db.get_samuse_account_guid()
        changer_guid = test_accounts["ap_account"]
        income_guid = test_accounts["expense_account"]
        line_items = [
            {"account_guid": income_guid, "memo": "Machine A", "amount": 100.00},
            {"account_guid": income_guid, "memo": "Machine B", "amount": 120.00},
            {"account_guid": changer_guid, "memo": "Changer refill", "amount": -40.00},
        ]
        guids = gnucash_db.create_cash_entry(
            entry_date=date.today(),
            line_items=line_items,
            description="",
        )
        changer_txn = guids[2]
        splits = self._splits_for(changer_txn)
        accounts = {s["account_guid"] for s in splits}
        assert accounts == {samuse_guid, changer_guid}
        assert sum(s["value_num"] for s in splits) == 0

    def test_supports_negative_amount_row(self, db_connection, test_accounts):
        samuse_guid = gnucash_db.get_samuse_account_guid()
        line_items = [{"account_guid": test_accounts["ap_account"], "memo": "Cash out", "amount": -20.00}]
        guids = gnucash_db.create_cash_entry(
            entry_date=date.today(),
            line_items=line_items,
            description="",
        )
        splits = self._splits_for(guids[0])
        by_acct = {s["account_guid"]: s for s in splits}
        assert by_acct[samuse_guid]["value_num"] == -2000
        assert by_acct[test_accounts["ap_account"]]["value_num"] == 2000

    def test_raises_on_empty_line_items(self, db_connection):
        with pytest.raises(ValueError, match="line_items|empty"):
            gnucash_db.create_cash_entry(
                entry_date=date.today(),
                line_items=[],
                description="Empty",
            )

    def test_raises_when_database_locked(self, monkeypatch):
        monkeypatch.setattr(gnucash_db, "is_locked_by_others", lambda: (True, "HOST1", 4242))
        with pytest.raises(RuntimeError, match="locked"):
            gnucash_db.create_cash_entry(
                entry_date=date.today(),
                line_items=[{"account_guid": "x" * 32, "memo": "A", "amount": 10.0}],
                description="Locked DB",
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

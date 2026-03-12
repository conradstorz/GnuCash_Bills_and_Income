# Cash-on-Hand Entry Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a right-side cash-on-hand batch entry panel to the web dashboard that creates multi-split GnuCash transactions against the `SAMUSE Cash-on-hand` account, plus an optional independent deposit transaction.

**Architecture:** New `gnucash_db.py` functions (`create_cash_entry`, `create_cash_deposit`, `get_samuse_account_guid`) follow existing patterns exactly — GUID generation, amount-as-cents, write verification, and mandatory lock checking before any write. New FastAPI routes + HTMX partials mirror the bills side. Dashboard layout changes from single-column to split-screen (bills left, cash right).

**Tech Stack:** Python 3.10+, FastAPI, Jinja2, HTMX, SQLite3, pytest, loguru

**Design doc:** `docs/plans/2026-03-09-cash-on-hand-entry-design.md`

---

## CRITICAL RULES — Read Before Every Task

1. **Lock check before every DB write.** Call `is_locked_by_others()` first. If `locked=True`, raise a descriptive error — do NOT write, do NOT clear the lock.
2. **Verify every insert.** Call `verify_record_exists(table, guid)` after every INSERT. Let `WriteVerificationError` propagate.
3. **Amounts as cents.** `value_num = int(amount * 100)`, `value_denom = 100`. Never store floats.
4. **SAMUSE split is auto-calculated.** `samuse_value_num = int(sum(amounts) * 100)`. Users never enter it.
5. **Each line item split is the negative of its entered amount.** `split_value_num = int(-amount * 100)`.
6. **Transaction must balance.** All split `value_num` values must sum to zero. Verify before inserting.
7. **Use `get_connection(readonly=False)`** for any write operation.
8. **Use `format_gnucash_date(dt, include_time=True)`** for all date fields.
9. **Use `format_gnucash_timestamp()`** for `enter_date`.

---

## Task 1: Create Data Files

**Files:**
- Create: `data/clients.json`
- Create: `data/cash_accounts.json`

**Step 1: Read config.py to confirm the `data/` path**

```python
# From config.py:
# PROJECT_ROOT = Path(r"D:\Users\Conrad\Documents\GnuCash\bill_processor")
# VENDOR_DB_PATH = PROJECT_ROOT / "data" / "vendor_database.json"
# NOTE: data/ files live under PROJECT_ROOT, not the code repo root.
# Add these constants to config.py:
CLIENTS_PATH = PROJECT_ROOT / "data" / "clients.json"
CASH_ACCOUNTS_PATH = PROJECT_ROOT / "data" / "cash_accounts.json"
```

**Step 2: Add constants to config.py**

Open `config.py`. After the `VENDOR_DATABASE_PATH` line, add:

```python
# Client name list for cash entry memo autocomplete
CLIENTS_PATH = PROJECT_ROOT / "data" / "clients.json"

# Cash/income accounts available in the cash entry dropdown
CASH_ACCOUNTS_PATH = PROJECT_ROOT / "data" / "cash_accounts.json"
```

**Step 3: Create clients.json**

Create `data/clients.json` (under PROJECT_ROOT, not repo root):

```json
{
  "clients": []
}
```

**Step 4: Create cash_accounts.json**

Create `data/cash_accounts.json`:

```json
{
  "accounts": []
}
```

> **Note for user:** Populate `cash_accounts.json` with the 5–10 accounts before using the feature. Each entry needs `name` (display name) and `guid` (32-char hex from GnuCash). Use `columbo.py` or the GnuCash SQLite DB browser to find account GUIDs. Format:
> ```json
> {"accounts": [{"name": "Service Income", "guid": "abcdef1234567890abcdef1234567890"}]}
> ```

**Step 5: Commit**

```bash
git add config.py data/clients.json data/cash_accounts.json
git commit -m "feat: add data files and config constants for cash-on-hand entry"
```

---

## Task 2: Write Failing Tests for gnucash_db Cash Functions

**Files:**
- Create: `tests/test_cash_entry.py`
- Read first: `tests/conftest.py`, `tests/test_bill_workflow.py` (for fixture patterns)

**Step 1: Write the failing tests**

Create `tests/test_cash_entry.py`:

```python
"""
Tests for cash-on-hand entry functions in gnucash_db.py.

These tests use a temporary copy of the real GnuCash database (via the
test_db_path fixture from conftest.py). All tests verify that:
- Transactions and splits are created with correct values
- All splits in a transaction sum to zero
- WriteVerificationError is raised on verification failure
- Lock checks are honored
"""

import pytest
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import gnucash_db


class TestGetSamuseAccountGuid:
    """Tests for get_samuse_account_guid()."""

    def test_returns_string_guid(self, db_connection):
        """Should return a 32-char hex GUID string."""
        guid = gnucash_db.get_samuse_account_guid()
        assert isinstance(guid, str)
        assert len(guid) == 32
        assert all(c in '0123456789abcdef' for c in guid)

    def test_account_exists_in_db(self, db_connection):
        """The returned GUID must exist in the accounts table."""
        guid = gnucash_db.get_samuse_account_guid()
        with gnucash_db.get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT guid, name FROM accounts WHERE guid = ?", (guid,)
            ).fetchone()
        assert row is not None, f"GUID {guid} not found in accounts"
        assert "SAMUSE" in row["name"].upper() or "CASH" in row["name"].upper()

    def test_raises_if_account_missing(self, db_connection, monkeypatch):
        """Should raise ValueError if SAMUSE Cash-on-hand account not found."""
        # Patch the account name so it won't be found
        monkeypatch.setattr(gnucash_db, "SAMUSE_ACCOUNT_NAME", "NONEXISTENT_ACCOUNT_XYZ")
        # Clear the cache so the patched name is used
        gnucash_db._samuse_guid_cache = None
        with pytest.raises(ValueError, match="SAMUSE"):
            gnucash_db.get_samuse_account_guid()
        # Restore cache
        gnucash_db._samuse_guid_cache = None


class TestCreateCashEntry:
    """Tests for create_cash_entry()."""

    def test_creates_transaction(self, db_connection, test_accounts, cash_entry_data):
        """Should create one transaction record."""
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
        """Should create N+1 splits: one per line item plus one for SAMUSE."""
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
        """All splits for the created transaction must sum to zero (balanced)."""
        txn_guid = gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )

        with gnucash_db.get_connection(readonly=True) as conn:
            rows = conn.execute(
                "SELECT value_num, value_denom FROM splits WHERE tx_guid = ?",
                (txn_guid,)
            ).fetchall()

        # All value_num/value_denom pairs must sum to 0 (using integer arithmetic)
        # Since denom is always 100, just sum value_num
        total = sum(r["value_num"] for r in rows)
        assert total == 0, f"Splits do not balance: total value_num = {total}"

    def test_samuse_split_value_equals_sum_of_line_items(self, db_connection, test_accounts, cash_entry_data):
        """The SAMUSE split value should equal the sum of all line item amounts in cents."""
        expected_total_cents = int(sum(
            item["amount"] for item in cash_entry_data["line_items"]
        ) * 100)

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

        assert row is not None, "SAMUSE split not found"
        assert row["value_num"] == expected_total_cents

    def test_line_item_splits_have_correct_values(self, db_connection, test_accounts, cash_entry_data):
        """Each line item split should have value_num = -amount_cents."""
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

        samuse_guid = gnucash_db.get_samuse_account_guid()
        split_map = {s["account_guid"]: s for s in splits if s["account_guid"] != samuse_guid}

        for item in cash_entry_data["line_items"]:
            expected_cents = int(-item["amount"] * 100)
            actual = split_map.get(item["account_guid"])
            assert actual is not None, f"Split for account {item['account_guid']} not found"
            assert actual["value_num"] == expected_cents
            assert actual["memo"] == item["memo"]

    def test_negative_amount_line_item(self, db_connection, test_accounts, cash_entry_data):
        """Negative amounts (cash out of SAMUSE) should be handled correctly."""
        line_items = [
            {"account_guid": test_accounts["income"], "memo": "Service", "amount": 100.00},
            {"account_guid": test_accounts["coins"], "memo": "Coins exchange", "amount": -20.00},
        ]
        txn_guid = gnucash_db.create_cash_entry(
            entry_date=date.today(),
            line_items=line_items,
            description="Test negative",
        )

        with gnucash_db.get_connection(readonly=True) as conn:
            rows = conn.execute(
                "SELECT value_num FROM splits WHERE tx_guid = ?", (txn_guid,)
            ).fetchall()

        total = sum(r["value_num"] for r in rows)
        assert total == 0

    def test_returns_transaction_guid(self, db_connection, test_accounts, cash_entry_data):
        """Should return the created transaction GUID as a 32-char hex string."""
        txn_guid = gnucash_db.create_cash_entry(
            entry_date=cash_entry_data["date"],
            line_items=cash_entry_data["line_items"],
            description=cash_entry_data["description"],
        )
        assert isinstance(txn_guid, str)
        assert len(txn_guid) == 32

    def test_raises_on_empty_line_items(self, db_connection, cash_entry_data):
        """Should raise ValueError if line_items list is empty."""
        with pytest.raises(ValueError, match="line_items"):
            gnucash_db.create_cash_entry(
                entry_date=cash_entry_data["date"],
                line_items=[],
                description="Empty",
            )


class TestCreateCashDeposit:
    """Tests for create_cash_deposit()."""

    def test_creates_transaction(self, db_connection, test_accounts):
        """Should create one transaction record."""
        with gnucash_db.get_connection(readonly=True) as conn:
            before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

        gnucash_db.create_cash_deposit(
            deposit_date=date.today() + timedelta(days=1),
            bank_account_guid=test_accounts["checking"],
            amount=75.00,
        )

        with gnucash_db.get_connection(readonly=True) as conn:
            after = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert after == before + 1

    def test_creates_exactly_two_splits(self, db_connection, test_accounts):
        """Should create exactly 2 splits: SAMUSE and bank account."""
        with gnucash_db.get_connection(readonly=True) as conn:
            before = conn.execute("SELECT COUNT(*) FROM splits").fetchone()[0]

        gnucash_db.create_cash_deposit(
            deposit_date=date.today() + timedelta(days=1),
            bank_account_guid=test_accounts["checking"],
            amount=75.00,
        )

        with gnucash_db.get_connection(readonly=True) as conn:
            after = conn.execute("SELECT COUNT(*) FROM splits").fetchone()[0]
        assert after == before + 2

    def test_splits_sum_to_zero(self, db_connection, test_accounts):
        """The two splits must balance to zero."""
        txn_guid = gnucash_db.create_cash_deposit(
            deposit_date=date.today() + timedelta(days=1),
            bank_account_guid=test_accounts["checking"],
            amount=75.00,
        )

        with gnucash_db.get_connection(readonly=True) as conn:
            rows = conn.execute(
                "SELECT value_num FROM splits WHERE tx_guid = ?", (txn_guid,)
            ).fetchall()

        total = sum(r["value_num"] for r in rows)
        assert total == 0

    def test_samuse_split_is_negative(self, db_connection, test_accounts):
        """SAMUSE split should be negative (cash leaving the drawer)."""
        samuse_guid = gnucash_db.get_samuse_account_guid()
        txn_guid = gnucash_db.create_cash_deposit(
            deposit_date=date.today() + timedelta(days=1),
            bank_account_guid=test_accounts["checking"],
            amount=75.00,
        )

        with gnucash_db.get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT value_num FROM splits WHERE tx_guid = ? AND account_guid = ?",
                (txn_guid, samuse_guid)
            ).fetchone()

        assert row is not None
        assert row["value_num"] == -7500  # -$75.00

    def test_bank_split_is_positive(self, db_connection, test_accounts):
        """Bank account split should be positive (cash going in to bank)."""
        txn_guid = gnucash_db.create_cash_deposit(
            deposit_date=date.today() + timedelta(days=1),
            bank_account_guid=test_accounts["checking"],
            amount=75.00,
        )

        with gnucash_db.get_connection(readonly=True) as conn:
            row = conn.execute(
                "SELECT value_num FROM splits WHERE tx_guid = ? AND account_guid = ?",
                (txn_guid, test_accounts["checking"])
            ).fetchone()

        assert row is not None
        assert row["value_num"] == 7500  # +$75.00

    def test_raises_on_zero_amount(self, db_connection, test_accounts):
        """Should raise ValueError for zero deposit amount."""
        with pytest.raises(ValueError, match="amount"):
            gnucash_db.create_cash_deposit(
                deposit_date=date.today(),
                bank_account_guid=test_accounts["checking"],
                amount=0.0,
            )

    def test_raises_on_negative_amount(self, db_connection, test_accounts):
        """Should raise ValueError for negative deposit amount."""
        with pytest.raises(ValueError, match="amount"):
            gnucash_db.create_cash_deposit(
                deposit_date=date.today(),
                bank_account_guid=test_accounts["checking"],
                amount=-50.0,
            )
```

**Step 2: Add `cash_entry_data` and `coins` account fixtures to conftest.py**

Open `tests/conftest.py`. After the existing `bill_data` fixture, add:

```python
@pytest.fixture
def cash_entry_data(test_accounts):
    """Sample cash entry data with two positive line items."""
    return {
        "date": date.today(),
        "description": "Test cash entry",
        "line_items": [
            {
                "account_guid": test_accounts["income"],
                "memo": "Alice",
                "amount": 50.00,
            },
            {
                "account_guid": test_accounts["income"],
                "memo": "Bob",
                "amount": 30.00,
            },
        ],
    }
```

Also update the `test_accounts` fixture in `conftest.py` to include a `coins` key. Read the existing `test_accounts` fixture first, then add:

```python
# Inside test_accounts fixture, add to the returned dict:
"coins": <guid of a second asset/cash account from the test DB>
```

> **Note:** The `coins` account guid must be a real account in the test database. Read `conftest.py` and adapt — use a second ASSET or CASH account that already exists, or use the same `income` account for the coins tests (acceptable for unit testing the split math).

**Step 3: Run tests to confirm they all fail**

```bash
pytest tests/test_cash_entry.py -v
```

Expected: All tests fail with `AttributeError: module 'gnucash_db' has no attribute 'get_samuse_account_guid'` (or similar). This confirms the tests are wired correctly before implementation.

---

## Task 3: Implement `get_samuse_account_guid` and `create_cash_entry`

**Files:**
- Modify: `gnucash_db.py`
- Read first: `gnucash_db.py` lines 1–200 (to find where to add the new functions, and to understand `get_connection`, `generate_guid`, `format_gnucash_date`, `format_gnucash_timestamp`, `verify_record_exists`, `WriteVerificationError`, `is_locked_by_others`)

**Step 1: Add module-level cache variable and constant**

Find the block of module-level constants near the top of `gnucash_db.py` (after imports). Add:

```python
# Cash-on-hand entry constants
SAMUSE_ACCOUNT_NAME = "SAMUSE Cash-on-hand"
_samuse_guid_cache: str | None = None
```

**Step 2: Add `get_samuse_account_guid()`**

Find a logical grouping point (near other account lookup functions like `get_checking_accounts`). Add:

```python
def get_samuse_account_guid() -> str:
    """Return the GUID of the SAMUSE Cash-on-hand account, cached after first call.

    Raises:
        ValueError: If the account is not found in the database.
    """
    global _samuse_guid_cache
    if _samuse_guid_cache is not None:
        return _samuse_guid_cache

    with get_connection(readonly=True) as conn:
        row = conn.execute(
            "SELECT guid FROM accounts WHERE name = ? AND placeholder = 0",
            (SAMUSE_ACCOUNT_NAME,)
        ).fetchone()

    if row is None:
        raise ValueError(
            f"SAMUSE Cash-on-hand account '{SAMUSE_ACCOUNT_NAME}' not found in database. "
            "Verify the account name in config.SAMUSE_ACCOUNT_NAME."
        )

    _samuse_guid_cache = row["guid"]
    return _samuse_guid_cache
```

**Step 3: Add `create_cash_entry()`**

Add after `get_samuse_account_guid()`:

```python
def create_cash_entry(
    entry_date: date,
    line_items: list[dict],
    description: str = "",
    verify: bool = True,
) -> str:
    """Create a multi-split cash-on-hand transaction in GnuCash.

    Creates one transaction with N+1 splits: one per line item against its
    respective account, plus one auto-calculated balancing split for the
    SAMUSE Cash-on-hand account.

    Args:
        entry_date: Date of the cash entry (shared by all splits).
        line_items: List of dicts, each with keys:
            - account_guid (str): 32-char hex account GUID
            - memo (str): Who paid / note for this split
            - amount (float): Positive = cash in to SAMUSE, negative = cash out
        description: Transaction-level description (optional).
        verify: If True, verify each record after insertion.

    Returns:
        The GUID of the created transaction.

    Raises:
        ValueError: If line_items is empty.
        WriteVerificationError: If any insert cannot be verified.
        RuntimeError: If the database is locked by another process.
    """
    if not line_items:
        raise ValueError("line_items must not be empty")

    # --- Lock check (MANDATORY before any write) ---
    locked, hostname, pid = is_locked_by_others()
    if locked:
        raise RuntimeError(
            f"GnuCash database is locked by {hostname} (PID {pid}). "
            "Close GnuCash or the other process before entering cash."
        )

    # --- Pre-calculate SAMUSE balancing amount ---
    total_cents = int(round(sum(item["amount"] for item in line_items) * 100))
    samuse_guid = get_samuse_account_guid()
    usd_guid = get_usd_guid()

    # Verify transaction will balance before writing anything
    line_cents = [int(round(-item["amount"] * 100)) for item in line_items]
    assert total_cents + sum(line_cents) == 0, "Transaction would not balance — internal error"

    post_date_str = format_gnucash_date(entry_date, include_time=True)
    enter_date_str = format_gnucash_timestamp()

    txn_guid = generate_guid()

    with get_connection(readonly=False) as conn:
        # 1. Insert transaction
        conn.execute(
            """
            INSERT INTO transactions
                (guid, currency_guid, num, post_date, enter_date, description)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (txn_guid, usd_guid, "", post_date_str, enter_date_str, description),
        )

        # 2. Insert SAMUSE balancing split
        samuse_split_guid = generate_guid()
        conn.execute(
            """
            INSERT INTO splits
                (guid, tx_guid, account_guid, memo,
                 value_num, value_denom, quantity_num, quantity_denom,
                 reconcile_state, lot_guid)
            VALUES (?, ?, ?, ?, ?, 100, ?, 100, 'n', NULL)
            """,
            (samuse_split_guid, txn_guid, samuse_guid, description,
             total_cents, total_cents),
        )

        # 3. Insert one split per line item
        for item, split_cents in zip(line_items, line_cents):
            split_guid = generate_guid()
            conn.execute(
                """
                INSERT INTO splits
                    (guid, tx_guid, account_guid, memo,
                     value_num, value_denom, quantity_num, quantity_denom,
                     reconcile_state, lot_guid)
                VALUES (?, ?, ?, ?, ?, 100, ?, 100, 'n', NULL)
                """,
                (split_guid, txn_guid, item["account_guid"], item["memo"],
                 split_cents, split_cents),
            )

        conn.commit()

    if verify:
        verify_record_exists("transactions", txn_guid, "cash entry transaction")
        verify_record_exists("splits", samuse_split_guid, "SAMUSE split")

    log_database_operation("create_cash_entry", txn_guid, f"total={total_cents/100:.2f}")
    return txn_guid
```

**Step 4: Run the create_cash_entry tests**

```bash
pytest tests/test_cash_entry.py::TestGetSamuseAccountGuid tests/test_cash_entry.py::TestCreateCashEntry -v
```

Expected: All pass. If any fail, read the error carefully — most likely causes:
- Column name mismatch in `splits` or `transactions` table (check schema with `schema_discovery.py` patterns)
- `get_usd_guid()` not found — locate its name in `gnucash_db.py` and use the correct function name
- `log_database_operation` not defined — use `logger.info(...)` instead if that helper doesn't exist

**Step 5: Commit**

```bash
git add gnucash_db.py tests/test_cash_entry.py tests/conftest.py
git commit -m "feat: add create_cash_entry and get_samuse_account_guid to gnucash_db"
```

---

## Task 4: Implement `create_cash_deposit`

**Files:**
- Modify: `gnucash_db.py`

**Step 1: Add `create_cash_deposit()` after `create_cash_entry()`**

```python
def create_cash_deposit(
    deposit_date: date,
    bank_account_guid: str,
    amount: float,
    memo: str = "Bank deposit",
    verify: bool = True,
) -> str:
    """Create a deposit transaction from SAMUSE Cash-on-hand to a bank account.

    This is a separate, independent transaction — the amount does not need to
    match any batch entry total (SAMUSE is a petty cash drawer).

    Args:
        deposit_date: Date of the deposit (typically next day after cash entry).
        bank_account_guid: GUID of the destination bank account.
        amount: Positive dollar amount to deposit.
        memo: Optional memo for both splits.
        verify: If True, verify each record after insertion.

    Returns:
        The GUID of the created deposit transaction.

    Raises:
        ValueError: If amount is zero or negative.
        WriteVerificationError: If any insert cannot be verified.
        RuntimeError: If the database is locked by another process.
    """
    if amount <= 0:
        raise ValueError(f"Deposit amount must be positive, got {amount}")

    # --- Lock check (MANDATORY before any write) ---
    locked, hostname, pid = is_locked_by_others()
    if locked:
        raise RuntimeError(
            f"GnuCash database is locked by {hostname} (PID {pid}). "
            "Close GnuCash or the other process before depositing."
        )

    samuse_guid = get_samuse_account_guid()
    usd_guid = get_usd_guid()
    amount_cents = int(round(amount * 100))

    post_date_str = format_gnucash_date(deposit_date, include_time=True)
    enter_date_str = format_gnucash_timestamp()

    txn_guid = generate_guid()
    samuse_split_guid = generate_guid()
    bank_split_guid = generate_guid()

    with get_connection(readonly=False) as conn:
        # 1. Insert transaction
        conn.execute(
            """
            INSERT INTO transactions
                (guid, currency_guid, num, post_date, enter_date, description)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (txn_guid, usd_guid, "", post_date_str, enter_date_str, memo),
        )

        # 2. SAMUSE split — cash leaving the drawer (negative)
        conn.execute(
            """
            INSERT INTO splits
                (guid, tx_guid, account_guid, memo,
                 value_num, value_denom, quantity_num, quantity_denom,
                 reconcile_state, lot_guid)
            VALUES (?, ?, ?, ?, ?, 100, ?, 100, 'n', NULL)
            """,
            (samuse_split_guid, txn_guid, samuse_guid, memo,
             -amount_cents, -amount_cents),
        )

        # 3. Bank split — cash arriving in bank (positive)
        conn.execute(
            """
            INSERT INTO splits
                (guid, tx_guid, account_guid, memo,
                 value_num, value_denom, quantity_num, quantity_denom,
                 reconcile_state, lot_guid)
            VALUES (?, ?, ?, ?, ?, 100, ?, 100, 'n', NULL)
            """,
            (bank_split_guid, txn_guid, bank_account_guid, memo,
             amount_cents, amount_cents),
        )

        conn.commit()

    if verify:
        verify_record_exists("transactions", txn_guid, "deposit transaction")
        verify_record_exists("splits", samuse_split_guid, "SAMUSE deposit split")
        verify_record_exists("splits", bank_split_guid, "bank deposit split")

    log_database_operation("create_cash_deposit", txn_guid, f"amount={amount:.2f}")
    return txn_guid
```

**Step 2: Run deposit tests**

```bash
pytest tests/test_cash_entry.py::TestCreateCashDeposit -v
```

Expected: All pass.

**Step 3: Run full test suite to check for regressions**

```bash
pytest tests/ -v
```

Expected: All previously passing tests still pass.

**Step 4: Commit**

```bash
git add gnucash_db.py
git commit -m "feat: add create_cash_deposit to gnucash_db"
```

---

## Task 5: Add a `get_cash_accounts()` Utility and Web Route Helpers

**Files:**
- Modify: `gnucash_db.py` (one small function)
- Create: `web/cash_io.py`

**Step 1: Add `get_cash_accounts()` to gnucash_db.py**

```python
def get_cash_accounts() -> list[dict]:
    """Load the cash/income account list from data/cash_accounts.json.

    Returns:
        List of dicts with 'name' and 'guid' keys.
        Returns empty list if file does not exist.
    """
    from config import CASH_ACCOUNTS_PATH
    if not CASH_ACCOUNTS_PATH.exists():
        return []
    import json
    data = json.loads(CASH_ACCOUNTS_PATH.read_text(encoding="utf-8"))
    return data.get("accounts", [])
```

**Step 2: Create `web/cash_io.py`** for client list management:

```python
"""Client name list I/O for cash entry memo autocomplete."""

import json
from config import CLIENTS_PATH


def read_clients() -> list[str]:
    """Return sorted list of client names from clients.json."""
    if not CLIENTS_PATH.exists():
        return []
    data = json.loads(CLIENTS_PATH.read_text(encoding="utf-8"))
    return sorted(data.get("clients", []))


def search_clients(query: str, limit: int = 10) -> list[str]:
    """Return client names that start with or contain the query string (case-insensitive)."""
    q = query.strip().lower()
    if not q:
        return []
    clients = read_clients()
    starts = [c for c in clients if c.lower().startswith(q)]
    contains = [c for c in clients if q in c.lower() and c not in starts]
    return (starts + contains)[:limit]
```

**Step 3: Write tests for cash_io.py**

Create `tests/test_cash_io.py`:

```python
import pytest
import json
from pathlib import Path
from unittest.mock import patch


def test_read_clients_empty_when_file_missing(tmp_path, monkeypatch):
    import web.cash_io as cash_io
    monkeypatch.setattr(cash_io, "CLIENTS_PATH", tmp_path / "nonexistent.json")
    assert cash_io.read_clients() == []


def test_read_clients_returns_sorted(tmp_path, monkeypatch):
    import web.cash_io as cash_io
    f = tmp_path / "clients.json"
    f.write_text(json.dumps({"clients": ["Zara", "Alice", "Bob"]}))
    monkeypatch.setattr(cash_io, "CLIENTS_PATH", f)
    result = cash_io.read_clients()
    assert result == ["Alice", "Bob", "Zara"]


def test_search_clients_starts_with(tmp_path, monkeypatch):
    import web.cash_io as cash_io
    f = tmp_path / "clients.json"
    f.write_text(json.dumps({"clients": ["Alice Smith", "Alice Jones", "Bob"]}))
    monkeypatch.setattr(cash_io, "CLIENTS_PATH", f)
    result = cash_io.search_clients("ali")
    assert "Alice Smith" in result
    assert "Alice Jones" in result
    assert "Bob" not in result


def test_search_clients_empty_query(tmp_path, monkeypatch):
    import web.cash_io as cash_io
    f = tmp_path / "clients.json"
    f.write_text(json.dumps({"clients": ["Alice"]}))
    monkeypatch.setattr(cash_io, "CLIENTS_PATH", f)
    assert cash_io.search_clients("") == []
```

**Step 4: Run cash_io tests**

```bash
pytest tests/test_cash_io.py -v
```

Expected: All pass.

**Step 5: Commit**

```bash
git add gnucash_db.py web/cash_io.py tests/test_cash_io.py
git commit -m "feat: add get_cash_accounts and cash_io client list helpers"
```

---

## Task 6: Update Dashboard Layout to Split-Screen

**Files:**
- Read first: `web/templates/base.html`, `web/templates/dashboard.html`, `web/static/style.css`
- Modify: `web/templates/dashboard.html`
- Modify: `web/static/style.css`

**Step 1: Read the existing templates and CSS**

Read all three files before making any changes. Understand the current card/column structure.

**Step 2: Update `dashboard.html` to split-screen**

Replace the existing content block with a two-column flex layout. The exact markup depends on what you find in dashboard.html, but the structure should be:

```html
{% extends "base.html" %}
{% block content %}
<div class="dashboard-split">
  <!-- LEFT: Bills panel -->
  <div class="panel panel-bills">
    {% include "partials/sync_status.html" %}
    {% include "partials/queued_bills.html" %}
    <!-- existing bill entry form card here -->
    <!-- existing recent bills table card here -->
  </div>

  <!-- RIGHT: Cash-on-hand panel -->
  <div class="panel panel-cash">
    {% include "partials/cash_entry.html" %}
  </div>
</div>
{% endblock %}
```

**Step 3: Add split-screen CSS to `style.css`**

Append to `web/static/style.css`:

```css
/* Split-screen dashboard layout */
.dashboard-split {
  display: flex;
  gap: 1.5rem;
  align-items: flex-start;
}

.panel {
  flex: 1 1 0;
  min-width: 0; /* prevent flex overflow */
}

@media (max-width: 900px) {
  .dashboard-split {
    flex-direction: column;
  }
}
```

**Step 4: Verify the page still loads**

Start the server:
```bash
python -m uvicorn bill_processor.web.app:app --reload
```
Open `http://localhost:8000`. Verify the bills panel still works. The cash panel area will be empty until Task 7.

**Step 5: Commit**

```bash
git add web/templates/dashboard.html web/static/style.css
git commit -m "feat: update dashboard to split-screen layout (bills left, cash right)"
```

---

## Task 7: Create Cash Entry Panel Template and Partials

**Files:**
- Create: `web/templates/partials/cash_entry.html`
- Create: `web/templates/partials/cash_row.html`

**Step 1: Create `web/templates/partials/cash_row.html`**

This is a single line item row returned by the `GET /cash/add-row` endpoint:

```html
<tr class="cash-row">
  <td>
    <select name="account_guid" required>
      <option value="">-- Account --</option>
      {% for acct in cash_accounts %}
      <option value="{{ acct.guid }}">{{ acct.name }}</option>
      {% endfor %}
    </select>
  </td>
  <td>
    <input type="text"
           name="memo"
           placeholder="Client name"
           autocomplete="off"
           hx-get="/clients/search"
           hx-trigger="keyup changed delay:200ms"
           hx-target="next .client-suggestions"
           hx-include="[name='memo']"
           required>
    <datalist class="client-suggestions"></datalist>
  </td>
  <td>
    <input type="number"
           name="amount"
           step="0.01"
           placeholder="0.00"
           class="amount-input"
           hx-on:change="updateSamuseTotal()"
           required>
  </td>
  <td>
    <button type="button"
            onclick="this.closest('tr').remove(); updateSamuseTotal()">✕</button>
  </td>
</tr>
```

**Step 2: Create `web/templates/partials/cash_entry.html`**

```html
<div class="card" id="cash-entry-panel">
  <h2>Cash Entry</h2>

  <div id="cash-error" class="error-msg" style="display:none"></div>
  <div id="cash-success" class="success-msg" style="display:none"></div>

  <form id="cash-form"
        hx-post="/cash/submit"
        hx-target="#cash-entry-panel"
        hx-swap="outerHTML">

    <div class="form-row">
      <label>Date
        <input type="date" name="entry_date" id="cash-date" required
               value="{{ today }}">
      </label>
    </div>

    <table id="cash-rows-table">
      <thead>
        <tr>
          <th>Account</th>
          <th>Memo (who paid)</th>
          <th>Amount ($)</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="cash-rows">
        <!-- Rows injected here by HTMX -->
      </tbody>
    </table>

    <button type="button"
            hx-get="/cash/add-row"
            hx-target="#cash-rows"
            hx-swap="beforeend">
      + Add Row
    </button>

    <div class="samuse-total">
      SAMUSE Total: $<span id="samuse-total">0.00</span>
    </div>

    <hr>

    <!-- Optional Bank Deposit Section -->
    <div class="deposit-toggle">
      <label>
        <input type="checkbox" id="deposit-toggle-cb"
               onchange="document.getElementById('deposit-section').style.display = this.checked ? 'block' : 'none'">
        Bank Deposit
      </label>
    </div>

    <div id="deposit-section" style="display:none">
      <div class="form-row">
        <label>Bank Account
          <select name="deposit_account_guid">
            <option value="">-- Select bank --</option>
            {% for acct in bank_accounts %}
            <option value="{{ acct.guid }}">{{ acct.name }}</option>
            {% endfor %}
          </select>
        </label>
        <label>Amount
          <input type="number" name="deposit_amount" step="0.01" placeholder="0.00">
        </label>
        <label>Date
          <input type="date" name="deposit_date" value="{{ tomorrow }}">
        </label>
      </div>
    </div>

    <div class="form-actions">
      <button type="submit">Submit All</button>
    </div>

  </form>
</div>

<script>
function updateSamuseTotal() {
  const inputs = document.querySelectorAll('#cash-rows .amount-input');
  let total = 0;
  inputs.forEach(input => {
    const val = parseFloat(input.value);
    if (!isNaN(val)) total += val;
  });
  document.getElementById('samuse-total').textContent = total.toFixed(2);
}
</script>
```

**Step 3: Commit**

```bash
git add web/templates/partials/cash_entry.html web/templates/partials/cash_row.html
git commit -m "feat: add cash entry panel and row templates"
```

---

## Task 8: Add FastAPI Routes for Cash Panel

**Files:**
- Read first: `web/app.py` (full file — understand imports, existing route patterns, how `templates.TemplateResponse` is called)
- Modify: `web/app.py`

**Step 1: Add imports at top of app.py**

Find the imports section. Add:

```python
from web.cash_io import search_clients
import gnucash_db
```

> If `gnucash_db` is already imported, skip that line.

**Step 2: Update the `GET /` route to pass cash panel data**

Find the `GET /` route handler. It currently returns a `TemplateResponse` for `dashboard.html`. Update it to also pass:

```python
from datetime import date, timedelta

# Inside the GET / handler, add to the template context:
"cash_accounts": gnucash_db.get_cash_accounts(),
"bank_accounts": gnucash_db.get_checking_accounts(),  # already exists in gnucash_db
"today": date.today().isoformat(),
"tomorrow": (date.today() + timedelta(days=1)).isoformat(),
```

**Step 3: Add the cash panel routes**

Add these routes after the existing vendor routes:

```python
# ---------------------------------------------------------------------------
# Cash-on-hand entry routes
# ---------------------------------------------------------------------------

@app.get("/cash/add-row")
async def cash_add_row(request: Request):
    """Return a blank line item row partial for the cash entry table."""
    cash_accounts = gnucash_db.get_cash_accounts()
    return templates.TemplateResponse(
        "partials/cash_row.html",
        {"request": request, "cash_accounts": cash_accounts},
    )


@app.get("/clients/search")
async def clients_search(request: Request, memo: str = ""):
    """Return autocomplete suggestions for client names."""
    suggestions = search_clients(memo)
    # Return a simple datalist options fragment
    options_html = "".join(f'<option value="{s}">' for s in suggestions)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=options_html)


@app.post("/cash/submit")
async def cash_submit(request: Request):
    """Process the cash entry form: create batch transaction + optional deposit."""
    from datetime import date as date_type
    from fastapi.responses import HTMLResponse

    form = await request.form()

    # --- Parse line items ---
    # Form sends repeated fields: account_guid[], memo[], amount[]
    account_guids = form.getlist("account_guid")
    memos = form.getlist("memo")
    amounts_raw = form.getlist("amount")

    # Filter out incomplete rows (all three fields must be present)
    line_items = []
    for guid, memo, amount_str in zip(account_guids, memos, amounts_raw):
        guid = guid.strip()
        memo = memo.strip()
        amount_str = amount_str.strip()
        if guid and memo and amount_str:
            try:
                line_items.append({
                    "account_guid": guid,
                    "memo": memo,
                    "amount": float(amount_str),
                })
            except ValueError:
                pass  # skip malformed rows

    if not line_items:
        # Return the panel with an error message
        cash_accounts = gnucash_db.get_cash_accounts()
        bank_accounts = gnucash_db.get_checking_accounts()
        today = date_type.today()
        return templates.TemplateResponse(
            "partials/cash_entry.html",
            {
                "request": request,
                "cash_accounts": cash_accounts,
                "bank_accounts": bank_accounts,
                "today": today.isoformat(),
                "tomorrow": (today + timedelta(days=1)).isoformat(),
                "error": "At least one complete line item is required.",
            },
        )

    entry_date_str = form.get("entry_date", "").strip()
    try:
        entry_date = date_type.fromisoformat(entry_date_str)
    except ValueError:
        entry_date = date_type.today()

    # --- Create batch transaction ---
    try:
        txn_guid = gnucash_db.create_cash_entry(
            entry_date=entry_date,
            line_items=line_items,
            description="Cash receipt",
        )
    except (RuntimeError, gnucash_db.WriteVerificationError) as exc:
        today = date_type.today()
        return templates.TemplateResponse(
            "partials/cash_entry.html",
            {
                "request": request,
                "cash_accounts": gnucash_db.get_cash_accounts(),
                "bank_accounts": gnucash_db.get_checking_accounts(),
                "today": today.isoformat(),
                "tomorrow": (today + timedelta(days=1)).isoformat(),
                "error": str(exc),
            },
        )

    deposit_error = None
    deposit_txn_guid = None

    # --- Optional deposit transaction ---
    deposit_account_guid = form.get("deposit_account_guid", "").strip()
    deposit_amount_str = form.get("deposit_amount", "").strip()
    deposit_date_str = form.get("deposit_date", "").strip()

    if deposit_account_guid and deposit_amount_str:
        try:
            deposit_amount = float(deposit_amount_str)
            deposit_date = date_type.fromisoformat(deposit_date_str) if deposit_date_str else date_type.today() + timedelta(days=1)
            deposit_txn_guid = gnucash_db.create_cash_deposit(
                deposit_date=deposit_date,
                bank_account_guid=deposit_account_guid,
                amount=deposit_amount,
            )
        except (RuntimeError, gnucash_db.WriteVerificationError, ValueError) as exc:
            deposit_error = str(exc)

    # --- Return cleared form with success message ---
    total = sum(item["amount"] for item in line_items)
    success_msg = f"Posted ${total:.2f} to SAMUSE Cash-on-hand."
    if deposit_txn_guid:
        success_msg += f" Deposit of ${float(deposit_amount_str):.2f} recorded."
    if deposit_error:
        success_msg += f" (Deposit failed: {deposit_error})"

    today = date_type.today()
    return templates.TemplateResponse(
        "partials/cash_entry.html",
        {
            "request": request,
            "cash_accounts": gnucash_db.get_cash_accounts(),
            "bank_accounts": gnucash_db.get_checking_accounts(),
            "today": today.isoformat(),
            "tomorrow": (today + timedelta(days=1)).isoformat(),
            "success": success_msg,
        },
    )
```

**Step 4: Update `cash_entry.html` to show error/success from context**

In `web/templates/partials/cash_entry.html`, the error/success divs already reference `error` and `success` variables. Add Jinja2 logic to display them:

```html
<!-- Replace the static error/success divs with: -->
{% if error %}
<div class="error-msg">{{ error }}</div>
{% endif %}
{% if success %}
<div class="success-msg">{{ success }}</div>
{% endif %}
```

**Step 5: Start the server and manually test the full flow**

```bash
python -m uvicorn bill_processor.web.app:app --reload
```

1. Navigate to `http://localhost:8000`
2. Verify split-screen layout appears
3. Click "+ Add Row" — a new row should appear (HTMX)
4. Fill in account, memo, amount — SAMUSE Total should update
5. Click Submit All — form should clear and show success message

**Step 6: Commit**

```bash
git add web/app.py web/templates/partials/cash_entry.html
git commit -m "feat: add cash-on-hand FastAPI routes and wire up HTMX panel"
```

---

## Task 9: Write Web Route Tests

**Files:**
- Read first: `tests/test_web_app.py` (understand how TestClient is used)
- Modify: `tests/test_web_app.py` OR Create: `tests/test_cash_web.py`

**Step 1: Add cash route tests**

Create `tests/test_cash_web.py`:

```python
"""Tests for cash-on-hand web routes."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from web.app import app

client = TestClient(app)


def test_add_row_returns_html():
    """GET /cash/add-row should return an HTML table row."""
    with patch("gnucash_db.get_cash_accounts", return_value=[
        {"name": "Service Income", "guid": "abc123" * 5 + "ab"}
    ]):
        response = client.get("/cash/add-row")
    assert response.status_code == 200
    assert "<tr" in response.text


def test_client_search_returns_matches():
    """GET /clients/search?memo=ali should return matching client names."""
    with patch("web.cash_io.CLIENTS_PATH") as mock_path:
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = '{"clients": ["Alice", "Bob", "Albert"]}'
        response = client.get("/clients/search?memo=al")
    assert response.status_code == 200
    assert "Alice" in response.text or "Albert" in response.text


def test_cash_submit_empty_form_returns_error():
    """POST /cash/submit with no line items should return error message."""
    with patch("gnucash_db.get_cash_accounts", return_value=[]), \
         patch("gnucash_db.get_checking_accounts", return_value=[]):
        response = client.post("/cash/submit", data={})
    assert response.status_code == 200
    assert "required" in response.text.lower() or "line item" in response.text.lower()


def test_cash_submit_locked_db_shows_error():
    """POST /cash/submit when DB is locked should show lock error, not crash."""
    form_data = {
        "entry_date": "2026-03-09",
        "account_guid": ["abc" * 10 + "ab"],
        "memo": ["Alice"],
        "amount": ["100.00"],
    }
    with patch("gnucash_db.create_cash_entry",
               side_effect=RuntimeError("GnuCash database is locked by GnuCash@HOST (PID 1234)")), \
         patch("gnucash_db.get_cash_accounts", return_value=[]), \
         patch("gnucash_db.get_checking_accounts", return_value=[]):
        response = client.post("/cash/submit", data=form_data)
    assert response.status_code == 200
    assert "locked" in response.text.lower()


def test_cash_submit_success_clears_form():
    """POST /cash/submit with valid data should return success message."""
    form_data = {
        "entry_date": "2026-03-09",
        "account_guid": ["abc" * 10 + "ab"],
        "memo": ["Alice"],
        "amount": ["100.00"],
    }
    with patch("gnucash_db.create_cash_entry", return_value="a" * 32), \
         patch("gnucash_db.get_cash_accounts", return_value=[]), \
         patch("gnucash_db.get_checking_accounts", return_value=[]):
        response = client.post("/cash/submit", data=form_data)
    assert response.status_code == 200
    assert "100.00" in response.text or "SAMUSE" in response.text
```

**Step 2: Run web tests**

```bash
pytest tests/test_cash_web.py -v
```

Expected: All pass. Fix any import or mock path issues that arise.

**Step 3: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests pass.

**Step 4: Commit**

```bash
git add tests/test_cash_web.py
git commit -m "test: add web route tests for cash-on-hand entry panel"
```

---

## Task 10: Final Polish and CLAUDE.md Update

**Files:**
- Modify: `CLAUDE.md`
- Read: `docs/plans/2026-03-09-cash-on-hand-entry-design.md`

**Step 1: Update CLAUDE.md**

Add a section describing the cash-on-hand feature to the Architecture section. Add the new data files and routes. Keep it concise.

**Step 2: Populate data files for real use**

With the server running:
1. Open `data/clients.json` and add real client names
2. Open `data/cash_accounts.json` and add real account GUIDs from GnuCash

Use `columbo.py` to find account GUIDs:
```bash
python columbo.py path/to/CFSIV_Sqlite3_database.gnucash
# Then inspect snapshot_before.json → search for "SAMUSE" and income account names
```

**Step 3: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with cash-on-hand feature architecture"
```

---

## Appendix: Accounting Sign Reference

| Scenario | SAMUSE split | Other account split |
|----------|-------------|---------------------|
| Client pays $100 (income) | +10000 | -10000 |
| Coins exchange out $20 (SAMUSE gives coins, gets bills — net neutral) | -2000 | +2000 |
| Bank deposit $75 (separate txn) | -7500 | +7500 (bank) |

All splits within a transaction must sum to `0`. The `create_cash_entry` function asserts this before writing.

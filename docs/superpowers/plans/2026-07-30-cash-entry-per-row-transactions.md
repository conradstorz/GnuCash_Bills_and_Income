# Cash Entry: One Transaction Per Row — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a single cash-entry submit write one two-split GnuCash transaction per row (row account ↔ SAMUSE Cash-on-hand) instead of one shared multi-split transaction, so no account register shows unrelated sibling splits.

**Architecture:** Change the data-layer function `create_cash_entry()` in `gnucash_db.py` to loop over line items and create an independent, self-balancing transaction for each. Update the `/api/cash/submit` route to consume the new list return value while preserving the JSON fields the React frontend already reads (`batch.ok`, `batch.total`). The frontend needs no change.

**Tech Stack:** Python 3, SQLite (direct access), FastAPI, pytest, `uv` for env/test execution, loguru for logging.

**Spec:** `docs/superpowers/specs/2026-07-30-cash-entry-per-row-transactions-design.md`

## Global Constraints

- Run Python and tests via `uv` only: `uv run pytest ...`. Never `pip install` / `python -m venv`.
- Diagnostics use loguru (`logger.info` / `logger.debug`) — never `print()`.
- Sign convention (unchanged): positive `amount` = cash **into** Cash-on-hand. The SAMUSE Cash-on-hand split carries `+amount`; the row account split carries `-amount`.
- Each created transaction has **exactly two** splits and balances on its own (splits sum to zero).
- `create_cash_entry()` returns `list[str]` — one transaction GUID per row, in input order.
- Blank-memo fallback for a transaction's description is `config.DEFAULT_MEMO` (data layer imports `config`, not `settings`).
- Do not modify `create_cash_deposit()` or the `/api/cash/deposit` route.

---

### Task 1: Data layer — one transaction per line item

**Files:**
- Modify: `gnucash_db.py` — function `create_cash_entry` (currently ~lines 1476–1549)
- Test: `tests/test_cash_entry.py` — class `TestCreateCashEntry` (currently lines 33–156)

**Interfaces:**
- Consumes: `is_locked_by_others()`, `get_samuse_account_guid()`, `get_usd_guid()`, `format_gnucash_date(date, include_time=True)`, `format_gnucash_timestamp()`, `generate_guid()`, `verify_record_exists(table, guid, label)`, `config.DEFAULT_MEMO` — all already present in `gnucash_db.py`.
- Produces: `create_cash_entry(entry_date, line_items: list, description: str = "", verify: bool = True) -> list[str]`. Each `line_items` element is a dict with keys `account_guid` (str), `memo` (str), `amount` (float). Returns one 32-char hex transaction GUID per row, in input order.

- [ ] **Step 1: Replace the `TestCreateCashEntry` class with tests for the new behavior**

In `tests/test_cash_entry.py`, replace the entire `class TestCreateCashEntry:` block (lines 33–156, i.e. everything from `class TestCreateCashEntry:` up to but **not** including `class TestCreateCashDeposit:`) with:

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_cash_entry.py::TestCreateCashEntry -v`
Expected: FAIL. `test_creates_one_transaction_per_row`, `test_creates_two_splits_per_row`, `test_returns_list_of_guids`, and the isolation test fail because the current implementation makes one transaction with N+1 splits and returns a single GUID string.

- [ ] **Step 3: Rewrite `create_cash_entry` in `gnucash_db.py`**

Replace the entire existing `create_cash_entry` function (from `def create_cash_entry(` through its `return txn_guid` line, currently ~lines 1476–1549) with:

```python
def create_cash_entry(
    entry_date,
    line_items: list,
    description: str = "",
    verify: bool = True,
) -> list:
    """Create one cash-on-hand transaction per line item.

    Each line item becomes its own two-split GnuCash transaction: the row's
    account balanced against SAMUSE Cash-on-hand. Keeping every row in its own
    transaction means no account register shows unrelated sibling splits.

    line_items: list of dicts with keys: account_guid, memo, amount
    description: retained for backward compatibility; no longer used as a
        transaction description (each transaction uses its own row memo, or
        config.DEFAULT_MEMO when the row memo is blank).
    Returns: list of transaction GUIDs, one per line item, in input order.
    """
    if not line_items:
        raise ValueError("line_items must not be empty")

    locked, hostname, pid = is_locked_by_others()
    if locked:
        raise RuntimeError(
            f"GnuCash database is locked by {hostname} (PID {pid}). "
            "Close GnuCash before entering cash."
        )

    samuse_guid = get_samuse_account_guid()
    usd_guid = get_usd_guid()

    post_date_str = format_gnucash_date(entry_date, include_time=True)
    enter_date_str = format_gnucash_timestamp()

    logger.info(f"Creating cash entry: {len(line_items)} line items (one transaction each)")

    txn_guids = []
    created = []  # (txn_guid, samuse_split_guid, row_split_guid)

    with get_connection(readonly=False) as conn:
        for item in line_items:
            cents = int(round(item["amount"] * 100))
            memo = item.get("memo", "") or ""
            txn_desc = memo.strip() or config.DEFAULT_MEMO

            txn_guid = generate_guid()
            samuse_split_guid = generate_guid()
            row_split_guid = generate_guid()

            conn.execute(
                "INSERT INTO transactions (guid, currency_guid, num, post_date, enter_date, description) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (txn_guid, usd_guid, "", post_date_str, enter_date_str, txn_desc),
            )
            # SAMUSE Cash-on-hand leg (+amount)
            conn.execute(
                "INSERT INTO splits (guid, tx_guid, account_guid, memo, action, "
                "reconcile_state, reconcile_date, "
                "value_num, value_denom, quantity_num, quantity_denom, lot_guid) "
                "VALUES (?, ?, ?, ?, '', 'n', NULL, ?, 100, ?, 100, NULL)",
                (samuse_split_guid, txn_guid, samuse_guid, txn_desc, cents, cents),
            )
            # Row account leg (-amount)
            conn.execute(
                "INSERT INTO splits (guid, tx_guid, account_guid, memo, action, "
                "reconcile_state, reconcile_date, "
                "value_num, value_denom, quantity_num, quantity_denom, lot_guid) "
                "VALUES (?, ?, ?, ?, '', 'n', NULL, ?, 100, ?, 100, NULL)",
                (row_split_guid, txn_guid, item["account_guid"], memo, -cents, -cents),
            )
            txn_guids.append(txn_guid)
            created.append((txn_guid, samuse_split_guid, row_split_guid))
        conn.commit()

    logger.info(f"Cash entry created: {len(txn_guids)} transactions")

    if verify:
        for txn_guid, samuse_split_guid, row_split_guid in created:
            verify_record_exists("transactions", txn_guid, "cash entry transaction")
            verify_record_exists("splits", samuse_split_guid, "SAMUSE split")
            verify_record_exists("splits", row_split_guid, "cash entry row split")

    return txn_guids
```

- [ ] **Step 4: Run the data-layer tests to verify they pass**

Run: `uv run pytest tests/test_cash_entry.py -v`
Expected: PASS (all of `TestGetSamuseAccountGuid`, `TestCreateCashEntry`, `TestCreateCashDeposit`).

- [ ] **Step 5: Run the broader cash test suite to catch regressions**

Run: `uv run pytest tests/test_cash_entry.py tests/test_cash_io.py tests/test_get_cash_accounts.py -v`
Expected: PASS. (`test_cash_web.py` is intentionally addressed in Task 2 and may still pass here because it mocks `create_cash_entry`.)

- [ ] **Step 6: Commit**

```bash
git add gnucash_db.py tests/test_cash_entry.py
git commit -m "feat: write one GnuCash transaction per cash-entry row"
```

---

### Task 2: Web route — consume list return, preserve response shape

**Files:**
- Modify: `web/app.py` — function `cash_submit` (`/api/cash/submit`), currently lines 652–695 (the `batch` block, lines ~664–678)
- Test: `tests/test_cash_web.py` — class `TestCashSubmit` (lines 28–87)

**Interfaces:**
- Consumes: `gnucash_db.create_cash_entry(...) -> list[str]` (from Task 1); `cash_io.save_memo_to_history(memo)` (unchanged).
- Produces: `POST /api/cash/submit` JSON response where `result["batch"] == {"ok": True, "total": <float>, "count": <int>, "guids": <list[str]>}`. The `deposit` branch and its response are unchanged.

- [ ] **Step 1: Update the web tests for the new response shape**

In `tests/test_cash_web.py`, make these edits inside `class TestCashSubmit`:

Replace `test_valid_submission_returns_batch_result` (lines 36–45) with:

```python
    def test_valid_submission_returns_batch_result(self):
        with patch("bill_processor.gnucash_db.create_cash_entry", return_value=["z" * 32]):
            response = client.post("/api/cash/submit", json={
                "entry_date": "2026-03-09",
                "entries": [{"account_guid": "a" * 32, "memo": "Alice", "amount": 100.0}],
            })
        assert response.status_code == 200
        data = response.json()
        assert data["batch"]["ok"] is True
        assert data["batch"]["total"] == 100.0
        assert data["batch"]["count"] == 1
        assert data["batch"]["guids"] == ["z" * 32]

    def test_multiple_entries_report_count(self):
        with patch("bill_processor.gnucash_db.create_cash_entry",
                   return_value=["z" * 32, "y" * 32, "x" * 32]):
            response = client.post("/api/cash/submit", json={
                "entry_date": "2026-03-09",
                "entries": [
                    {"account_guid": "a" * 32, "memo": "A", "amount": 100.0},
                    {"account_guid": "b" * 32, "memo": "B", "amount": 120.0},
                    {"account_guid": "c" * 32, "memo": "Changer", "amount": -40.0},
                ],
            })
        assert response.status_code == 200
        data = response.json()
        assert data["batch"]["count"] == 3
        assert data["batch"]["total"] == 180.0
```

In `test_deposit_failure_included_in_response` (line 58) change the mock return value from `return_value="z" * 32` to `return_value=["z" * 32]`.

In `test_deposit_success_included_in_response` (line 75) change the mock return value from `return_value="z" * 32` to `return_value=["z" * 32]`.

(`test_empty_entries_returns_422` and `test_locked_db_returns_500` need no change.)

- [ ] **Step 2: Run the web submit tests to verify the new ones fail**

Run: `uv run pytest tests/test_cash_web.py::TestCashSubmit -v`
Expected: FAIL. `test_valid_submission_returns_batch_result` and `test_multiple_entries_report_count` fail with `KeyError: 'count'` (the current route returns `{"ok", "guid", "total"}`, no `count`/`guids`).

- [ ] **Step 3: Update the `batch` block in `cash_submit`**

In `web/app.py`, replace this block (currently lines ~664–678):

```python
    result = {}
    try:
        line_items = [
            {"account_guid": e.account_guid, "memo": e.memo, "amount": e.amount}
            for e in body.entries
        ]
        batch_guid = gnucash_db.create_cash_entry(
            entry_date=entry_date,
            line_items=line_items,
        )
        for item in line_items:
            if item["memo"].strip():
                cash_io.save_memo_to_history(item["memo"])
        total = sum(item["amount"] for item in line_items)
        logger.info(f"Cash entry posted: {len(line_items)} items, total=${total:.2f}, guid={batch_guid[:8]}")
        result["batch"] = {"ok": True, "guid": batch_guid, "total": total}
    except Exception as e:
        logger.exception(f"Cash entry failed (date={body.entry_date}, items={len(body.entries)}): {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

with:

```python
    result = {}
    try:
        line_items = [
            {"account_guid": e.account_guid, "memo": e.memo, "amount": e.amount}
            for e in body.entries
        ]
        guids = gnucash_db.create_cash_entry(
            entry_date=entry_date,
            line_items=line_items,
        )
        for item in line_items:
            if item["memo"].strip():
                cash_io.save_memo_to_history(item["memo"])
        total = sum(item["amount"] for item in line_items)
        logger.info(f"Cash entry posted: {len(guids)} transactions, total=${total:.2f}")
        result["batch"] = {"ok": True, "total": total, "count": len(guids), "guids": guids}
    except Exception as e:
        logger.exception(f"Cash entry failed (date={body.entry_date}, items={len(body.entries)}): {e}")
        raise HTTPException(status_code=500, detail=str(e))
```

- [ ] **Step 4: Run the web submit tests to verify they pass**

Run: `uv run pytest tests/test_cash_web.py -v`
Expected: PASS (all of `TestMemoSearch`, `TestCashSubmit`, `TestCashDeposit`, `TestAddressLookup`).

- [ ] **Step 5: Confirm the frontend needs no change**

No code edit. Verify by inspection that `frontend/src/pages/CashEntry.tsx` reads only `res.batch?.ok` and `res.batch.total` (both preserved). Run: `git grep -n "res.batch" frontend/src`
Expected: only references to `res.batch?.ok`, `res.batch.total`, `res.batch?.error` — none requiring `guid`/`count`.

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest`
Expected: PASS (no regressions across the suite).

- [ ] **Step 7: Commit**

```bash
git add web/app.py tests/test_cash_web.py
git commit -m "feat: report per-row transaction count from cash submit route"
```

---

## Self-Review

**Spec coverage:**
- "Each line item becomes its own transaction (2 splits, row account ↔ Cash-on-hand)" → Task 1, Steps 3 + tests in Step 1.
- "Sign convention unchanged" → Task 1 test `test_each_transaction_has_samuse_and_row_account`, `test_supports_negative_amount_row`.
- "Transaction description = row memo, fallback DEFAULT_MEMO" → Task 1 tests `test_transaction_description_is_row_memo`, `test_blank_memo_falls_back_to_default_description`.
- "Return type list[str]" → Task 1 test `test_returns_list_of_guids`.
- "Per-transaction verification" → Task 1 Step 3 `verify` loop.
- "Isolation of transfer/changer rows" → Task 1 test `test_transfer_row_transaction_is_isolated`.
- "Route preserves batch.ok/batch.total, adds count/guids; memo history unchanged" → Task 2 Steps 1–3.
- "Frontend no change" → Task 2 Step 5.
- "Deposit path untouched" → not modified; Global Constraints + `TestCreateCashDeposit`/`TestCashDeposit` remain unchanged and must still pass (Task 1 Step 4, Task 2 Step 4).
- "Out of scope: un-tangle prior transaction; new non-cash-on-hand transfer mode" → not in any task, intentionally.

**Placeholder scan:** No TBD/TODO; every code step shows full code. OK.

**Type consistency:** `create_cash_entry(...) -> list[str]` produced in Task 1, consumed as `guids` in Task 2. Test helper `_splits_for` returns list of dicts with `account_guid`/`value_num`/`memo`. Response keys `ok`/`total`/`count`/`guids` consistent between Task 2 Step 1 tests and Step 3 implementation. OK.

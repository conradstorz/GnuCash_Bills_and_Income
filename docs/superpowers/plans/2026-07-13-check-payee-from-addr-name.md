# Check Payee from Vendor `addr_name` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the printed check payee come from the vendor's `addr_name` ("Payment Address → Name") field when set, falling back to the vendor Company Name (`name`) otherwise.

**Architecture:** A single pure helper `_effective_payee(addr_name, name)` centralizes the fallback rule. `get_invoice_by_guid()` exposes the computed payee as `bill['check_payee']`; `post_bill()` and `pay_bill()` write that into the transaction `description` (the field GnuCash prints as the payee). The deprecated `create_posted_bill` path gets the same fallback so it can't silently diverge.

**Tech Stack:** Python 3, SQLite (GnuCash file), pytest, loguru, `uv` for running.

## Global Constraints

- Run all Python and tests via `uv` — `uv run pytest ...`, never bare `pytest` or `pip`.
- Do not chain shell commands with `&&`; issue separate commands.
- Use loguru for any diagnostics — never `print()`.
- All code changes in this plan are confined to `gnucash_db.py`; tests go in `tests/test_bill_workflow.py`.
- The fallback rule, stated once and used everywhere: `effective_payee = addr_name.strip() if addr_name and addr_name.strip() else (name or "")`.
- `bill['vendor_name']` keeps its current meaning (vendor Company Name) and MUST NOT change — it is used for logging. The payee is a new, separate value.
- Tests operate on a temporary copy of the real DB via `tests/conftest.py` fixtures (`db_connection`, `test_vendor_guid`, `test_accounts`, `bill_data`). They `pytest.skip` automatically if the real DB is absent.

---

### Task 1: `_effective_payee` fallback helper

**Files:**
- Modify: `gnucash_db.py` (add module-level helper near the other private helpers, e.g. just above `get_invoice_by_guid` at line 1738)
- Test: `tests/test_bill_workflow.py` (new class `TestEffectivePayee`, no DB fixtures needed)

**Interfaces:**
- Consumes: nothing.
- Produces: `gnucash_db._effective_payee(addr_name: Optional[str], vendor_name: Optional[str]) -> str` — returns trimmed `addr_name` when non-empty, else `vendor_name or ""`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bill_workflow.py`:

```python
class TestEffectivePayee:
    """Unit tests for the check-payee fallback rule (gnucash_db._effective_payee)."""

    def test_addr_name_used_when_present(self):
        assert gnucash_db._effective_payee("Bullet County Sheriff", "Bullet County Taxes KY") \
            == "Bullet County Sheriff"

    def test_falls_back_to_name_when_addr_name_empty(self):
        assert gnucash_db._effective_payee("", "Acme Co") == "Acme Co"

    def test_falls_back_to_name_when_addr_name_none(self):
        assert gnucash_db._effective_payee(None, "Acme Co") == "Acme Co"

    def test_falls_back_to_name_when_addr_name_whitespace(self):
        assert gnucash_db._effective_payee("   ", "Acme Co") == "Acme Co"

    def test_addr_name_is_trimmed(self):
        assert gnucash_db._effective_payee("  Real Payee LLC  ", "Acme Co") == "Real Payee LLC"

    def test_name_none_yields_empty_string(self):
        assert gnucash_db._effective_payee(None, None) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bill_workflow.py::TestEffectivePayee -v`
Expected: FAIL — `AttributeError: module 'bill_processor.gnucash_db' has no attribute '_effective_payee'`

- [ ] **Step 3: Write minimal implementation**

In `gnucash_db.py`, immediately above `def get_invoice_by_guid` (line 1738), add:

```python
def _effective_payee(addr_name: Optional[str], vendor_name: Optional[str]) -> str:
    """Return the name to print as the check payee.

    GnuCash prints the check payee from the transaction ``description`` field.
    We use the vendor's "Payment Address -> Name" field (``vendors.addr_name``)
    when it is non-empty, otherwise fall back to the vendor Company Name
    (``vendors.name``). See docs/CHECK_PRINTING.md and
    docs/superpowers/specs/2026-07-13-check-payee-from-addr-name-design.md.
    """
    if addr_name and addr_name.strip():
        return addr_name.strip()
    return vendor_name or ""
```

(`Optional` is already imported in `gnucash_db.py`; confirm with `grep -n "from typing import" gnucash_db.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_bill_workflow.py::TestEffectivePayee -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add gnucash_db.py tests/test_bill_workflow.py
git commit -m "feat: add _effective_payee fallback helper for check payee"
```

---

### Task 2: Route payee through post_bill and pay_bill

**Files:**
- Modify: `gnucash_db.py`
  - `get_invoice_by_guid()` at line 1738-1748
  - `post_bill()` description insert at line 2055
  - `pay_bill()` description insert at line 2292
- Test: `tests/test_bill_workflow.py` (new class `TestCheckPayee`)

**Interfaces:**
- Consumes: `gnucash_db._effective_payee(...)` from Task 1.
- Produces: `get_invoice_by_guid()` return dict now includes keys `vendor_addr_name` (raw column) and `check_payee` (computed). `post_bill`/`pay_bill` write `bill['check_payee']` into `transactions.description`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bill_workflow.py`:

```python
class TestCheckPayee:
    """The check payee (transaction description) comes from vendor.addr_name
    with fallback to vendor.name."""

    @staticmethod
    def _set_addr_name(db_path, vendor_guid, value):
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE vendors SET addr_name = ? WHERE guid = ?", (value, vendor_guid))
        conn.commit()
        conn.close()

    @staticmethod
    def _vendor_name(db_path, vendor_guid):
        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT name FROM vendors WHERE guid = ?", (vendor_guid,)).fetchone()
        conn.close()
        return row[0]

    @staticmethod
    def _description(db_path, txn_guid):
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT description FROM transactions WHERE guid = ?", (txn_guid,)
        ).fetchone()
        conn.close()
        return row[0]

    @staticmethod
    def _post_txn_guid(db_path, bill_guid):
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT post_txn FROM invoices WHERE guid = ?", (bill_guid,)
        ).fetchone()
        conn.close()
        return row[0]

    def test_addr_name_becomes_payee_on_both_transactions(
        self, db_connection, test_vendor_guid, test_accounts, bill_data
    ):
        self._set_addr_name(db_connection, test_vendor_guid, "Real Payee LLC")

        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date'],
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account'],
        )
        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            checking_account_guid=test_accounts['checking_account'],
            payment_date=bill_data['date'],
        )

        post_txn_guid = self._post_txn_guid(db_connection, bill_guid)
        assert self._description(db_connection, post_txn_guid) == "Real Payee LLC", \
            "Posting (AP) transaction description should be addr_name"
        assert self._description(db_connection, payment_txn_guid) == "Real Payee LLC", \
            "Payment transaction description (check payee) should be addr_name"

    def test_falls_back_to_vendor_name_when_addr_name_empty(
        self, db_connection, test_vendor_guid, test_accounts, bill_data
    ):
        self._set_addr_name(db_connection, test_vendor_guid, "")
        expected = self._vendor_name(db_connection, test_vendor_guid)

        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date'],
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account'],
        )
        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            checking_account_guid=test_accounts['checking_account'],
            payment_date=bill_data['date'],
        )

        assert self._description(db_connection, payment_txn_guid) == expected, \
            "Payment description should fall back to vendor name when addr_name empty"

    def test_falls_back_when_addr_name_whitespace(
        self, db_connection, test_vendor_guid, test_accounts, bill_data
    ):
        self._set_addr_name(db_connection, test_vendor_guid, "   ")
        expected = self._vendor_name(db_connection, test_vendor_guid)

        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date'],
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account'],
        )
        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            checking_account_guid=test_accounts['checking_account'],
            payment_date=bill_data['date'],
        )

        assert self._description(db_connection, payment_txn_guid) == expected, \
            "Whitespace-only addr_name should fall back to vendor name"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bill_workflow.py::TestCheckPayee -v`
Expected: FAIL on `test_addr_name_becomes_payee_on_both_transactions` — description equals the vendor name, not `"Real Payee LLC"` (the fallback tests may already pass since payee currently equals name).

- [ ] **Step 3: Modify `get_invoice_by_guid` to expose `check_payee`**

Replace `gnucash_db.py` lines 1738-1748 with:

```python
def get_invoice_by_guid(invoice_guid: str) -> Optional[Dict]:
    """Get an invoice/bill record by GUID.

    Adds a computed ``check_payee`` key: the vendor's addr_name when set,
    otherwise the vendor name. This is what should be printed as the check
    payee (see _effective_payee).
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT i.*, v.name as vendor_name, v.addr_name as vendor_addr_name
            FROM invoices i
            LEFT JOIN vendors v ON i.owner_guid = v.guid
            WHERE i.guid = ?
        """, (invoice_guid,))
        row = cursor.fetchone()
        if not row:
            return None
        bill = dict(row)
        bill['check_payee'] = _effective_payee(bill.get('vendor_addr_name'), bill.get('vendor_name'))
        return bill
```

- [ ] **Step 4: Modify `post_bill` to write the payee**

In `gnucash_db.py` at line 2055, change the last parameter from `bill['vendor_name']` to `bill['check_payee']`:

```python
            """, (txn_guid, usd_guid, date_posted, date_entered, bill['check_payee']))
```

- [ ] **Step 5: Modify `pay_bill` to write the payee**

In `gnucash_db.py` at line 2292, change the last parameter from `bill['vendor_name']` to `bill['check_payee']`:

```python
            """, (payment_txn_guid, usd_guid, check_number, date_posted, date_entered, bill['check_payee']))
```

- [ ] **Step 6: Run the payee tests to verify they pass**

Run: `uv run pytest tests/test_bill_workflow.py::TestCheckPayee -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Run the full bill-workflow suite for regressions**

Run: `uv run pytest tests/test_bill_workflow.py -v`
Expected: PASS — all existing tests still green (existing tests assert on date/splits, not on description equalling the vendor name, so they are unaffected).

- [ ] **Step 8: Commit**

```bash
git add gnucash_db.py tests/test_bill_workflow.py
git commit -m "feat: use vendor addr_name as check payee in post_bill and pay_bill"
```

---

### Task 3: Same fallback in the deprecated `create_posted_bill` path

**Files:**
- Modify: `gnucash_db.py` — vendor-name lookup at lines 2507-2511 and the description insert at line 2569
- Test: `tests/test_bill_workflow.py` (extend `TestCheckPayee`)

**Interfaces:**
- Consumes: `gnucash_db._effective_payee(...)` from Task 1.
- Produces: the deprecated `create_posted_bill` transaction `description` now uses the same payee fallback. No new public interface.

- [ ] **Step 1: Confirm the deprecated function's name and signature**

Run: `uv run python -c "import bill_processor.gnucash_db as g; import inspect; print([n for n in dir(g) if 'posted' in n.lower()])"`
Expected: prints the deprecated function name (e.g. `['create_posted_bill']`). Use that exact name in the test below (shown here as `create_posted_bill`).

- [ ] **Step 2: Write the failing test**

Add to class `TestCheckPayee` in `tests/test_bill_workflow.py`:

```python
    def test_deprecated_create_posted_bill_uses_addr_name(
        self, db_connection, test_vendor_guid, test_accounts, bill_data
    ):
        self._set_addr_name(db_connection, test_vendor_guid, "Deprecated Payee LLC")

        bill_guid = gnucash_db.create_posted_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date'],
        )
        post_txn_guid = self._post_txn_guid(db_connection, bill_guid)
        assert self._description(db_connection, post_txn_guid) == "Deprecated Payee LLC", \
            "Deprecated path should also honor addr_name as payee"
```

(If Step 1 shows a different function name or required parameters, adjust the call to match its real signature — it returns the bill GUID.)

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_bill_workflow.py::TestCheckPayee::test_deprecated_create_posted_bill_uses_addr_name -v`
Expected: FAIL — description equals the vendor name, not `"Deprecated Payee LLC"`.

- [ ] **Step 4: Modify the deprecated vendor lookup**

In `gnucash_db.py` replace lines 2507-2511:

```python
    # Get vendor name for transaction description
    with get_connection() as conn:
        cursor = conn.execute("SELECT name FROM vendors WHERE guid = ?", (vendor_guid,))
        vendor_row = cursor.fetchone()
        vendor_name = vendor_row['name'] if vendor_row else "Unknown Vendor"
```

with:

```python
    # Get payee for transaction description: addr_name ("Payment Address -> Name")
    # when set, else the vendor Company Name.
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT name, addr_name FROM vendors WHERE guid = ?", (vendor_guid,)
        )
        vendor_row = cursor.fetchone()
        if vendor_row:
            vendor_name = _effective_payee(vendor_row['addr_name'], vendor_row['name'])
        else:
            vendor_name = "Unknown Vendor"
```

(The local variable stays named `vendor_name` so the description insert at line 2569, `..., vendor_name`, needs no further change — it now carries the effective payee.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_bill_workflow.py::TestCheckPayee::test_deprecated_create_posted_bill_uses_addr_name -v`
Expected: PASS

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: PASS — no regressions across the suite.

- [ ] **Step 7: Commit**

```bash
git add gnucash_db.py tests/test_bill_workflow.py
git commit -m "feat: honor addr_name payee fallback in deprecated create_posted_bill"
```

---

## Notes for the implementer

- **Line numbers may drift** as you edit. Anchor on the surrounding code shown in each step (the `INSERT INTO transactions (...)` blocks and the `SELECT ... FROM vendors` block), not the raw line numbers.
- **No changes to address handling.** The printed address still resolves from the `gncOwner` slot → vendor address fields; do not touch that code.
- **Manual sanity check (optional, no automated test):** after implementation, a real vendor whose GnuCash "Payment Address → Name" differs from its Company Name will now print the address-name value as the check payee. This matches the 38 such vendors identified in the design spec. No migration is needed — vendors with an empty `addr_name` are unaffected.
- Reference docs: `docs/CHECK_PRINTING.md` and `docs/superpowers/specs/2026-07-13-check-payee-from-addr-name-design.md`.

# Check Number — Bill Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional check number field to web dashboard bill entry, stored in `transactions.num` in GnuCash.

**Architecture:** Five sequential tasks — DB layer first, then queue parsing, then queue I/O, then web routes, then UI. Each task has tests before implementation. Tasks are ordered by dependency: later tasks call earlier ones.

**Tech Stack:** Python, SQLite (via gnucash_db.py), FastAPI + HTMX, Jinja2 templates, pytest + FastAPI TestClient.

**Spec:** `docs/superpowers/specs/2026-03-23-check-number-bill-entry-design.md`

---

## Files Changed

| File | Action |
|---|---|
| `gnucash_db.py` | Modify — add `check_number` param to `pay_bill()` |
| `utils.py` | Modify — parse optional 5th field in `parse_input_line()` |
| `web/queue_io.py` | Modify — add `check_number` to `_format_bill_line()`, `add_bill()`, `update_bill()` |
| `web/app.py` | Modify — accept `check_number` in add/edit routes; read from bill dict in `_process_one_bill()` |
| `web/templates/bill_entry.html` | Modify — add Check # input field |
| `web/templates/partials/queued_bills.html` | Modify — add Check # column and inline edit field |
| `tests/test_bill_workflow.py` | Modify — add test for `check_number` stored in `transactions.num` |
| `tests/test_utils.py` | Modify — add tests for 5th field parsing |
| `tests/test_web_app.py` | Modify — add tests for check_number in add/edit routes |

---

## Task 1: `pay_bill()` — store check number in `transactions.num`

**Files:**
- Modify: `gnucash_db.py:2130-2135` (function signature)
- Modify: `gnucash_db.py:2252` (INSERT into transactions)
- Modify: `tests/test_bill_workflow.py`

The `transactions` INSERT currently hard-codes `''` for `num`. This task makes it use `check_number`.

- [ ] **Step 1: Write the failing test**

Add a new test method inside `class TestBillWorkflow` in `tests/test_bill_workflow.py`:

```python
def test_pay_bill_stores_check_number(self, db_connection, test_vendor_guid, test_accounts, bill_data):
    """check_number is written to transactions.num on the payment transaction."""
    import sqlite3
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
        check_number="1042",
    )
    conn = sqlite3.connect(str(db_connection))
    row = conn.execute(
        "SELECT num FROM transactions WHERE guid = ?", (payment_txn_guid,)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "1042"
```

- [ ] **Step 2: Run test to confirm it fails**

```
uv run pytest tests/test_bill_workflow.py::TestBillWorkflow::test_pay_bill_stores_check_number -v
```

Expected: `TypeError: pay_bill() got an unexpected keyword argument 'check_number'`

- [ ] **Step 3: Add `check_number` parameter to `pay_bill()`**

In `gnucash_db.py`, change the function signature from:

```python
def pay_bill(
    bill_guid: str,
    checking_account_guid: str,
    payment_date: date = None,
    memo: str = None,
    verify: bool = True
) -> str:
```

To:

```python
def pay_bill(
    bill_guid: str,
    checking_account_guid: str,
    payment_date: date = None,
    memo: str = None,
    check_number: str = "",
    verify: bool = True,
) -> str:
```

- [ ] **Step 4: Write `check_number` into `transactions.num`**

In `gnucash_db.py`, find the INSERT into `transactions` (around line 2252). Change:

```python
conn.execute("""
    INSERT INTO transactions (
        guid, currency_guid, num, post_date, enter_date, description
    ) VALUES (?, ?, '', ?, ?, ?)
""", (payment_txn_guid, usd_guid, date_posted, date_entered, bill['vendor_name']))
```

To:

```python
conn.execute("""
    INSERT INTO transactions (
        guid, currency_guid, num, post_date, enter_date, description
    ) VALUES (?, ?, ?, ?, ?, ?)
""", (payment_txn_guid, usd_guid, check_number, date_posted, date_entered, bill['vendor_name']))
```

- [ ] **Step 5: Run test to confirm it passes**

```
uv run pytest tests/test_bill_workflow.py::TestBillWorkflow::test_pay_bill_stores_check_number -v
```

Expected: PASS

- [ ] **Step 6: Run full test suite to confirm no regressions**

```
uv run pytest tests/ -q
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add gnucash_db.py tests/test_bill_workflow.py
git commit -m "feat: add check_number param to pay_bill(), stored in transactions.num"
```

---

## Task 2: `parse_input_line()` — parse optional 5th field

**Files:**
- Modify: `utils.py:48-109`
- Modify: `tests/test_utils.py`

`parse_input_line()` currently handles 4 comma-separated fields. This task adds an optional 5th field (`check_number`), defaulting to `""` when absent or blank. The returned dict gains a `check_number` key.

- [ ] **Step 1: Write failing tests**

Add a new test class in `tests/test_utils.py`:

```python
class TestParseInputLineCheckNumber:
    def test_five_field_line_parses_check_number(self):
        result = parse_input_line("Acme Electric, 150.50, January bill, 2026-03-15, 1042")
        assert result is not None
        assert result["check_number"] == "1042"

    def test_four_field_line_defaults_check_number_to_empty(self):
        result = parse_input_line("Acme Electric, 150.50, January bill, 2026-03-15")
        assert result is not None
        assert result["check_number"] == ""

    def test_five_field_line_blank_check_number_defaults_to_empty(self):
        result = parse_input_line("Acme Electric, 150.50, January bill, 2026-03-15, ")
        assert result is not None
        assert result["check_number"] == ""

    def test_check_number_can_be_non_numeric(self):
        result = parse_input_line("Acme Electric, 150.50, memo, 2026-03-15, EFT-99")
        assert result is not None
        assert result["check_number"] == "EFT-99"

    def test_existing_four_field_dict_keys_unchanged(self):
        result = parse_input_line("Acme Electric, 150.50, memo, 2026-03-15, 1042")
        assert result is not None
        assert "vendor_name" in result
        assert "amount" in result
        assert "memo" in result
        assert "date" in result
```

- [ ] **Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_utils.py::TestParseInputLineCheckNumber -v
```

Expected: `KeyError: 'check_number'` or `AssertionError`

- [ ] **Step 3: Update `parse_input_line()` to parse 5th field**

In `utils.py`, change the return dict and add 5th field parsing. Replace the section from the date parsing to the return statement:

```python
    # Parse date (optional)
    bill_date = date.today()
    if len(parts) > 3 and parts[3]:
        try:
            bill_date = datetime.strptime(parts[3], "%Y-%m-%d").date()
        except ValueError:
            # Try alternate formats
            for fmt in config.ALTERNATIVE_DATE_FORMATS:
                try:
                    bill_date = datetime.strptime(parts[3], fmt).date()
                    break
                except ValueError:
                    continue
            else:
                logger.warning(f"Invalid date '{parts[3]}', using today")

    # Parse check number (optional 5th field)
    check_number = parts[4].strip() if len(parts) > 4 else ""

    return {
        'vendor_name': vendor_name,
        'amount': amount,
        'memo': memo,
        'date': bill_date,
        'check_number': check_number,
    }
```

- [ ] **Step 4: Run new tests to confirm they pass**

```
uv run pytest tests/test_utils.py::TestParseInputLineCheckNumber -v
```

Expected: All 5 tests pass.

- [ ] **Step 5: Run full test suite to confirm no regressions**

```
uv run pytest tests/ -q
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add utils.py tests/test_utils.py
git commit -m "feat: parse optional check_number as 5th field in parse_input_line()"
```

---

## Task 3: `queue_io.py` — serialize check number in queue file

**Files:**
- Modify: `web/queue_io.py:44-77`

`_format_bill_line()`, `add_bill()`, and `update_bill()` gain a `check_number` parameter. When non-empty, it's appended as the 5th comma-separated field; when empty, it's omitted (no trailing comma). `read_queue()` needs no changes — it calls `parse_input_line()`, which already returns `check_number` after Task 2.

- [ ] **Step 1: Write failing tests for `_format_bill_line()`**

Add a new test class in `tests/test_web_app.py`:

```python
class TestFormatBillLine:
    def test_with_check_number_appends_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        from datetime import date
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15), "1042")
        assert result == "Acme Electric, 150.50, memo, 2026-03-15, 1042\n"

    def test_without_check_number_omits_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        from datetime import date
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15))
        assert result == "Acme Electric, 150.50, memo, 2026-03-15\n"

    def test_empty_check_number_omits_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        from datetime import date
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15), "")
        assert result == "Acme Electric, 150.50, memo, 2026-03-15\n"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_web_app.py::TestFormatBillLine -v
```

Expected: `TypeError` — `_format_bill_line()` does not yet accept `check_number`.

- [ ] **Step 3: Update `_format_bill_line()`**

In `web/queue_io.py`, replace:

```python
def _format_bill_line(vendor_name: str, amount: float, memo: str, bill_date: date) -> str:
    memo = memo.strip() or "no memo"
    return f"{vendor_name}, {amount:.2f}, {memo}, {bill_date.isoformat()}\n"
```

With:

```python
def _format_bill_line(vendor_name: str, amount: float, memo: str, bill_date: date, check_number: str = "") -> str:
    memo = memo.strip() or "no memo"
    base = f"{vendor_name}, {amount:.2f}, {memo}, {bill_date.isoformat()}"
    if check_number:
        return f"{base}, {check_number}\n"
    return f"{base}\n"
```

- [ ] **Step 4: Run `TestFormatBillLine` to confirm it passes**

```
uv run pytest tests/test_web_app.py::TestFormatBillLine -v
```

Expected: All 3 tests pass.

- [ ] **Step 5: Update `add_bill()`**

Replace:

```python
def add_bill(vendor_name: str, amount: float, memo: str, bill_date: date) -> None:
    """Append a bill to the queue file."""
    line = _format_bill_line(vendor_name, amount, memo, bill_date)
    config.BILLS_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.BILLS_INPUT_PATH, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info(f"Queued bill: {vendor_name} ${amount:.2f}")
```

With:

```python
def add_bill(vendor_name: str, amount: float, memo: str, bill_date: date, check_number: str = "") -> None:
    """Append a bill to the queue file."""
    line = _format_bill_line(vendor_name, amount, memo, bill_date, check_number)
    config.BILLS_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.BILLS_INPUT_PATH, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info(f"Queued bill: {vendor_name} ${amount:.2f}")
```

- [ ] **Step 6: Update `update_bill()`**

Replace:

```python
def update_bill(file_line_index: int, vendor_name: str, amount: float, memo: str, bill_date: date) -> bool:
    """Replace the bill at the given file line index with updated values."""
    lines = _read_raw_lines()
    if file_line_index < 0 or file_line_index >= len(lines):
        logger.warning(f"update_bill: line index {file_line_index} out of range (file has {len(lines)} lines)")
        return False
    lines[file_line_index] = _format_bill_line(vendor_name, amount, memo, bill_date)
    _write_raw_lines(lines)
    return True
```

With:

```python
def update_bill(file_line_index: int, vendor_name: str, amount: float, memo: str, bill_date: date, check_number: str = "") -> bool:
    """Replace the bill at the given file line index with updated values."""
    lines = _read_raw_lines()
    if file_line_index < 0 or file_line_index >= len(lines):
        logger.warning(f"update_bill: line index {file_line_index} out of range (file has {len(lines)} lines)")
        return False
    lines[file_line_index] = _format_bill_line(vendor_name, amount, memo, bill_date, check_number)
    _write_raw_lines(lines)
    return True
```

- [ ] **Step 7: Run full test suite to confirm no regressions**

```
uv run pytest tests/ -q
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add web/queue_io.py tests/test_web_app.py
git commit -m "feat: add check_number to queue_io format/add/update functions"
```

---

## Task 4: `web/app.py` — wire check number through routes

**Files:**
- Modify: `web/app.py:127-148` (`add_to_queue`)
- Modify: `web/app.py:162-219` (`_process_one_bill`)
- Modify: `web/app.py:262-285` (`edit_queue_item`)
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_web_app.py`:

```python
def test_add_bill_with_check_number(client, tmp_queue):
    response = client.post("/bills/queue", data={
        "vendor_name": "Acme Electric",
        "amount": "123.45",
        "memo": "Test bill",
        "bill_date": "2026-03-01",
        "check_number": "1042",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text()
    assert "1042" in content


def test_add_bill_without_check_number_omits_fifth_field(client, tmp_queue):
    response = client.post("/bills/queue", data={
        "vendor_name": "Acme Electric",
        "amount": "123.45",
        "memo": "Test bill",
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text().strip()
    # Should end with the date, no trailing comma
    assert content.endswith("2026-03-01")


def test_edit_bill_adds_check_number(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
    response = client.patch("/bills/queue/0", data={
        "vendor_name": "Acme Electric",
        "amount": "123.45",
        "memo": "test",
        "bill_date": "2026-03-01",
        "check_number": "2001",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text()
    assert "2001" in content


def test_edit_bill_clears_check_number(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01, 1042\n")
    response = client.patch("/bills/queue/0", data={
        "vendor_name": "Acme Electric",
        "amount": "123.45",
        "memo": "test",
        "bill_date": "2026-03-01",
        "check_number": "",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text().strip()
    assert "1042" not in content
    assert content.endswith("2026-03-01")
```

- [ ] **Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_web_app.py::test_add_bill_with_check_number tests/test_web_app.py::test_add_bill_without_check_number_omits_fifth_field tests/test_web_app.py::test_edit_bill_adds_check_number tests/test_web_app.py::test_edit_bill_clears_check_number -v
```

Expected: All 4 fail (check_number not in file / trailing comma present).

- [ ] **Step 3: Update `add_to_queue` route**

In `web/app.py`, add `check_number` to the `add_to_queue` function signature and pass it through:

```python
@app.post("/bills/queue", response_class=HTMLResponse)
def add_to_queue(
    request: Request,
    vendor_name: str = Form(...),
    amount: float = Form(...),
    memo: str = Form(""),
    bill_date: str = Form(""),
    check_number: str = Form(""),
):
    """Add a bill to the queue and return refreshed bill entry form."""
    if not vendor_name.strip():
        return HTMLResponse('<p class="error-msg">Vendor name is required.</p>', status_code=200)
    if amount <= 0:
        return HTMLResponse('<p class="error-msg">Amount must be greater than zero.</p>', status_code=200)
    try:
        parsed_date = date.fromisoformat(bill_date) if bill_date else date.today()
    except ValueError:
        parsed_date = date.today()
    queue_io.add_bill(vendor_name, amount, memo, parsed_date, check_number)
    return templates.TemplateResponse(request, "bill_entry.html", {
        "today": date.today().isoformat(),
        "success": f"Added {vendor_name} ${amount:.2f} to queue",
    })
```

- [ ] **Step 4: Update `edit_queue_item` route**

In `web/app.py`, add `check_number` to the `edit_queue_item` function and pass it through:

```python
@app.patch("/bills/queue/{index}", response_class=HTMLResponse)
def edit_queue_item(
    request: Request,
    index: int,
    vendor_name: str = Form(...),
    amount: float = Form(...),
    memo: str = Form(""),
    bill_date: str = Form(""),
    check_number: str = Form(""),
):
    """Update a queued bill and return refreshed queue card."""
    if not vendor_name.strip():
        return HTMLResponse('<p class="error-msg">Vendor name is required.</p>', status_code=200)
    if amount <= 0:
        return HTMLResponse('<p class="error-msg">Amount must be greater than zero.</p>', status_code=200)
    try:
        parsed_date = date.fromisoformat(bill_date) if bill_date else date.today()
    except ValueError:
        parsed_date = date.today()
    ok = queue_io.update_bill(index, vendor_name, amount, memo, parsed_date, check_number)
    queue = queue_io.read_queue()
    return templates.TemplateResponse(request, "partials/queued_bills.html", {
        "queue": queue,
        "last_error": None if ok else f"Could not update bill at index {index}",
    })
```

- [ ] **Step 5: Update `_process_one_bill()` to pass check_number to `pay_bill()`**

In `web/app.py`, find the `pay_bill(...)` call inside `_process_one_bill()` and add `check_number`:

```python
        gnucash_db.pay_bill(
            bill_guid=bill_guid,
            checking_account_guid=checking_guid,
            payment_date=bill_date,
            memo=bill.get("memo", ""),
            check_number=bill.get("check_number", ""),
        )
```

- [ ] **Step 6: Run new tests to confirm they pass**

```
uv run pytest tests/test_web_app.py::test_add_bill_with_check_number tests/test_web_app.py::test_add_bill_without_check_number_omits_fifth_field tests/test_web_app.py::test_edit_bill_adds_check_number tests/test_web_app.py::test_edit_bill_clears_check_number -v
```

Expected: All 4 pass.

- [ ] **Step 7: Run full test suite to confirm no regressions**

```
uv run pytest tests/ -q
```

Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add web/app.py tests/test_web_app.py
git commit -m "feat: wire check_number through web routes and _process_one_bill()"
```

---

## Task 5: Web UI — add Check # field to form and queue table

**Files:**
- Modify: `web/templates/bill_entry.html`
- Modify: `web/templates/partials/queued_bills.html`

No automated tests for HTML templates — verify manually by running the server and inspecting the UI.

- [ ] **Step 1: Add Check # input to `bill_entry.html`**

In `web/templates/bill_entry.html`, add the Check # field after the Date input and before the submit button div:

```html
  <label for="date-input">Date</label>
  <input type="date" name="bill_date" id="date-input" value="{{ today }}">

  <label for="check-number-input">Check #</label>
  <input type="text" name="check_number" id="check-number-input" placeholder="optional" style="width:8rem">

  <div style="margin-top:1rem">
    <button type="submit" class="btn-primary">Add to Queue</button>
  </div>
```

- [ ] **Step 2: Add Check # column to queue table header in `queued_bills.html`**

In `web/templates/partials/queued_bills.html`, change:

```html
      <thead><tr><th>Vendor</th><th>Amount</th><th>Memo</th><th>Date</th><th></th></tr></thead>
```

To:

```html
      <thead><tr><th>Vendor</th><th>Amount</th><th>Memo</th><th>Date</th><th>Check #</th><th></th></tr></thead>
```

- [ ] **Step 3: Add Check # cell and inline edit form to each queue table row in `queued_bills.html`**

The current template has no inline edit mechanism — each row only has Process and Remove buttons. This step adds a Check # display cell and a new inline edit form (per row) that submits all 5 fields via PATCH. The hidden fields for vendor_name, amount, memo, and bill_date carry the current row values so the full replacement write in `update_bill()` works correctly.

Find this block:

```html
        <tr>
          <td>{{ bill.vendor_name }}</td>
          <td>${{ "%.2f"|format(bill.amount) }}</td>
          <td>{{ bill.memo }}</td>
          <td>{{ bill.date }}</td>
          <td>
            <button hx-post="/bills/queue/{{ bill._index }}/process"
                    hx-target="#queued-bills"
                    hx-swap="outerHTML">Process</button>
            <button hx-delete="/bills/queue/{{ bill._index }}"
                    hx-target="#queued-bills"
                    hx-swap="outerHTML"
                    hx-confirm="Remove this bill from the queue?">Remove</button>
          </td>
        </tr>
```

Replace with:

```html
        <tr>
          <td>{{ bill.vendor_name }}</td>
          <td>${{ "%.2f"|format(bill.amount) }}</td>
          <td>{{ bill.memo }}</td>
          <td>{{ bill.date }}</td>
          <td>{{ bill.check_number }}</td>
          <td>
            <button hx-post="/bills/queue/{{ bill._index }}/process"
                    hx-target="#queued-bills"
                    hx-swap="outerHTML">Process</button>
            <button hx-delete="/bills/queue/{{ bill._index }}"
                    hx-target="#queued-bills"
                    hx-swap="outerHTML"
                    hx-confirm="Remove this bill from the queue?">Remove</button>
            <form style="display:inline"
                  hx-patch="/bills/queue/{{ bill._index }}"
                  hx-target="#queued-bills"
                  hx-swap="outerHTML">
              <input type="hidden" name="vendor_name" value="{{ bill.vendor_name }}">
              <input type="hidden" name="amount" value="{{ bill.amount }}">
              <input type="hidden" name="memo" value="{{ bill.memo }}">
              <input type="hidden" name="bill_date" value="{{ bill.date }}">
              <input type="text" name="check_number" value="{{ bill.check_number }}"
                     placeholder="Check #" style="width:5rem">
              <button type="submit">Save</button>
            </form>
          </td>
        </tr>
```

- [ ] **Step 4: Manual smoke test**

Start the server:
```
uv run uvicorn bill_processor.web.app:app --reload --port 7432
```

Open `http://localhost:7432` and verify:
1. The add-bill form shows a "Check #" field after the Date field
2. Adding a bill with a check number shows it in the queue table
3. Adding a bill without a check number works normally (blank Check # column)
4. The inline Check # input on each queue row saves when submitted
5. Clearing a check number via the inline form removes it from the file

- [ ] **Step 5: Run full test suite one final time**

```
uv run pytest tests/ -q
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add web/templates/bill_entry.html web/templates/partials/queued_bills.html
git commit -m "feat: add Check # field to bill entry form and queue table"
```

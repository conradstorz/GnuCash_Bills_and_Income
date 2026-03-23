# Check Number — Bill Entry Design Spec
**Date:** 2026-03-23
**Scope:** Add an optional check number field to web dashboard bill entry, flowing through the queue file and 3-step workflow into `transactions.num` in GnuCash.

---

## Background

Bills are entered via the web dashboard and queued in `data/bills_to_process.txt`. Processing runs the 3-step workflow: `create_bill()` → `post_bill()` → `pay_bill()`. The payment transaction has a `transactions.num` column (the standard GnuCash check number field) that is currently always written as `""`.

Users print checks in a batch run and only learn check numbers after the print run. Check number entry is therefore optional at queue time and optional at process time — most bills will be processed with no check number.

---

## Interfaces in Scope

Web dashboard only. Tkinter GUIs (`bill_entry_gui.py`, `vendor_manager_gui.py`) are out of scope and scheduled for removal.

---

## Data Flow

```
Add bill form (web)
  └─ POST /bills/queue  →  queue_io.add_bill()  →  bills_to_process.txt (5th field, omitted if blank)
                                                           │
                               PATCH /bills/queue/{i}  ───┘  (edit check number + all other fields)
                                                           │
                               POST /bills/queue/process   ┘
                               POST /bills/queue/{i}/process
                                   └─ _process_one_bill(bill_dict)
                                         └─ pay_bill(check_number=bill_dict.get("check_number", ""))
                                               └─ transactions.num
```

---

## Queue File Format

Fifth field added, optional:

```
Vendor Name, Amount, Memo, Date, CheckNumber
```

**Examples:**
```
Acme Electric, 150.50, January bill, 2026-03-15, 1042
Bob's Plumbing, 200.00, no memo, 2026-03-20
```

- When `check_number` is non-empty, it is appended as the 5th field.
- When `check_number` is empty, the field is **omitted entirely** (no trailing comma).
- Existing 4-field lines are fully backward-compatible — parsed `check_number` defaults to `""`.

---

## Files Changed

| File | Change |
|---|---|
| `gnucash_db.py` | Add `check_number: str = ""` param to `pay_bill()`; write to `transactions.num` |
| `utils.py` | Update `parse_input_line()` to parse optional 5th field as `check_number` |
| `web/queue_io.py` | Update `_format_bill_line()`, `add_bill()`, `update_bill()` to handle `check_number` |
| `web/app.py` | Accept `check_number` in `POST /bills/queue` and `PATCH /bills/queue/{index}`; `_process_one_bill()` reads it from bill dict |
| `web/templates/bill_entry.html` | Add optional "Check #" input to add-bill form and queue table column |

---

## Section Details

### 1. `gnucash_db.pay_bill()`

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

`check_number` is written to `transactions.num`. When blank, behavior is identical to current (empty string). No other DB tables are affected.

### 2. `utils.parse_input_line()`

Parses the 5th comma-separated field as `check_number`. Returns a dict with a new `check_number` key (defaults to `""` when the field is absent or blank). The existing 4-field contract is unchanged.

### 3. `web/queue_io.py`

- **`_format_bill_line()`** gains a `check_number: str = ""` parameter. When non-empty, appends `, {check_number}` to the line. When empty, the line ends after the date — no trailing comma.
- **`add_bill()`** gains `check_number: str = ""` and passes it to `_format_bill_line()`.
- **`update_bill()`** gains `check_number: str = ""` and passes it to `_format_bill_line()`. The PATCH route always sends all 5 fields, so an empty `check_number` in a PATCH request overwrites an existing value with `""` (clearing it).

### 4. `web/app.py`

- **`POST /bills/queue`** — accepts optional `check_number: str = Form("")` and passes to `queue_io.add_bill()`.
- **`PATCH /bills/queue/{index}`** — accepts optional `check_number: str = Form("")` alongside the existing fields (vendor_name, amount, memo, bill_date); passes all 5 to `queue_io.update_bill()`. Submits all fields together (full replacement), consistent with the existing edit pattern.
- **`_process_one_bill(bill: dict)`** — no signature change. Reads `check_number` from the bill dict via `bill.get("check_number", "")` and passes to `pay_bill()`. Both call sites (`process_all` and `process_one`) pass the bill dict from `read_queue()`, so both automatically propagate `check_number`.

### 5. Web UI (`bill_entry.html`)

- **Add form:** Narrow "Check #" text input placed after the Date field. Optional, no validation, submits with the rest of the form.
- **Queue table:** New "Check #" column (narrow). The existing inline edit action submits all fields (vendor, amount, memo, date, check_number) together via PATCH. Blank for most rows.

---

## Error Handling

- Non-numeric check numbers are accepted — GnuCash stores `transactions.num` as text.
- No validation on format or uniqueness.
- If `check_number` is absent from a form POST, it defaults silently to `""`.

---

## Out of Scope

- Auto-assignment of check numbers.
- Tkinter GUI changes.
- Validation of check number format or uniqueness.
- Displaying or searching processed bills by check number.

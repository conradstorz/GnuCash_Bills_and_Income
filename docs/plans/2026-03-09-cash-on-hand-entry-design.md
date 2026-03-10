# Cash-on-Hand Entry Feature Design

**Date:** 2026-03-09
**Status:** Approved

## Overview

Add a cash-on-hand batch entry panel to the existing web dashboard. Users collect client cash payments throughout the day and enter them all at once as a single GnuCash transaction against the `SAMUSE Cash-on-hand` account. An optional independent bank deposit transaction can be submitted at the same time.

---

## Context & Constraints

- The existing bills panel occupies the full dashboard. The new panel will sit **side-by-side** with it in a split-screen layout (bills left, cash-on-hand right).
- All existing database safety patterns **must be honored without exception**, including:
  - GnuCash lock record check before any write
  - Stale PID detection (if locked, verify the locking process is still alive)
  - Live lock → block submission, show user who holds the lock
  - Stale lock → still block submission, warn the user (do not auto-clear)
  - `WriteVerificationError` on every insert
  - Rollback / no partial writes

---

## Data Model

### GnuCash Transactions

**Batch transaction** (one per submission):
- One transaction with N+1 splits
- N splits: one per line item, each against a different income/asset/cash account
- 1 auto-calculated split: `SAMUSE Cash-on-hand` = negative sum of all line item amounts (the balancing entry — never entered by the user)
- All splits share the batch date

**Deposit transaction** (optional, independent):
- Separate two-split transaction: `SAMUSE Cash-on-hand` debit/credit + selected bank account credit/debit
- Date is typically next day (user-editable)
- Amount is independent of the batch total — SAMUSE operates as a petty cash drawer with a fluctuating balance

### Supporting Data Files

**`data/clients.json`** — client name list for memo autocomplete (15–45 names):
```json
{ "clients": ["Client A", "Client B"] }
```

**`data/cash_accounts.json`** — the 5–10 accounts available in the line item account dropdown, seeded once from GnuCash:
```json
{
  "accounts": [
    { "name": "Service Income", "guid": "..." },
    { "name": "Coins Fund", "guid": "..." }
  ]
}
```

Accounts are seeded manually (or via a one-time setup command) and rarely change. No runtime GnuCash account query needed.

---

## UI Layout

Split-screen dashboard: bills panel on the left, cash-on-hand panel on the right at equal width.

**Cash-on-hand panel:**

```
┌─────────────────────────────────────┐
│  Cash Entry          Date: [______] │
├─────────────────────────────────────┤
│  Account ▼    Memo ░░░    Amount    │
│  [________] [________] [______] [✕] │
│  [________] [________] [______] [✕] │
│  [________] [________] [______] [✕] │
│                        [+ Add Row]  │
├─────────────────────────────────────┤
│            SAMUSE Total:  $  xxx.xx │
├─────────────────────────────────────┤
│  □ Bank Deposit                     │
│    Bank [________] Amount [______]  │
│    Date [______]                    │
├─────────────────────────────────────┤
│                       [Submit All]  │
└─────────────────────────────────────┘
```

- **Date** defaults to today, editable
- **Line item rows** added/removed dynamically via HTMX (no page reload)
- **SAMUSE Total** updates live as amounts are typed (client-side JS sum)
- **Bank Deposit** section hidden until checkbox is ticked; deposit date defaults to tomorrow
- **Submit All** creates 1 batch transaction (+ 1 deposit transaction if checked), then clears the form on success
- Amounts may be positive (cash in) or negative (cash out, e.g. coins fund transfers)

---

## Backend Design

### New functions in `gnucash_db.py`

Follows existing patterns: `generate_guid()`, amount-as-cents, `format_gnucash_date()`, `verify_record_exists()`, `WriteVerificationError`.

| Function | Purpose |
|----------|---------|
| `get_samuse_account_guid()` | Look up `SAMUSE Cash-on-hand` account guid from GnuCash; cached after first call |
| `get_cash_accounts()` | Load account list from `data/cash_accounts.json` |
| `create_cash_entry(date, line_items, memo)` | Create N+1 split transaction; `line_items` = list of `{account_guid, memo, amount}` |
| `create_cash_deposit(date, bank_account_guid, amount)` | Create two-split deposit transaction |

### New FastAPI routes in `web/app.py`

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/cash` | Render cash-on-hand panel partial |
| POST | `/cash/submit` | Lock check → create transaction(s) → return cleared form or error |
| GET | `/cash/add-row` | Return a blank line item row partial (HTMX) |
| GET | `/clients/search` | Return autocomplete suggestions from `clients.json` |

### Shared with bills side (no duplication)

`get_connection()`, `generate_guid()`, `format_gnucash_date()`, `format_gnucash_timestamp()`, `verify_record_exists()`, `WriteVerificationError`, and the DB lock check / stale PID detection function.

---

## Workflow

### Happy Path

1. User opens dashboard; right panel loads with today's date and one blank row
2. User fills in line items (account, memo, amount); SAMUSE Total updates live
3. User optionally ticks Bank Deposit and fills in bank account, amount, date
4. User clicks Submit All
5. Server performs lock check — if clear, proceeds
6. Batch transaction created and verified
7. If deposit checked: deposit transaction created and verified
8. Form clears; success message shows SAMUSE total posted (and deposit amount if applicable)

### Error Handling

| Condition | Behavior |
|-----------|----------|
| DB locked by live PID | Show lock holder info inline, block submission |
| DB locked by stale PID | Warn user, block submission (do not auto-clear lock) |
| Empty line items on submit | Client-side validation blocks submission |
| Incomplete row (missing field) | Client-side validation blocks submission |
| Batch write fails / `WriteVerificationError` | Show error inline; deposit never attempted |
| Deposit write fails | Show error inline; batch already committed (reported separately) |

---

## Out of Scope (Initial Release)

- UI for managing `clients.json` (edit the file directly; list changes rarely)
- UI for managing `cash_accounts.json` (seed once via setup step)
- Viewing/editing past cash entries
- Reconciliation support

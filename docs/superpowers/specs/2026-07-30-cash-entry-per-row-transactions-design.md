# Cash Entry: One Transaction Per Row — Design

**Date:** 2026-07-30
**Status:** Approved (pending spec review)

## Problem

The web dashboard's cash-entry panel lets the user record several cash movements
in a single submit session (revenue collected from machines, plus internal
"changer" petty-cash moves). Today, `create_cash_entry()` writes **all** rows from
one submit into a **single** GnuCash transaction: one balancing split to
SAMUSE Cash-on-hand plus one split per row.

Because a GnuCash account register shows every transaction touching that account
*and* displays all sibling splits of that transaction, any account used in the
batch (e.g. the "Dollar bill changers" petty-cash account) shows a transaction
whose split detail includes unrelated money from the other rows. This creates
confusion in registers where that money does not belong.

The changer moves are not income or expense — they are asset-to-asset transfers
that conceptually always pass through Cash-on-hand. The user wants to keep
entering all rows in one session (all the data is captured at once), but have the
code write them into the database as cleanly separated transactions.

## Decision

Change `create_cash_entry()` so that **each line item becomes its own GnuCash
transaction** with exactly two splits: the row's account and SAMUSE Cash-on-hand.
Every transaction balances on its own and never shares a transaction with any
other row. This gives a clean break between the source of each cash movement and
every other movement — nothing appears as a sibling split in a register where it
does not belong.

The user explicitly accepted the trade-off that daily revenue will no longer
appear as one grouped entry in the Cash-on-hand register; each revenue machine
becomes its own transaction on that date.

### Alternatives considered

- **Income grouped, each transfer separate.** Keeps income as one transaction and
  isolates each transfer. Rejected: the user wants total isolation, with the
  source of coins "moot" and never visible in another register.
- **Income transaction + one combined transfer transaction.** Rejected: reintroduces
  cross-contamination between two transfer/asset accounts.

## Before / After

**Before** — one transaction, N+1 splits:

```
Txn: Cash-on-hand +$300 / Machine A -$100 / Machine B -$120 / Changer -$80
```

**After** — N transactions, 2 splits each:

```
Txn 1: Cash-on-hand +$100 / Machine A income  -$100
Txn 2: Cash-on-hand +$120 / Machine B income  -$120
Txn 3: Cash-on-hand  -$80 / Changer (petty)   +$80
```

## Changes

### `gnucash_db.py` — `create_cash_entry(entry_date, line_items, description="", verify=True)`

- Loop over `line_items`. For each row, create one transaction with two splits:
  - the row's account: value/quantity = `-amount` (in cents)
  - SAMUSE Cash-on-hand: value/quantity = `+amount` (in cents)
- **Sign convention unchanged:** positive `amount` = cash into Cash-on-hand.
  Each transaction balances on its own (the two splits sum to zero); the previous
  whole-batch balance check becomes a trivially-true per-transaction check.
- **Transaction description** = the row's `memo`. If the row's memo is empty/blank,
  fall back to `settings.default_memo`. The memo is also retained on the row's
  own split (as today).
- **Return type** changes from `str` to `list[str]` — one transaction GUID per row,
  in input order.
- **Verification** (when `verify=True`) runs per transaction: verify the
  transaction record and both of its splits exist.
- The existing lock check (`is_locked_by_others`) runs once up front, unchanged.
- All rows are written under a single DB connection/commit so the submit remains
  atomic (all rows succeed or the operation raises before commit).

The `description` parameter is retained for backward compatibility but is no
longer the transaction-level description for the batch; per-row memos drive each
transaction's description. (No current caller passes a non-default `description`.)

### `web/app.py` — `POST /api/cash/submit`

- Adapt to the `list[str]` return value.
- Response shape keeps the fields the frontend reads (`ok`, `total`) and reports
  the per-row detail:

  ```python
  result["batch"] = {
      "ok": True,
      "total": total,
      "count": len(guids),
      "guids": guids,
  }
  ```

- Memo-history saving (`cash_io.save_memo_to_history`) is unchanged.
- Logging updated to report the number of transactions created.

### Frontend (`frontend/src/pages/CashEntry.tsx`, `frontend/src/api/cash.ts`)

- **No change required.** The page reads only `res.batch.ok` and
  `res.batch.total`, both preserved. (`guids`/`count` are additive.)

### Deposit path

- `create_cash_deposit()` and `POST /api/cash/deposit` are untouched — a deposit is
  already its own transaction.

## Testing

Update `tests/test_cash_entry.py` and `tests/test_cash_web.py`:

- A submit with N rows creates **N transactions**, each with **exactly 2 splits**.
- Each transaction balances (splits sum to zero) and has correct signs:
  Cash-on-hand `+amount`, row account `-amount`.
- Each transaction's non-Cash-on-hand split points at the correct row account,
  and the SAMUSE leg is present in every transaction.
- Each transaction's description equals the row memo (or `settings.default_memo`
  when the row memo is blank).
- **Isolation case:** a submit mixing income rows and a changer row produces a
  changer transaction whose splits are **only** the changer account and
  Cash-on-hand — no income splits present.
- `create_cash_entry` returns a list of GUIDs of length N.
- Web-layer test asserts the `/api/cash/submit` response still exposes
  `batch.ok` and `batch.total`, plus `batch.count == N`.

## Out of Scope

- Un-tangling the already-posted mixed transaction from prior entry. Handled
  separately (manually in GnuCash or a one-off script) once the user decides.
- Any "transfer between two non-Cash-on-hand buckets" entry mode — unnecessary,
  since all moves route through Cash-on-hand.

# Design: Check Payee from Vendor `addr_name`

**Date:** 2026-07-13
**Status:** Approved (design), pending implementation plan

## Problem

The payee printed on a check is taken verbatim from the payment transaction's
`description` field (see `docs/CHECK_PRINTING.md`). Today the tool always sets
that `description` to the vendor's GnuCash **Company Name** (`vendors.name`).

That couples the printed payee to the vendor's *internal, searchable label*. For
many real vendors the two should differ: the label used for bookkeeping and
lookup is not the legal entity the check must be payable to. Examples already
present in the live database:

| `vendors.name` (internal label) | `vendors.addr_name` (real payee) |
|---|---|
| Bullet County Taxes KY | Bullet County Sheriff |
| Pace-o-Matic Corporation | PoM of Kentucky LLC |
| AMOA | Amusement Music Operators America |
| Floyd County Treasurer | Floyd County Government |

The user wants to **decouple the check payee from the vendor name**, store the
override **in the GnuCash database vendor record**, and edit it in **GnuCash's
native vendor editor**.

## Key insight

GnuCash's vendor editor already exposes a **"Payment Address → Name"** field,
which maps to the existing `vendors.addr_name` column. The user has already been
populating it with the real "pay to the order of" name for the vendors that need
it — that value simply never reached the check, because the payee is derived from
`description` (= `vendors.name`), not from `addr_name`.

So no new field, schema change, or KVP slot is required. We repurpose an existing,
natively-editable, already-curated column as the payee source.

## Solution

**Rule:** the check payee (transaction `description`) =
`vendors.addr_name` when it is non-empty (after trimming whitespace), otherwise
fall back to `vendors.name`.

```
effective_payee = addr_name.strip() if addr_name and addr_name.strip() else name
```

This applies wherever the tool currently writes the vendor name into a transaction
`description` — both the posting (Accounts Payable) transaction and the payment
transaction.

### Why the fallback is self-migrating

Measured against the live database (334 vendors):

| Condition | Count | Effect on printed payee |
|---|---:|---|
| `addr_name` empty | 285 | Falls back to `name` — **no change** |
| `addr_name == name` | 11 | Same value — **no change** |
| `addr_name` differs from `name` | 38 | Now prints `addr_name` — **the intended fix** |

No migration script or data backfill is needed. The fallback rule produces correct
behavior for every existing vendor. The only behavioral change is the 38 vendors
whose checks begin printing their `addr_name` — which is the explicit goal.

## Scope of changes

All changes are localized to `gnucash_db.py`.

1. **`get_invoice_by_guid()`** (~line 1742) — add `v.addr_name` to the vendor JOIN
   and expose a new key on the returned bill dict:
   `bill['check_payee'] = (addr_name or '').strip() or vendor_name`.
   `bill['vendor_name']` keeps its current meaning (the Company Name) and continues
   to be used for logging and any UI/return values — it is **not** changed.

2. **`post_bill()`** (line 2055) — write `bill['check_payee']` into the posting
   transaction `description` instead of `bill['vendor_name']`.

3. **`pay_bill()`** (line 2292) — write `bill['check_payee']` into the payment
   transaction `description` instead of `bill['vendor_name']`. (This is the
   transaction checks are printed from.)

4. **`create_posted_bill` (deprecated)** (~line 2507) — apply the same
   `addr_name`-or-`name` fallback to its local `vendor_name` lookup, so the
   deprecated path does not silently diverge from the supported one.

### Explicitly unchanged

- **Address block resolution.** The printed address still resolves from the
  `gncOwner` KVP slot on the transaction → the vendor's address fields (including
  `addr_name`). Because the payee now also comes from `addr_name`, the payee line
  and the mailing-address name line **match** — the desired result on a check.
- **`vendors.name`** — remains the internal, searchable label; untouched.
- **App-side editing.** Editing is done in GnuCash's native vendor editor. No
  changes to the app's vendor manager UI. The app already stores `addr_name` in
  `data/vendor_database.json` via vendor sync, so it stays consistent.

## Data flow (after change)

```
GnuCash vendor record
  ├── name       ── internal label (search, lists, logs)  ── unchanged
  └── addr_name  ── "Payment Address → Name"
                       │
                       ▼
            effective_payee = addr_name.strip() or name
                       │
        ┌──────────────┴───────────────┐
        ▼                              ▼
  post_bill: AP txn.description   pay_bill: payment txn.description
                                         │
                                         ▼
                                 Printed check PAYEE line

  Printed check ADDRESS block ◀── gncOwner slot ── vendor addr fields (incl. addr_name)
```

## Error handling / edge cases

- `addr_name` is `NULL` → treated as empty → fall back to `name`.
- `addr_name` is whitespace-only → trimmed to empty → fall back to `name`.
- `name` itself missing (vendor row not found) → existing behavior is preserved
  (e.g. the deprecated path already uses `"Unknown Vendor"`); the fallback does not
  introduce a new failure mode.

## Testing

Add tests (extending the existing `test_bill_workflow` suite) that assert the
`description` written to the transaction:

1. **`addr_name` populated and distinct** → transaction `description` equals
   `addr_name` (not `name`). Verify for both the posting and payment transactions.
2. **`addr_name` empty/NULL** → transaction `description` equals `name`.
3. **`addr_name` whitespace-only** → transaction `description` equals `name`
   (fallback), confirming the trim.

Tests operate on the temporary DB copy per `tests/conftest.py` fixtures; set
`addr_name` on the test vendor to exercise each branch.

## Out of scope (YAGNI)

- No UI in the app for editing `addr_name` (native GnuCash editor is the intended
  editor).
- No JSON-schema or sync changes — `addr_name` already round-trips.
- No new KVP slot, no new column, no migration script.
- No changes to how the address block is populated.

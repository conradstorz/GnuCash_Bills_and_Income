# How GnuCash Prints Checks (Payee & Address)

This document records the verified facts about how a printed check gets its
**payee name** and **vendor address** when checks are produced from the GnuCash
check register. Understanding this is central to the project, because printing a
check with an auto-filled address is one of the primary reasons the tool creates
bills as *invoices* rather than plain register transactions.

All statements below are grounded in the project's own source code and in
findings recorded during development (see the "Evidence" pointers).

---

## TL;DR

1. **The check PAYEE = the transaction's `description` field**, taken essentially
   verbatim. In the register this is the "Description" column.
2. **The `description` is plain free text.** This project *writes the vendor name
   into it* at posting/payment time — it is a populated value, **not** a
   live-linked field that auto-updates from the vendor record. Edit the
   description in the register and the printed payee changes.
3. **The vendor ADDRESS travels by a different path.** GnuCash's "Print Check"
   dialog resolves the address from a **`gncOwner` KVP slot on the transaction**,
   not from the description. Name and address are two independent mechanisms.
4. **The memo does NOT become the payee.** The memo is stored as the invoice
   `notes` / a transaction `notes` slot — never the description.
5. **The check number** is stored in the transaction's `num` field.

---

## The two independent paths

```
Printed check
├── PAYEE NAME  ◀── transactions.description   (free text; we set it = vendor name)
└── ADDRESS     ◀── gncOwner KVP slot on the transaction  (owner-type=4 vendor, owner-guid)
```

If the `gncOwner` slot is missing from the transaction, **the name still prints
correctly but the address is blank.** This exact failure mode was observed and
fixed in this project (older `pay_bill()` versions attached `gncOwner` only to the
*lot*, not to the transaction).

> Evidence: `repair_payment_gncowner.py` docstring —
> *"GnuCash's 'Print Check' dialog resolves the vendor address by reading
> `gncOwner` from the transaction's own KVP slots. Without it the vendor name
> prints correctly (from transactions.description) but the address is blank."*

---

## How this project fills those fields

The tool implements a 3-step workflow (`gnucash_db.py`). The relevant field
writes are:

### 1. `create_bill()`
Creates the **unposted** invoice record and its entry. Stores the **memo** in the
invoice `notes`. No register transaction exists yet, so there is no payee/description
at this stage.

### 2. `post_bill()`
Creates the Accounts Payable transaction (`trans-txn-type = 'I'`).

- `transactions.description` ← **`bill['vendor_name']`**  ·  *Evidence: `gnucash_db.py:2055`*

### 3. `pay_bill()`
Creates the payment transaction from the checking account (`trans-txn-type = 'P'`).
**This is the transaction a check is printed from.**

- `transactions.description` ← **`bill['vendor_name']`** → becomes the check PAYEE
  ·  *Evidence: `gnucash_db.py:2292`*
- `transactions.num` ← **`check_number`**  ·  *Evidence: `gnucash_db.py:2292`*
- `gncOwner` KVP slots (owner-type = 4 = vendor, owner-guid = vendor GUID) are
  attached **to the transaction itself** → enables the check's address lookup
  ·  *Evidence: `gnucash_db.py:2308-2324`, comment "CRITICAL for check printing!"*
- The memo, if provided, is stored as a `notes` slot — **not** the description
  ·  *Evidence: `gnucash_db.py:2302-2306`*

An explicit code comment records the design intent:

> `gnucash_db.py:2563` — *"Create the transaction (description should be VENDOR
> NAME, not memo)"*

---

## Common misconception, corrected

> "The description line seems to be derived automatically from the name of the vendor."

**Functionally true, mechanically no.** GnuCash does not maintain a live link that
copies the vendor name into the description. Rather:

- GnuCash's native business "Process Payment" routine *fills* the payment
  transaction's description with the owner (vendor) name at creation time, which
  makes it *look* automatic.
- This project reproduces that behavior by **explicitly writing** `vendor_name`
  into `transactions.description`.

Consequence: the description is a snapshot, not a link. If the vendor is later
renamed, existing transactions keep the old description (and thus the old printed
payee) until edited. Conversely, hand-editing the description in the register will
change the printed payee without touching the vendor record.

---

## Field-to-check mapping (reference)

| Check element | GnuCash source | Set by this project to | Code |
|---|---|---|---|
| Payee name | `transactions.description` | vendor name | `gnucash_db.py:2055`, `:2292` |
| Vendor address | `gncOwner` KVP slot on the transaction | vendor GUID (owner-type 4) | `gnucash_db.py:2308-2324` |
| Check number | `transactions.num` | `check_number` arg | `gnucash_db.py:2292` |
| Memo / notes | invoice `notes` / txn `notes` slot | memo arg | `gnucash_db.py:2302-2306` |

---

## Related repair tooling

`repair_payment_gncowner.py` — one-time script that backfills the `gncOwner`
transaction slot on payment transactions created by older `pay_bill()` versions,
restoring the address on printed checks. Run with `--apply` to fix, or without
flags for a safe dry run.

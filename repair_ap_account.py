#!/usr/bin/env python3
"""
repair_ap_account.py
====================
One-time repair script: corrects bills that were posted/paid against the wrong
Accounts Payable account.

Bills B-0025 through B-0030 were processed with ``ap_account_guid`` pointing to
"SAMUSE Product Sales" (account_type=INCOME) instead of "Payables (SAMUSE)"
(account_type=PAYABLE).  GnuCash's check-print dialog resolves the vendor
address by walking the AP split to its PAYABLE account — it silently produces
a blank address if the split is against any other account type.

For each affected bill this script updates:
  1. ``invoices.post_acc``              — the posted AP account on the invoice record
  2. ``lots.account_guid``              — the lot belongs to the AP account
  3. ``splits.account_guid``            — AP split in the bill-posting transaction (type I)
  4. ``splits.account_guid``            — AP split in the payment transaction (type P)

Usage
-----
    # Dry-run (safe, no changes)
    uv run python repair_ap_account.py

    # Apply the fix to the real database
    uv run python repair_ap_account.py --apply

    # Target a specific database file
    uv run python repair_ap_account.py --db /path/to/file.gnucash --apply

Exit codes
----------
    0  success (or dry-run completed cleanly)
    1  error
"""

import argparse
import sqlite3
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

def _resolve_db_path() -> Path:
    try:
        from settings_manager import settings  # type: ignore
        return settings.gnucash_db_path
    except Exception:
        pass
    try:
        from config import GNUCASH_DB_PATH  # type: ignore
        return Path(GNUCASH_DB_PATH)
    except Exception:
        pass
    raise RuntimeError(
        "Cannot determine GnuCash database path.  "
        "Pass --db /path/to/file.gnucash explicitly."
    )


# ---------------------------------------------------------------------------
# Discovery: find bills posted to the wrong AP account
# ---------------------------------------------------------------------------

def _find_affected_bills(conn: sqlite3.Connection, wrong_ap_guid: str) -> list[dict]:
    """
    Return all invoices whose post_acc is the wrong INCOME account.
    Also resolve the payment transaction GUID (if paid) by finding the
    'P'-type transaction that has a split linked to the bill's post_lot.
    """
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT
            i.id           AS bill_id,
            i.guid         AS bill_guid,
            i.owner_guid   AS vendor_guid,
            i.post_acc     AS current_ap_guid,
            i.post_lot     AS lot_guid,
            i.post_txn     AS posting_txn_guid
        FROM invoices i
        WHERE i.post_acc = ?
        ORDER BY i.date_posted
    """, (wrong_ap_guid,)).fetchall()

    results = []
    for r in rows:
        entry = dict(r)
        # Find the payment transaction: type-P txn with a split in this lot
        pay_row = conn.execute("""
            SELECT t.guid AS payment_txn_guid
            FROM transactions t
            JOIN slots s ON s.obj_guid = t.guid
                         AND s.name = 'trans-txn-type'
                         AND s.string_val = 'P'
            JOIN splits sp ON sp.tx_guid = t.guid
                           AND sp.lot_guid = ?
            LIMIT 1
        """, (entry["lot_guid"],)).fetchone()
        entry["payment_txn_guid"] = pay_row["payment_txn_guid"] if pay_row else None
        results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Repair one bill
# ---------------------------------------------------------------------------

def _repair_one(conn: sqlite3.Connection, bill: dict,
                wrong_ap_guid: str, correct_ap_guid: str) -> list[str]:
    """Apply all four corrections for a single bill.  Returns list of actions taken."""
    actions = []

    # 1. invoices.post_acc
    conn.execute(
        "UPDATE invoices SET post_acc = ? WHERE guid = ? AND post_acc = ?",
        (correct_ap_guid, bill["bill_guid"], wrong_ap_guid),
    )
    actions.append("invoices.post_acc updated")

    # 2. lots.account_guid
    conn.execute(
        "UPDATE lots SET account_guid = ? WHERE guid = ? AND account_guid = ?",
        (correct_ap_guid, bill["lot_guid"], wrong_ap_guid),
    )
    actions.append("lots.account_guid updated")

    # 3. AP split in the posting transaction (type I)
    n = conn.execute(
        "UPDATE splits SET account_guid = ? "
        "WHERE tx_guid = ? AND account_guid = ?",
        (correct_ap_guid, bill["posting_txn_guid"], wrong_ap_guid),
    ).rowcount
    actions.append(f"posting txn AP split updated ({n} row(s))")

    # 4. AP split in the payment transaction (type P)
    if bill["payment_txn_guid"]:
        n = conn.execute(
            "UPDATE splits SET account_guid = ? "
            "WHERE tx_guid = ? AND account_guid = ?",
            (correct_ap_guid, bill["payment_txn_guid"], wrong_ap_guid),
        ).rowcount
        actions.append(f"payment txn AP split updated ({n} row(s))")
    else:
        actions.append("payment txn: not found / bill unpaid (skipped)")

    return actions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair bills posted against the wrong AP (INCOME) account."
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="Path to the .gnucash (SQLite) file.  "
             "Defaults to settings_manager / config.py value.",
    )
    parser.add_argument(
        "--wrong-ap",
        metavar="GUID",
        default="e7cf4f04896a4ba1bf1aadd2cac219a8",
        help="GUID of the incorrect AP account (default: SAMUSE Product Sales).",
    )
    parser.add_argument(
        "--correct-ap",
        metavar="GUID",
        default="708ac4b6804440cc8206b57258f96542",
        help="GUID of the correct PAYABLE account (default: Payables (SAMUSE)).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes.  Without this flag the script is a dry-run.",
    )
    args = parser.parse_args()

    if args.db:
        db_path = Path(args.db)
    else:
        try:
            db_path = _resolve_db_path()
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
        return 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] Database: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Show account names for sanity-check
    def acct_name(guid):
        r = conn.execute("SELECT name, account_type FROM accounts WHERE guid = ?", (guid,)).fetchone()
        return f"{r['name']} ({r['account_type']})" if r else "NOT FOUND"

    print(f"\nWrong  AP account: {acct_name(args.wrong_ap)}  [{args.wrong_ap}]")
    print(f"Correct AP account: {acct_name(args.correct_ap)}  [{args.correct_ap}]")

    try:
        affected = _find_affected_bills(conn, args.wrong_ap)
    except sqlite3.Error as exc:
        print(f"\nERROR querying database: {exc}", file=sys.stderr)
        conn.close()
        return 1

    if not affected:
        print("\nNo bills found using the wrong AP account.  Nothing to do.")
        conn.close()
        return 0

    print(f"\nFound {len(affected)} bill(s) with wrong AP account:\n")
    for b in affected:
        paid_info = f"payment_txn={b['payment_txn_guid'][:8]}.." if b["payment_txn_guid"] else "UNPAID"
        print(
            f"  {b['bill_id']:15s}  lot={b['lot_guid'][:8]}..  "
            f"posting_txn={b['posting_txn_guid'][:8]}..  {paid_info}"
        )

    if not args.apply:
        print(f"\n[DRY-RUN] No changes made.  Re-run with --apply to write the fix.")
        conn.close()
        return 0

    # Apply all repairs inside a single transaction
    try:
        for bill in affected:
            actions = _repair_one(conn, bill, args.wrong_ap, args.correct_ap)
            print(f"\n  {bill['bill_id']}:")
            for a in actions:
                print(f"    ✓ {a}")
        conn.commit()
        print(f"\n[APPLY] Successfully repaired {len(affected)} bill(s).")
    except sqlite3.Error as exc:
        conn.rollback()
        print(f"\nERROR writing to database (rolled back): {exc}", file=sys.stderr)
        conn.close()
        return 1

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
repair_payment_gncowner.py
==========================
One-time repair script: adds missing ``gncOwner`` KVP slots to payment
transactions that were processed by an older version of pay_bill() that only
attached gncOwner to the *lot*, not to the transaction itself.

GnuCash's "Print Check" dialog resolves the vendor address by reading
``gncOwner`` from the transaction's own KVP slots.  Without it the vendor
name prints correctly (from transactions.description) but the address is blank.

Usage
-----
    # See what would be fixed (safe, no changes)
    uv run python repair_payment_gncowner.py

    # Apply the fix to the real database
    uv run python repair_payment_gncowner.py --apply

    # Target a specific database file
    uv run python repair_payment_gncowner.py --db /path/to/file.gnucash --apply

Exit codes
----------
    0  success (or dry-run completed cleanly)
    1  error
"""

import argparse
import sqlite3
import sys
import uuid
from pathlib import Path


# ---------------------------------------------------------------------------
# GUID helper (no imports from the main package — fully standalone)
# ---------------------------------------------------------------------------

def _generate_guid() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# DB path resolution (tries settings_manager first, falls back to config.py)
# ---------------------------------------------------------------------------

def _resolve_db_path() -> Path:
    try:
        # Import from the installed package if available
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
# Discovery query
# ---------------------------------------------------------------------------

# Find every payment transaction that:
#   - has trans-txn-type = 'P'
#   - has an AP split whose lot links to an invoice (via gncInvoice frame)
#   - does NOT already have a gncOwner slot on the transaction
#
# The gncInvoice structure on the lot:
#   slots row A: obj_guid=lot_guid,   name='gncInvoice',             slot_type=9, guid_val=frame_guid
#   slots row B: obj_guid=frame_guid, name='gncInvoice/invoice-guid', slot_type=5, guid_val=bill_guid
#
# The gncOwner structure we need to ADD to the transaction:
#   slots row C: obj_guid=owner_frame_guid, name='gncOwner/owner-type', slot_type=1, int64_val=4
#   slots row D: obj_guid=owner_frame_guid, name='gncOwner/owner-guid', slot_type=5, guid_val=vendor_guid
#   slots row E: obj_guid=txn_guid,         name='gncOwner',            slot_type=9, guid_val=owner_frame_guid

FIND_BROKEN_SQL = """
SELECT
    t.guid         AS txn_guid,
    t.description  AS vendor_name,
    i.owner_guid   AS vendor_guid,
    i.id           AS bill_id
FROM transactions t
JOIN slots s_type
    ON  s_type.obj_guid    = t.guid
    AND s_type.name        = 'trans-txn-type'
    AND s_type.string_val  = 'P'
JOIN splits sp
    ON  sp.tx_guid   = t.guid
    AND sp.lot_guid IS NOT NULL
    AND sp.lot_guid  != ''
JOIN slots s_inv_frame
    ON  s_inv_frame.obj_guid = sp.lot_guid
    AND s_inv_frame.name     = 'gncInvoice'
JOIN slots s_inv_guid
    ON  s_inv_guid.obj_guid = s_inv_frame.guid_val
    AND s_inv_guid.name     = 'gncInvoice/invoice-guid'
JOIN invoices i
    ON  i.guid = s_inv_guid.guid_val
WHERE NOT EXISTS (
    SELECT 1 FROM slots s_own
    WHERE s_own.obj_guid = t.guid
      AND s_own.name     = 'gncOwner'
)
GROUP BY t.guid   -- de-dup: a transaction may have multiple lot-linked splits
"""


def _find_broken(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    cursor = conn.execute(FIND_BROKEN_SQL)
    return [dict(row) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------

def _repair_one(conn: sqlite3.Connection, row: dict) -> None:
    """Insert the three gncOwner slots onto the payment transaction."""
    txn_guid   = row["txn_guid"]
    vendor_guid = row["vendor_guid"]
    frame_guid  = _generate_guid()

    # Child key: owner-type = 4 (vendor)
    conn.execute(
        "INSERT INTO slots (obj_guid, name, slot_type, int64_val) "
        "VALUES (?, 'gncOwner/owner-type', 1, 4)",
        (frame_guid,),
    )
    # Child key: owner-guid = vendor GUID
    conn.execute(
        "INSERT INTO slots (obj_guid, name, slot_type, guid_val) "
        "VALUES (?, 'gncOwner/owner-guid', 5, ?)",
        (frame_guid, vendor_guid),
    )
    # Parent frame pointer on the transaction
    conn.execute(
        "INSERT INTO slots (obj_guid, name, slot_type, guid_val) "
        "VALUES (?, 'gncOwner', 9, ?)",
        (txn_guid, frame_guid),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair payment transactions missing gncOwner slots."
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="Path to the GnuCash .gnucash (SQLite) file.  "
             "Defaults to settings_manager / config.py value.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes.  Without this flag the script is a dry-run.",
    )
    args = parser.parse_args()

    # Resolve DB path
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
    print(f"[{mode}] Database: {db_path}\n")

    # Open connection
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    try:
        broken = _find_broken(conn)
    except sqlite3.Error as exc:
        print(f"ERROR querying database: {exc}", file=sys.stderr)
        conn.close()
        return 1

    if not broken:
        print("No broken payment transactions found.  Nothing to do.")
        conn.close()
        return 0

    print(f"Found {len(broken)} payment transaction(s) missing gncOwner:\n")
    for row in broken:
        print(
            f"  Bill {row['bill_id']:8s}  "
            f"vendor={row['vendor_name']!r:40s}  "
            f"txn={row['txn_guid']}"
        )

    if not args.apply:
        print(
            f"\n[DRY-RUN] No changes made.  "
            f"Re-run with --apply to write the fix."
        )
        conn.close()
        return 0

    # Apply
    try:
        for row in broken:
            _repair_one(conn, row)
        conn.commit()
        print(f"\n[APPLY] Successfully repaired {len(broken)} transaction(s).")
    except sqlite3.Error as exc:
        conn.rollback()
        print(f"ERROR writing to database (rolled back): {exc}", file=sys.stderr)
        conn.close()
        return 1

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

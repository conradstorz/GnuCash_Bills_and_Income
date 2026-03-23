"""Shared test helpers — importable by any test file."""
import sqlite3
import uuid


def _insert_lock(db_path, hostname, pid):
    """Insert a lock row directly into gnclock to simulate a held lock."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO gnclock VALUES (?, ?)", (hostname, pid))
    conn.commit()
    conn.close()


def _insert_test_vendor(db_path, name, guid=None, vendor_id=None, **addr_fields):
    """Insert a minimal vendor row into the SQLite DB at db_path.

    Uses PRAGMA table_info to discover available columns so it works across
    GnuCash schema versions. Returns the inserted GUID.
    """
    guid = guid or uuid.uuid4().hex
    vendor_id = vendor_id or "099999"

    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        "SELECT guid FROM commodities WHERE mnemonic='USD' AND namespace='CURRENCY' LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        raise RuntimeError("USD commodity not found in test DB")
    currency_guid = row[0]

    # Discover available columns
    cur = conn.execute("PRAGMA table_info(vendors)")
    available = {r[1] for r in cur.fetchall()}

    base = {
        "guid": guid,
        "id": vendor_id,
        "name": name,
        "currency": currency_guid,
        "active": 1,
        "tax_override": 0,
        "notes": "",
        "addr_name": addr_fields.get("addr_name", ""),
        "addr_addr1": addr_fields.get("addr_addr1", ""),
        "addr_addr2": addr_fields.get("addr_addr2", ""),
        "addr_addr3": addr_fields.get("addr_addr3", ""),
        "addr_addr4": addr_fields.get("addr_addr4", ""),
        "addr_phone": addr_fields.get("addr_phone", ""),
        "addr_fax": addr_fields.get("addr_fax", ""),
        "addr_email": addr_fields.get("addr_email", ""),
        "tax_inc": "",
        # tax_table is excluded: it is a FK reference to the tax tables table.
        # SQLite does not enforce FKs by default, but excluding is safer.
    }

    insert_data = {k: v for k, v in base.items() if k in available}
    cols = ", ".join(insert_data.keys())
    placeholders = ", ".join("?" * len(insert_data))
    conn.execute(
        f"INSERT INTO vendors ({cols}) VALUES ({placeholders})",
        list(insert_data.values())
    )
    conn.commit()
    conn.close()
    return guid

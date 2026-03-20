"""Shared test helpers — importable by any test file."""
import sqlite3


def _insert_lock(db_path, hostname, pid):
    """Insert a lock row directly into gnclock to simulate a held lock."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO gnclock VALUES (?, ?)", (hostname, pid))
    conn.commit()
    conn.close()

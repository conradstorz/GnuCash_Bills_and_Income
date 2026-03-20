"""Tests for DB lock management functions in gnucash_db.py."""
import os
import socket
import sqlite3
from pathlib import Path
from unittest.mock import patch
import importlib.util

import pytest

from bill_processor.gnucash_db import (
    is_gnucash_locked,
    get_lock_info,
    is_locked_by_others,
    _get_lock_hostname,
    _is_process_running,
    clean_stale_lock,
    acquire_lock,
    release_lock,
    database_lock,
)

_spec = importlib.util.spec_from_file_location("helpers", Path(__file__).parent / "helpers.py")
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
_insert_lock = _helpers._insert_lock
del _spec, _helpers


class TestIsGnucashLocked:
    def test_db_missing(self, lock_db):
        lock_db.unlink()
        assert is_gnucash_locked() == (False, None, None)

    def test_empty_table(self, lock_db):
        assert is_gnucash_locked() == (False, None, None)

    def test_locked_row_present(self, lock_db):
        _insert_lock(lock_db, "GnuCash@HOST", 1234)
        locked, hostname, pid = is_gnucash_locked()
        assert locked is True
        assert hostname == "GnuCash@HOST"
        assert pid == 1234

    def test_operational_error_treated_as_locked(self, lock_db):
        with patch("bill_processor.gnucash_db.sqlite3.connect",
                   side_effect=sqlite3.OperationalError("disk I/O error")):
            locked, hostname, pid = is_gnucash_locked()
        assert locked is True
        assert hostname == "unknown"
        assert pid == 0


class TestGetLockInfo:
    def test_not_locked_returns_none(self, lock_db):
        assert get_lock_info() is None

    def test_locked_returns_dict(self, lock_db):
        _insert_lock(lock_db, "GnuCash@HOST", 5678)
        info = get_lock_info()
        assert info == {"hostname": "GnuCash@HOST", "pid": 5678}


class TestIsLockedByOthers:
    def test_not_locked(self, lock_db):
        assert is_locked_by_others() == (False, None, None)

    def test_locked_by_own_process(self, lock_db):
        my_hostname = _get_lock_hostname()
        my_pid = os.getpid()
        _insert_lock(lock_db, my_hostname, my_pid)
        assert is_locked_by_others() == (False, None, None)

    def test_locked_by_different_pid(self, lock_db):
        my_hostname = _get_lock_hostname()
        foreign_pid = os.getpid() + 9999
        _insert_lock(lock_db, my_hostname, foreign_pid)
        locked, hostname, pid = is_locked_by_others()
        assert locked is True
        assert hostname == my_hostname
        assert pid == foreign_pid

    def test_locked_by_different_hostname(self, lock_db):
        _insert_lock(lock_db, "GnuCash@OTHER", 1234)
        locked, hostname, pid = is_locked_by_others()
        assert locked is True
        assert hostname == "GnuCash@OTHER"
        assert pid == 1234


class TestGetLockHostname:
    def test_format_starts_with_prefix(self):
        assert _get_lock_hostname().startswith("BillProcessor@")

    def test_contains_machine_name(self):
        assert socket.gethostname() in _get_lock_hostname()


class TestIsProcessRunning:
    def test_negative_pid_returns_false(self):
        assert _is_process_running(-1) is False
        assert _is_process_running(0) is False

    def test_live_pid_returns_true(self):
        # os.getpid() is guaranteed to be running (it's us)
        assert _is_process_running(os.getpid()) is True

    def test_dead_pid_returns_false(self):
        # PID 999999 is almost certainly not running on any machine
        # If this is flaky (PID exists), increase the value or skip
        assert _is_process_running(999999) is False


class TestCleanStaleLock:
    def _row_count(self, db_path):
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM gnclock").fetchone()[0]
        conn.close()
        return count

    def test_no_lock_returns_false(self, lock_db):
        assert clean_stale_lock() is False

    def test_remote_billprocessor_lock_untouched(self, lock_db):
        # BillProcessor@ on a different machine — cannot clean remotely
        _insert_lock(lock_db, "BillProcessor@OTHER_MACHINE", 9999)
        assert clean_stale_lock() is False
        assert self._row_count(lock_db) == 1

    def test_local_billprocessor_live_pid_untouched(self, lock_db):
        local_hostname = _get_lock_hostname()
        _insert_lock(lock_db, local_hostname, 9999)
        with patch("bill_processor.gnucash_db._is_process_running", return_value=True):
            assert clean_stale_lock() is False
        assert self._row_count(lock_db) == 1

    def test_local_billprocessor_dead_pid_cleaned(self, lock_db):
        local_hostname = _get_lock_hostname()
        _insert_lock(lock_db, local_hostname, 9999)
        with patch("bill_processor.gnucash_db._is_process_running", return_value=False):
            assert clean_stale_lock() is True
        assert self._row_count(lock_db) == 0

    def test_gnucash_lock_live_pid_untouched(self, lock_db):
        # Raw GnuCash lock (no BillProcessor@ prefix) — falls through to PID check
        _insert_lock(lock_db, "GnuCash@DESKTOP", 9999)
        with patch("bill_processor.gnucash_db._is_process_running", return_value=True):
            assert clean_stale_lock() is False
        assert self._row_count(lock_db) == 1

    def test_gnucash_lock_dead_pid_cleaned(self, lock_db):
        # GnuCash crashed — dead PID, no BillProcessor@ prefix, so it gets cleaned
        _insert_lock(lock_db, "GnuCash@DESKTOP", 9999)
        with patch("bill_processor.gnucash_db._is_process_running", return_value=False):
            assert clean_stale_lock() is True
        assert self._row_count(lock_db) == 0

    def test_db_error_on_delete_returns_false(self, lock_db):
        local_hostname = _get_lock_hostname()
        _insert_lock(lock_db, local_hostname, 9999)
        # Patching sqlite3.connect to raise OperationalError means is_gnucash_locked()
        # catches it and returns (True, "unknown", 0). clean_stale_lock() then proceeds
        # to attempt the DELETE, hits the same error in its own connect call, and the
        # except sqlite3.Error block returns False.
        with patch("bill_processor.gnucash_db._is_process_running", return_value=False), \
             patch("bill_processor.gnucash_db.sqlite3.connect",
                   side_effect=sqlite3.OperationalError("disk full")):
            result = clean_stale_lock()
        assert result is False

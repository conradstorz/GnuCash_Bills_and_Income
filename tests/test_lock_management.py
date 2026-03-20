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

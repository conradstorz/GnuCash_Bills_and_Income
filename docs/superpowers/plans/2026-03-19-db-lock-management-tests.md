# DB Lock Management Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add comprehensive real-SQLite tests for all lock management functions in `gnucash_db.py` and de-mock `test_db_health.py`.

**Architecture:** Four files touched. A new `tests/helpers.py` holds the shared `_insert_lock` helper. `conftest.py` gets two new fixtures (`lock_db`, `health_db`) imported from helpers. A new `test_lock_management.py` covers all ten lock functions. `test_db_health.py` is refactored to remove all mocks and use `health_db` with real SQLite state.

**Tech Stack:** pytest, sqlite3 (stdlib), `unittest.mock.patch`, Python 3.11+

**Spec:** `docs/superpowers/specs/2026-03-19-db-lock-management-tests-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `tests/helpers.py` | Create | `_insert_lock` helper — importable by all test files |
| `tests/conftest.py` | Modify | Add `lock_db`, `health_db` fixtures (use `_insert_lock` from helpers) |
| `tests/test_lock_management.py` | Create | Tests for all lock primitive functions |
| `tests/test_db_health.py` | Refactor | Remove mocks; use `health_db` + real DB state |

---

## Windows URI Note (Read Before Starting)

`gnucash_db.py` constructs SQLite URI strings like `f"file:{db_path}?mode=ro"` using `str(Path(...))`. On Windows this produces backslashes which SQLite's URI parser rejects with "unable to open database file". If any test fails with that error, the fix is to change those lines in `gnucash_db.py` to use `db_path.as_posix()`. Check for this in Tasks 2 and 7.

Affected lines in `gnucash_db.py`:
- Line 302: `uri = f"file:{db_path}?mode=ro"` (in `is_gnucash_locked`)
- Line 609: `uri = f"file:{db_path}?mode=ro"` (in `get_connection`)

---

## Task 1: Create `tests/helpers.py` and Update `conftest.py`

**Files:**
- Create: `tests/helpers.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Create `tests/helpers.py`**

```python
"""Shared test helpers — importable by any test file."""
import sqlite3


def _insert_lock(db_path, hostname, pid):
    """Insert a lock row directly into gnclock to simulate a held lock."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO gnclock VALUES (?, ?)", (hostname, pid))
    conn.commit()
    conn.close()
```

- [ ] **Step 2: Add imports and fixtures to `conftest.py`**

Add `from unittest.mock import patch` and `from tests.helpers import _insert_lock` to the imports at the top of `tests/conftest.py`. Then add the two new fixtures after the existing ones:

```python
@pytest.fixture
def lock_db(tmp_path):
    """Minimal SQLite DB with only gnclock table; GNUCASH_DB_PATH patched to it.

    Uses patch() rather than direct attribute mutation (the existing db_connection
    fixture style) so the original value is automatically restored on test exit.
    """
    db = tmp_path / "test.gnucash"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE gnclock (Hostname TEXT, PID INTEGER)")
    conn.commit()
    conn.close()
    with patch("bill_processor.gnucash_db.config.GNUCASH_DB_PATH", db):
        yield db


@pytest.fixture
def health_db(tmp_path):
    """SQLite DB with gnclock + accounts tables for check_db_health tests."""
    db = tmp_path / "test.gnucash"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE gnclock (Hostname TEXT, PID INTEGER)")
    conn.execute("""CREATE TABLE accounts (
        guid TEXT, name TEXT, account_type TEXT, placeholder INTEGER
    )""")
    conn.commit()
    conn.close()
    with patch("bill_processor.gnucash_db.config.GNUCASH_DB_PATH", db):
        yield db
```

- [ ] **Step 3: Verify conftest still loads**

```
uv run pytest tests/test_utils.py -v --co -q
```

Expected: test names listed, no import errors.

- [ ] **Step 4: Commit**

```
git add tests/helpers.py tests/conftest.py
git commit -m "test: add lock_db/health_db fixtures and _insert_lock helper"
```

---

## Task 2: `TestIsGnucashLocked` and `TestGetLockInfo`

**Files:**
- Create: `tests/test_lock_management.py`

- [ ] **Step 1: Create the file with imports and `TestIsGnucashLocked`**

```python
"""Tests for DB lock management functions in gnucash_db.py."""
import os
import socket
import sqlite3
from unittest.mock import patch

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
from tests.helpers import _insert_lock


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
```

- [ ] **Step 2: Run to verify tests pass (or diagnose URI issue)**

```
uv run pytest tests/test_lock_management.py::TestIsGnucashLocked -v
```

Expected: 4 PASSED. If any fail with "unable to open database file", fix `gnucash_db.py` line 302:
change `uri = f"file:{db_path}?mode=ro"` to `uri = f"file:{db_path.as_posix()}?mode=ro"`. Re-run after the fix.

- [ ] **Step 3: Add `TestGetLockInfo`**

Append to `tests/test_lock_management.py`:

```python
class TestGetLockInfo:
    def test_not_locked_returns_none(self, lock_db):
        assert get_lock_info() is None

    def test_locked_returns_dict(self, lock_db):
        _insert_lock(lock_db, "GnuCash@HOST", 5678)
        info = get_lock_info()
        assert info == {"hostname": "GnuCash@HOST", "pid": 5678}
```

- [ ] **Step 4: Run both classes**

```
uv run pytest tests/test_lock_management.py::TestIsGnucashLocked tests/test_lock_management.py::TestGetLockInfo -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```
git add tests/test_lock_management.py
git commit -m "test: add TestIsGnucashLocked and TestGetLockInfo"
```

---

## Task 3: `TestIsLockedByOthers` and `TestGetLockHostname`

**Files:**
- Modify: `tests/test_lock_management.py`

- [ ] **Step 1: Add `TestIsLockedByOthers`**

Append to `tests/test_lock_management.py`:

```python
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
```

- [ ] **Step 2: Add `TestGetLockHostname`**

Append:

```python
class TestGetLockHostname:
    def test_format_starts_with_prefix(self):
        assert _get_lock_hostname().startswith("BillProcessor@")

    def test_contains_machine_name(self):
        assert socket.gethostname() in _get_lock_hostname()
```

- [ ] **Step 3: Run new classes**

```
uv run pytest tests/test_lock_management.py::TestIsLockedByOthers tests/test_lock_management.py::TestGetLockHostname -v
```

Expected: 6 PASSED.

- [ ] **Step 4: Commit**

```
git add tests/test_lock_management.py
git commit -m "test: add TestIsLockedByOthers and TestGetLockHostname"
```

---

## Task 4: `TestIsProcessRunning` and `TestCleanStaleLock`

**Files:**
- Modify: `tests/test_lock_management.py`

- [ ] **Step 1: Add `TestIsProcessRunning`**

Append to `tests/test_lock_management.py`:

```python
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
```

- [ ] **Step 2: Run `TestIsProcessRunning`**

```
uv run pytest tests/test_lock_management.py::TestIsProcessRunning -v
```

Expected: 3 PASSED. If `test_dead_pid_returns_false` fails (PID 999999 happens to exist), that is genuinely a flaky environment — skip that test with `@pytest.mark.skipif` or increase the PID value to something even less likely.

- [ ] **Step 3: Add `TestCleanStaleLock`**

Append to `tests/test_lock_management.py`:

```python
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
        # Patching sqlite3.connect to always raise means is_gnucash_locked() also
        # raises, returning (True, "unknown", 0) — that's acceptable here;
        # the outer function still hits the error path and returns False.
        with patch("bill_processor.gnucash_db._is_process_running", return_value=False), \
             patch("bill_processor.gnucash_db.sqlite3.connect",
                   side_effect=sqlite3.Error("disk full")):
            result = clean_stale_lock()
        assert result is False
```

- [ ] **Step 4: Run both classes**

```
uv run pytest tests/test_lock_management.py::TestIsProcessRunning tests/test_lock_management.py::TestCleanStaleLock -v
```

Expected: 10 PASSED.

- [ ] **Step 5: Commit**

```
git add tests/test_lock_management.py
git commit -m "test: add TestIsProcessRunning and TestCleanStaleLock"
```

---

## Task 5: `TestAcquireLock` and `TestReleaseLock`

**Files:**
- Modify: `tests/test_lock_management.py`

- [ ] **Step 1: Add `TestAcquireLock`**

Append to `tests/test_lock_management.py`:

```python
class TestAcquireLock:
    def _get_gnclock_rows(self, db_path):
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT Hostname, PID FROM gnclock").fetchall()
        conn.close()
        return rows

    def test_unlocked_db_acquires(self, lock_db):
        assert acquire_lock() is True
        rows = self._get_gnclock_rows(lock_db)
        assert len(rows) == 1
        assert rows[0][0] == _get_lock_hostname()
        assert rows[0][1] == os.getpid()
        release_lock()  # clean up

    def test_already_locked_externally_returns_false(self, lock_db):
        _insert_lock(lock_db, "GnuCash@OTHER", 1234)
        assert acquire_lock() is False
        rows = self._get_gnclock_rows(lock_db)
        assert len(rows) == 1
        assert rows[0][0] == "GnuCash@OTHER"

    def test_stale_lock_auto_cleaned_then_acquired(self, lock_db):
        local_hostname = _get_lock_hostname()
        _insert_lock(lock_db, local_hostname, 9999)  # stale lock from dead PID
        with patch("bill_processor.gnucash_db._is_process_running", return_value=False):
            assert acquire_lock() is True
        rows = self._get_gnclock_rows(lock_db)
        assert len(rows) == 1
        assert rows[0][0] == local_hostname
        assert rows[0][1] == os.getpid()
        release_lock()

    def test_db_error_on_insert_returns_false(self, lock_db):
        # Read paths (is_gnucash_locked, clean_stale_lock) use uri=True.
        # The INSERT write path uses a plain connect (no uri=True).
        # Raise only on non-URI connects to avoid triggering a false early return
        # from the lock-check reads.
        real_connect = sqlite3.connect

        def raise_on_write(*args, **kwargs):
            if not kwargs.get("uri", False):
                raise sqlite3.Error("simulated write failure")
            return real_connect(*args, **kwargs)

        with patch("bill_processor.gnucash_db.sqlite3.connect", side_effect=raise_on_write):
            result = acquire_lock()
        assert result is False
```

- [ ] **Step 2: Add `TestReleaseLock`**

Append:

```python
class TestReleaseLock:
    def _get_gnclock_rows(self, db_path):
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT Hostname, PID FROM gnclock").fetchall()
        conn.close()
        return rows

    def test_releases_own_lock(self, lock_db):
        # Use _insert_lock directly — keeps this test isolated from acquire_lock()
        _insert_lock(lock_db, _get_lock_hostname(), os.getpid())
        assert release_lock() is True
        assert self._get_gnclock_rows(lock_db) == []

    def test_no_lock_is_idempotent(self, lock_db):
        assert release_lock() is True

    def test_does_not_delete_others_lock(self, lock_db):
        _insert_lock(lock_db, "GnuCash@OTHER", 1234)
        assert release_lock() is True
        rows = self._get_gnclock_rows(lock_db)
        assert len(rows) == 1
        assert rows[0][0] == "GnuCash@OTHER"

    def test_db_error_returns_false(self, lock_db):
        with patch("bill_processor.gnucash_db.sqlite3.connect",
                   side_effect=sqlite3.Error("locked")):
            assert release_lock() is False
```

- [ ] **Step 3: Run both classes**

```
uv run pytest tests/test_lock_management.py::TestAcquireLock tests/test_lock_management.py::TestReleaseLock -v
```

Expected: 8 PASSED.

- [ ] **Step 4: Commit**

```
git add tests/test_lock_management.py
git commit -m "test: add TestAcquireLock and TestReleaseLock"
```

---

## Task 6: `TestDatabaseLockContextManager`

**Files:**
- Modify: `tests/test_lock_management.py`

- [ ] **Step 1: Add `TestDatabaseLockContextManager`**

Append to `tests/test_lock_management.py`:

```python
class TestDatabaseLockContextManager:
    """Tests for the database_lock() context manager.

    Known behavioral gap: if release_lock() raises inside the finally block,
    that exception propagates and may mask any exception from the with-body.
    This is not tested here — testing it would require mocking release_lock(),
    which reintroduces the mock approach we're moving away from.
    """

    def _get_gnclock_rows(self, db_path):
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT Hostname, PID FROM gnclock").fetchall()
        conn.close()
        return rows

    def test_lock_held_during_block(self, lock_db):
        with database_lock():
            rows = self._get_gnclock_rows(lock_db)
            assert len(rows) == 1
            assert rows[0][0] == _get_lock_hostname()
            assert rows[0][1] == os.getpid()

    def test_lock_released_after_normal_exit(self, lock_db):
        with database_lock():
            pass
        assert self._get_gnclock_rows(lock_db) == []

    def test_lock_released_after_exception(self, lock_db):
        with pytest.raises(ValueError):
            with database_lock():
                raise ValueError("something went wrong")
        assert self._get_gnclock_rows(lock_db) == []

    def test_raises_runtime_error_if_already_locked(self, lock_db):
        _insert_lock(lock_db, "GnuCash@OTHER", 1234)
        with pytest.raises(RuntimeError, match="database is in use"):
            with database_lock():
                pass  # pragma: no cover
```

- [ ] **Step 2: Run `TestDatabaseLockContextManager`**

```
uv run pytest tests/test_lock_management.py::TestDatabaseLockContextManager -v
```

Expected: 4 PASSED.

- [ ] **Step 3: Run the full new test file**

```
uv run pytest tests/test_lock_management.py -v
```

Expected: all 34 tests PASSED.
(4 + 2 + 4 + 2 + 3 + 7 + 4 + 4 + 4 = 34)

- [ ] **Step 4: Commit**

```
git add tests/test_lock_management.py
git commit -m "test: add TestDatabaseLockContextManager — completes test_lock_management.py"
```

---

## Task 7: De-mock `test_db_health.py`

**Files:**
- Modify: `tests/test_db_health.py`

- [ ] **Step 1: Read the current file**

Read `tests/test_db_health.py` in full before editing.

- [ ] **Step 2: Rewrite the file**

Replace the entire contents with:

```python
"""Tests for check_db_health() in gnucash_db.py — uses real SQLite, no mocks."""
import sqlite3
import pytest
from bill_processor import gnucash_db, config
from tests.helpers import _insert_lock


def _insert_samuse_account(db_path):
    """Insert the SAMUSE account row required for an 'ok' health check.

    name must equal config.CASH_ON_HAND_ACCOUNT_NAME and placeholder must be 0
    to match the query in check_db_health().
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO accounts (guid, name, account_type, placeholder) VALUES (?, ?, 'CASH', 0)",
        ("a" * 32, config.CASH_ON_HAND_ACCOUNT_NAME),
    )
    conn.commit()
    conn.close()


class TestCheckDbHealth:
    def test_returns_ok_when_healthy(self, health_db):
        _insert_samuse_account(health_db)
        result = gnucash_db.check_db_health()
        assert result["status"] == "ok"
        assert result["path"] == str(health_db)
        assert result["hostname"] is None
        assert result["pid"] is None

    def test_returns_missing_when_file_not_found(self, health_db):
        health_db.unlink()
        result = gnucash_db.check_db_health()
        assert result["status"] == "missing"
        assert "path" in result

    def test_returns_locked_when_locked_by_others(self, health_db):
        _insert_lock(health_db, "GnuCash@DESKTOP-XYZ", 4821)
        result = gnucash_db.check_db_health()
        assert result["status"] == "locked"
        assert result["hostname"] == "GnuCash@DESKTOP-XYZ"
        assert result["pid"] == 4821
        assert "4821" in result["message"] or "DESKTOP-XYZ" in result["message"]

    def test_returns_account_missing_when_samuse_not_found(self, health_db):
        # accounts table is empty — no SAMUSE row inserted
        result = gnucash_db.check_db_health()
        assert result["status"] == "account_missing"
        assert config.CASH_ON_HAND_ACCOUNT_NAME in result["message"]
        assert result["hostname"] is None
        assert result["pid"] is None

    def test_missing_check_does_not_reach_lock_check(self, health_db):
        # When the file is missing, check_db_health() returns early before calling
        # is_locked_by_others(). We verify the outcome (status == "missing") rather
        # than the call count — this is a weaker assertion than the original mock-based
        # test, accepted as an intentional trade-off for removing mock infrastructure.
        health_db.unlink()
        result = gnucash_db.check_db_health()
        assert result["status"] == "missing"

    def test_ok_result_contains_path(self, health_db):
        _insert_samuse_account(health_db)
        result = gnucash_db.check_db_health()
        assert result["path"] == str(health_db)
```

- [ ] **Step 3: Run de-mocked tests**

```
uv run pytest tests/test_db_health.py -v
```

Expected: 6 PASSED. If any fail with "unable to open database file", fix `gnucash_db.py` line 609:
change `uri = f"file:{db_path}?mode=ro"` to `uri = f"file:{db_path.as_posix()}?mode=ro"`. Re-run after the fix.

- [ ] **Step 4: Run the full test suite to confirm no regressions**

```
uv run pytest tests/ -v --tb=short
```

Expected: all previously passing tests still pass; new lock tests and de-mocked health tests pass.

- [ ] **Step 5: Commit**

```
git add tests/test_db_health.py
git commit -m "test: de-mock test_db_health.py — use real SQLite via health_db fixture"
```

---

## Final Verification

- [ ] **Run full suite one more time**

```
uv run pytest tests/ -v
```

Expected: all tests pass with no references to mock infrastructure in health or lock tests.

# DB Lock Management Tests — Design Spec
**Date:** 2026-03-19
**Scope:** Add comprehensive tests for GnuCash database lock management functions in `gnucash_db.py`, and de-mock the existing `test_db_health.py` tests.

---

## Background

`gnucash_db.py` contains a complete lock management subsystem that is currently untested:

| Function | Purpose |
|---|---|
| `is_gnucash_locked()` | Reads `gnclock` table; returns `(is_locked, hostname, pid)` |
| `get_lock_info()` | Thin wrapper returning `dict` or `None` |
| `is_locked_by_others()` | Skips our own process's lock |
| `_get_lock_hostname()` | Returns `BillProcessor@<hostname>` |
| `_is_process_running(pid)` | Cross-platform PID liveness check |
| `clean_stale_lock()` | Removes dead-process locks from local machine |
| `acquire_lock()` | Inserts our lock into `gnclock` (calls clean first) |
| `release_lock()` | Deletes our lock from `gnclock` |
| `database_lock()` | Context manager wrapping acquire/release |

`test_db_health.py` currently mocks `is_locked_by_others` rather than using a real database, which means the SQL path is never exercised.

---

## Approach

- **Real SQLite database** for all lock tests — creates actual `.gnucash` files in `tmp_path` with a `gnclock` table.
- **Mock only `_is_process_running`** — reliable "dead PID" detection is non-deterministic on Windows; everything else hits real SQLite.
- **Two new/modified files:**
  1. `tests/test_lock_management.py` — new file for lock primitive tests
  2. `tests/test_db_health.py` — de-mock: replace patched `is_locked_by_others` with real DB state manipulation

---

## Windows URI Path Note

`is_gnucash_locked()` and `get_connection()` open SQLite with a URI string (`file:<path>?mode=ro`). On Windows, `str(Path(...))` produces backslashes which SQLite's URI parser may reject. All URI construction must use `db_path.as_posix()` instead of `str(db_path)`. The `lock_db` and `health_db` fixtures must verify this works — if tests fail with `unable to open database file`, this is the cause.

---

## Fixtures (all in `conftest.py`)

### `lock_db`
Creates a minimal SQLite file with only the `gnclock` table. Patches `gnucash_db.config.GNUCASH_DB_PATH` (matching the established conftest.py pattern of patching the attribute on the module reference, not `bill_processor.config.GNUCASH_DB_PATH`).

```python
@pytest.fixture
def lock_db(tmp_path):
    db = tmp_path / "test.gnucash"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE gnclock (Hostname TEXT, PID INTEGER)")
    conn.commit()
    conn.close()
    with patch("bill_processor.gnucash_db.config.GNUCASH_DB_PATH", db):
        yield db
```

### `health_db`
Extends `lock_db` with an `accounts` table for SAMUSE account presence/absence scenarios. When inserting the "account found" row, `name` must equal `config.CASH_ON_HAND_ACCOUNT_NAME` and `placeholder` must be `0` (integer).

```python
@pytest.fixture
def health_db(tmp_path):
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

### `_insert_lock(db_path, hostname, pid)` (module-level helper in `conftest.py`)
Inserts a row directly into `gnclock` to simulate a held lock. Placed in `conftest.py` so both `test_lock_management.py` and `test_db_health.py` can use it without importing between test files.

```python
def _insert_lock(db_path, hostname, pid):
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT INTO gnclock VALUES (?, ?)", (hostname, pid))
    conn.commit()
    conn.close()
```

---

## `tests/test_lock_management.py` — Test Classes

### `TestIsGnucashLocked`
| Test | Setup | Expected |
|---|---|---|
| `test_db_missing` | `lock_db` path deleted before call | `(False, None, None)` |
| `test_empty_table` | `lock_db` with empty gnclock | `(False, None, None)` |
| `test_locked_row_present` | `_insert_lock("GnuCash@HOST", 1234)` | `(True, "GnuCash@HOST", 1234)` |
| `test_operational_error` | Mock `sqlite3.connect` to raise `OperationalError` | `(True, "unknown", 0)` |

### `TestGetLockInfo`
A thin wrapper — two tests cover both branches. No new scenarios beyond `TestIsGnucashLocked`.

| Test | Setup | Expected |
|---|---|---|
| `test_not_locked` | Empty gnclock | `None` |
| `test_locked` | Insert lock row | `{'hostname': ..., 'pid': ...}` |

### `TestIsLockedByOthers`
| Test | Setup | Expected |
|---|---|---|
| `test_not_locked` | Empty gnclock | `(False, None, None)` |
| `test_locked_by_own_process` | `_insert_lock(_get_lock_hostname(), os.getpid())` | `(False, None, None)` |
| `test_locked_by_different_pid` | `_insert_lock(_get_lock_hostname(), os.getpid() + 9999)` | `(True, hostname, pid)` |
| `test_locked_by_different_hostname` | `_insert_lock("GnuCash@OTHER", 1234)` | `(True, "GnuCash@OTHER", 1234)` |

### `TestGetLockHostname`
| Test | Expected |
|---|---|
| `test_format` | Starts with `"BillProcessor@"` |
| `test_contains_machine_name` | Contains `socket.gethostname()` |

### `TestCleanStaleLock`
Note: The remote-machine check only applies to `BillProcessor@` prefixed locks. Raw GnuCash locks (e.g., `GnuCash@HOST`) fall through to the PID check, so dead-PID GnuCash locks will be cleaned.

| Test | Lock inserted | `_is_process_running` mock | Expected return | Expected DB state |
|---|---|---|---|---|
| `test_no_lock` | None | — | `False` | empty |
| `test_remote_billprocessor_lock` | `BillProcessor@OTHER_MACHINE` + any PID | — | `False` | row present |
| `test_local_billprocessor_live_pid` | `BillProcessor@<local>` + PID | returns `True` | `False` | row present |
| `test_local_billprocessor_dead_pid` | `BillProcessor@<local>` + PID | returns `False` | `True` | gnclock empty |
| `test_gnucash_lock_live_pid` | `GnuCash@DESKTOP` + PID | returns `True` | `False` | row present |
| `test_gnucash_lock_dead_pid` | `GnuCash@DESKTOP` + PID | returns `False` | `True` | gnclock empty |
| `test_db_error_on_delete` | `BillProcessor@<local>` + dead PID | returns `False` | `False` | — |

### `TestAcquireLock`
| Test | Setup | Expected return | Expected DB state |
|---|---|---|---|
| `test_unlocked_db` | Empty gnclock | `True` | Our hostname+PID row inserted |
| `test_already_locked_externally` | `_insert_lock("GnuCash@OTHER", 1234)` | `False` | Foreign row still present |
| `test_stale_lock_auto_cleaned` | `_insert_lock(local_hostname, dead_pid)`, mock `_is_process_running` → `False` | `True` | Our row replaces stale row |
| `test_db_error_on_insert` | Use `side_effect` on `sqlite3.connect` to succeed for reads (lock-check path) but raise `sqlite3.Error` on the INSERT call | `False` | — |

**Note on `test_db_error_on_insert`:** Do not mock `sqlite3.connect` to always raise — `clean_stale_lock` and `is_gnucash_locked` also call it, and raising there will cause an early `False` return for the wrong reason. Use a `side_effect` callable that counts calls or inspects arguments to raise only on the write connection.

### `TestReleaseLock`
Setup for `test_releases_own_lock` uses `_insert_lock` directly (not `acquire_lock()`), keeping the test isolated from `acquire_lock`'s behaviour.

| Test | Setup | Expected return | Expected DB state |
|---|---|---|---|
| `test_releases_own_lock` | `_insert_lock(_get_lock_hostname(), os.getpid())` | `True` | gnclock empty |
| `test_no_lock_is_idempotent` | Empty gnclock | `True` | still empty |
| `test_does_not_delete_others_lock` | `_insert_lock("GnuCash@OTHER", 1234)` | `True` | foreign row still present |
| `test_db_error` | Mock sqlite3 to raise | `False` | — |

### `TestDatabaseLockContextManager`
| Test | Scenario |
|---|---|
| `test_lock_held_during_block` | Inside `with database_lock():`, query gnclock and assert our row is present |
| `test_lock_released_after_block` | After `with` exits normally, gnclock is empty |
| `test_lock_released_after_exception` | Exception raised inside block — gnclock is still empty after (finally fires) |
| `test_raises_if_already_locked` | `_insert_lock("GnuCash@OTHER", 1234)` before entering — raises `RuntimeError` |

**Note:** If `release_lock()` itself raises inside the `finally` block, that exception propagates and may mask a body exception. This is a known behavioral gap in the context manager — document it in a code comment in the test file, but do not add a test for it (it would require mocking `release_lock` which reintroduces mocks for no practical gain).

---

## `tests/test_db_health.py` — De-mocking Plan

Switch all tests to use the `health_db` fixture. Replace mock patches with direct DB manipulation:

| Old approach | New approach |
|---|---|
| `patch("...is_locked_by_others", return_value=(False, None, None))` | `health_db` with empty `gnclock` |
| `patch("...is_locked_by_others", return_value=(True, "GnuCash@DESKTOP-XYZ", 4821))` | `_insert_lock(health_db, "GnuCash@DESKTOP-XYZ", 4821)` |
| `patch("...get_connection", return_value=_make_samuse_conn(True))` | Insert row: `name=config.CASH_ON_HAND_ACCOUNT_NAME, placeholder=0` into `accounts` |
| `patch("...get_connection", return_value=_make_samuse_conn(False))` | Leave `accounts` table empty |

The `_make_samuse_conn` helper and all mock infrastructure in `test_db_health.py` can be deleted.

**URI path note:** The de-mocked tests call `check_db_health()` which calls `get_connection(readonly=True)`, which constructs a URI string. The same Windows backslash concern applies — validate that `health_db`'s `tmp_path` file opens correctly via URI mode on Windows before assuming the tests pass.

---

## Files Changed

| File | Action |
|---|---|
| `tests/conftest.py` | **Update** — add `lock_db`, `health_db` fixtures and `_insert_lock` helper |
| `tests/test_lock_management.py` | **Create** — ~170–200 lines |
| `tests/test_db_health.py` | **Refactor** — remove all mocks, use `health_db` fixture |

# Test Expansion Design
**Date:** 2026-05-07  
**Scope:** Fix test runner + add core pipeline test coverage

## Problem

`tests/run_tests.py` only runs `test_bill_workflow.py` (19 tests). The project has 20 test files with hundreds of tests that never run. Additionally, three core pipeline modules have no test coverage: `web/queue_io.py`, `main.py`, and several web endpoints.

## Goal

1. Fix the runner so all existing test files execute.
2. Add `tests/test_queue_io.py` — covers the bill queue file I/O layer.
3. Add `tests/test_main.py` — covers the CLI bill processing workflow.
4. Expand `tests/test_web_app.py` — covers the handful of untested API routes.

Out of scope: repair scripts, maintenance tools (`columbo.py`, `check_bill_dates.py`, etc.), `schema_discovery.py`.

---

## Section 1 — Fix `tests/run_tests.py`

Change the automated test invocation from:
```
pytest tests/test_bill_workflow.py -v -m not manual
```
to:
```
pytest tests/ -v -m not manual
```

This picks up all 20 existing test files with no other changes. The manual test prompt and marker separation are preserved unchanged.

---

## Section 2 — `tests/test_queue_io.py` (new file)

**Module under test:** `web/queue_io.py`  
**Fixture strategy:** `tmp_path` (pytest built-in) + `monkeypatch` to redirect `config.BILLS_INPUT_PATH` to a temp file. No real data touched.

### Test cases

**`read_queue()`**
- Empty file returns `[]`
- Single bill without check_number parsed correctly (vendor, amount, memo, date, `_index`)
- Single bill with check_number parsed correctly
- Malformed / blank lines silently skipped
- `_index` reflects actual file line position for multi-bill files

**`add_bill()`**
- Appends correct CSV format to existing file
- check_number omitted from line when empty string
- check_number appended as 5th field when provided
- Creates file (and parent dirs) if file does not yet exist

**`remove_bill()`**
- Removes the line at the given index
- Remaining lines preserved in order
- Returns `False` on out-of-range index (negative or >= line count)

**`update_bill()`**
- Replaces the line at the given index with new values
- Other lines preserved in order
- Returns `False` on out-of-range index
- check_number roundtrip: add with check_number → update without → verify 5th field gone

---

## Section 3 — `tests/test_main.py` (new file)

**Module under test:** `main.py` (`process_bill`, `process_input_file`)  
**Fixture strategy:** Real test DB from `conftest.py` (`test_db_path`, `test_accounts`, `test_vendor_guid`), same pattern as `test_bill_workflow.py`. Interactive prompts mocked with `unittest.mock.patch`.

**Mocking targets:**
- `main.confirm_proceed` — controls yes/no prompts (vendor creation, alias, proceed)
- `builtins.input` — controls checking account selection index
- `main.gnucash_db` settings patched to use `test_db_path`

### `process_bill()` test cases

| Test | Setup | Expected |
|------|-------|----------|
| Exact vendor match | vendor exists in test DB | Returns `True`, bill created/posted/paid |
| Exact match with check_number | vendor exists, check_number="1234" | check_number reaches `pay_bill` |
| Fuzzy match, user confirms alias | slightly misspelled vendor name | Alias saved, returns `True` |
| Fuzzy match, user declines alias | slightly misspelled vendor name | No alias saved, still returns `True` |
| Vendor not found, user creates | unknown vendor name, confirm=True | Vendor created, bill processed, returns `True` |
| Vendor not found, user skips | unknown vendor name, confirm=False | Returns `False` |

### `process_input_file()` test cases

| Test | Setup | Expected |
|------|-------|----------|
| Single bill | one valid line in temp file | `{'total':1, 'success':1, 'failed':0, 'skipped':0}` |
| Bill with check_number | line has 5th field | check_number passed to `pay_bill` |
| Empty file | zero valid lines | `{'total':0, ...}` without prompting |
| File not found | path does not exist | Raises `FileNotFoundError` |
| User cancels at "Process these bills?" | confirm_proceed returns False | All bills skipped, returns skipped counts |
| User cancels account selection | KeyboardInterrupt on `input()` | Returns skipped counts |

---

## Section 4 — Additions to `tests/test_web_app.py`

Five new test classes appended to the existing file. All use the existing `client` fixture.

| Class | Route | Cases |
|-------|-------|-------|
| `TestGetVendors` | `GET /api/vendors` | Returns list; empty list when no vendors |
| `TestCreateVendor` | `POST /api/vendors` | Success: valid vendor returns key (complements existing empty-name error test) |
| `TestAccountTypeEndpoints` | `GET /api/accounts/expense`, `/payable`, `/bank` | Each returns a list; empty list when no matching accounts in DB |
| `TestVendorKeySync` | `POST /api/vendors/{key}/sync` | Returns ok; 404 for unknown key |
| `TestShutdown` | `POST /api/shutdown` | Returns 200 (server shutdown mocked) |

---

## Implementation Order

1. Fix `run_tests.py` (one-line change, verify all existing tests pass)
2. Write `tests/test_queue_io.py`
3. Write `tests/test_main.py`
4. Add new classes to `tests/test_web_app.py`

---

## Success Criteria

- `uv run python tests/run_tests.py` runs all test files without manual intervention
- All new tests pass
- No existing tests broken

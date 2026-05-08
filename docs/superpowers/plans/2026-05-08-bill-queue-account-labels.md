# Bill Queue Account Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the bill queue file with `bill_type` and per-column account override fields, backed by a label registry that maps human-readable preset names to GnuCash account GUIDs.

**Architecture:** A new `BillAccountResolver` class reads `data/bill_account_labels.json` and resolves each bill's three accounts (expense, checking, AP) from preset defaults + per-column overrides + DB name fallback. `parse_input_line`, `queue_io`, and `app.py` are updated to pass the four new fields through the stack. The React frontend gains a `bill_type` input in the bill editor and a bill-types section in Settings.

**Tech Stack:** Python 3.12, FastAPI, React 18 + TypeScript, TanStack Query, pytest, uv

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `data/bill_account_labels.json` | Label registry — presets and labels with name+guid |
| Create | `web/bill_account_resolver.py` | `BillAccountResolver` — resolves bill fields to GUIDs |
| Create | `tests/test_bill_account_resolver.py` | Tests for resolver |
| Modify | `utils.py:48-113` | `parse_input_line` — parse 4 new optional columns |
| Modify | `tests/test_utils.py` | Add tests for new parse columns |
| Modify | `web/queue_io.py:44-81` | `_format_bill_line`, `add_bill`, `update_bill` — new params |
| Modify | `tests/test_queue_io.py` | Add tests for new columns |
| Modify | `web/app.py:122-203` | `BillIn`, `_serialize_bill`, `_process_one_bill`, add two endpoints |
| Modify | `frontend/src/api/bills.ts` | Add `bill_type` to `Bill` and `BillIn` types |
| Create | `frontend/src/api/bill_types.ts` | API client for bill-types endpoints |
| Modify | `frontend/src/pages/BillsQueue.tsx` | Add `bill_type` column to table and editor |
| Modify | `frontend/src/pages/Settings.tsx` | Add Bill Types section |

---

## Task 1: Create registry file and BillAccountResolver

**Files:**
- Create: `data/bill_account_labels.json`
- Create: `web/bill_account_resolver.py`
- Create: `tests/test_bill_account_resolver.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_bill_account_resolver.py`:

```python
"""Tests for web/bill_account_resolver.py."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from bill_processor.web.bill_account_resolver import BillAccountResolver


@pytest.fixture
def registry_path(tmp_path):
    data = {
        "presets": {
            "utility": {
                "expense_acct":  {"name": "Expenses:Utilities", "guid": "exp-1"},
                "checking_acct": {"name": "Assets:Checking",    "guid": "chk-1"},
                "payables_acct": {"name": "Liabilities:AP",     "guid": "ap-1"},
            }
        },
        "labels": {
            "main_checking": {"name": "Assets:Checking",        "guid": "chk-1"},
            "ap":            {"name": "Liabilities:AP",         "guid": "ap-1"},
            "gas_expense":   {"name": "Expenses:Utilities:Gas", "guid": "gas-1"},
        },
    }
    p = tmp_path / "labels.json"
    p.write_text(json.dumps(data))
    return p


@pytest.fixture
def resolver(registry_path):
    return BillAccountResolver(registry_path=registry_path)


class TestResolveAllEmpty:
    def test_returns_none_when_all_empty(self, resolver):
        assert resolver.resolve("", "", "", "") is None


class TestResolvePreset:
    def test_preset_resolves_all_three_guids(self, resolver):
        result = resolver.resolve("utility", "", "", "")
        assert result == {"expense_guid": "exp-1", "checking_guid": "chk-1", "ap_guid": "ap-1"}

    def test_unknown_bill_type_raises_value_error(self, resolver):
        with pytest.raises(ValueError, match="Unknown bill type: 'foo'"):
            resolver.resolve("foo", "", "", "")


class TestResolveOverride:
    def test_label_override_replaces_preset_account(self, resolver):
        result = resolver.resolve("utility", "gas_expense", "", "")
        assert result["expense_guid"] == "gas-1"
        assert result["checking_guid"] == "chk-1"

    def test_bare_name_override_triggers_db_lookup(self, resolver):
        with patch("bill_processor.gnucash_db.get_account_by_name") as mock:
            mock.return_value = {"guid": "db-guid", "name": "Expenses:Custom"}
            result = resolver.resolve("utility", "Expenses:Custom", "", "")
        assert result["expense_guid"] == "db-guid"

    def test_unknown_label_without_preset_triggers_db_lookup(self, resolver):
        with patch("bill_processor.gnucash_db.get_account_by_name") as mock:
            mock.return_value = {"guid": "db-guid2", "name": "Assets:Other"}
            result = resolver.resolve("", "unknown_label", "main_checking", "ap")
        assert result["expense_guid"] == "db-guid2"


class TestResolveNoPreset:
    def test_all_labels_no_preset(self, resolver):
        result = resolver.resolve("", "gas_expense", "main_checking", "ap")
        assert result == {"expense_guid": "gas-1", "checking_guid": "chk-1", "ap_guid": "ap-1"}

    def test_missing_account_raises_value_error(self, resolver):
        with pytest.raises(ValueError, match="expense_acct"):
            resolver.resolve("", "", "main_checking", "ap")


class TestMissingGuid:
    def test_empty_guid_in_preset_triggers_db_lookup(self, tmp_path):
        data = {
            "presets": {
                "noguids": {
                    "expense_acct":  {"name": "Expenses:Test", "guid": ""},
                    "checking_acct": {"name": "Assets:Test",   "guid": ""},
                    "payables_acct": {"name": "Liabilities:AP","guid": ""},
                }
            },
            "labels": {},
        }
        p = tmp_path / "labels.json"
        p.write_text(json.dumps(data))
        r = BillAccountResolver(registry_path=p)
        with patch("bill_processor.gnucash_db.get_account_by_name") as mock:
            mock.return_value = {"guid": "looked-up", "name": "..."}
            result = r.resolve("noguids", "", "", "")
        assert result["expense_guid"] == "looked-up"

    def test_db_lookup_failure_raises_value_error(self, tmp_path):
        data = {
            "presets": {
                "bad": {
                    "expense_acct":  {"name": "Expenses:Missing", "guid": ""},
                    "checking_acct": {"name": "Assets:Missing",   "guid": ""},
                    "payables_acct": {"name": "Liabilities:AP",   "guid": ""},
                }
            },
            "labels": {},
        }
        p = tmp_path / "labels.json"
        p.write_text(json.dumps(data))
        r = BillAccountResolver(registry_path=p)
        with patch("bill_processor.gnucash_db.get_account_by_name", return_value=None):
            with pytest.raises(ValueError, match="Account not found"):
                r.resolve("bad", "", "", "")


class TestSyncGuids:
    def test_sync_populates_missing_guids(self, tmp_path):
        data = {
            "presets": {
                "utility": {
                    "expense_acct":  {"name": "Expenses:Utilities", "guid": ""},
                    "checking_acct": {"name": "Assets:Checking",    "guid": "chk-1"},
                    "payables_acct": {"name": "Liabilities:AP",     "guid": "ap-1"},
                }
            },
            "labels": {
                "gas": {"name": "Expenses:Gas", "guid": ""},
            },
        }
        p = tmp_path / "labels.json"
        p.write_text(json.dumps(data))
        r = BillAccountResolver(registry_path=p)

        def fake_lookup(name):
            return {"guid": f"synced-{name.replace(':', '-')}", "name": name}

        with patch("bill_processor.gnucash_db.get_account_by_name", side_effect=fake_lookup):
            report = r.sync_guids()

        saved = json.loads(p.read_text())
        assert saved["presets"]["utility"]["expense_acct"]["guid"] == "synced-Expenses-Utilities"
        assert saved["labels"]["gas"]["guid"] == "synced-Expenses-Gas"
        assert report["updated"] >= 2
        assert report["failed"] == []

    def test_sync_records_failures(self, tmp_path):
        data = {
            "presets": {
                "bad": {
                    "expense_acct":  {"name": "Expenses:Missing", "guid": ""},
                    "checking_acct": {"name": "Assets:Check",     "guid": "ok"},
                    "payables_acct": {"name": "Liabilities:AP",   "guid": "ok"},
                }
            },
            "labels": {},
        }
        p = tmp_path / "labels.json"
        p.write_text(json.dumps(data))
        r = BillAccountResolver(registry_path=p)
        with patch("bill_processor.gnucash_db.get_account_by_name", return_value=None):
            report = r.sync_guids()
        assert len(report["failed"]) >= 1
        assert "Expenses:Missing" in report["failed"][0]["name"]
```

- [ ] **Step 2: Run to confirm all fail**

```
uv run pytest tests/test_bill_account_resolver.py -v
```

Expected: `ModuleNotFoundError: No module named 'bill_processor.web.bill_account_resolver'`

- [ ] **Step 3: Create `data/bill_account_labels.json` template**

```json
{
  "presets": {},
  "labels": {}
}
```

- [ ] **Step 4: Create `web/bill_account_resolver.py`**

```python
"""Resolve bill_type labels and account names to GnuCash account GUIDs."""
import json
from pathlib import Path
from typing import Optional
from loguru import logger

from bill_processor import config


REGISTRY_PATH = config.PROJECT_ROOT / "data" / "bill_account_labels.json"


class BillAccountResolver:
    def __init__(self, registry_path: Path = None):
        self._path = registry_path or REGISTRY_PATH
        self._registry = self._load()

    def _load(self) -> dict:
        if not self._path.exists():
            return {"presets": {}, "labels": {}}
        with open(self._path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._registry, f, indent=2)

    def resolve(
        self,
        bill_type: str,
        expense_acct: str,
        checking_acct: str,
        payables_acct: str,
    ) -> Optional[dict]:
        """Return {"expense_guid", "checking_guid", "ap_guid"} or None (use global settings).

        Raises ValueError if resolution fails for any configured account.
        """
        if not any([bill_type, expense_acct, checking_acct, payables_acct]):
            return None

        defaults = {"expense_acct": None, "checking_acct": None, "payables_acct": None}
        if bill_type:
            preset = self._registry.get("presets", {}).get(bill_type)
            if preset is None:
                raise ValueError(f"Unknown bill type: '{bill_type}'")
            defaults = dict(preset)

        overrides = {
            "expense_acct": expense_acct.strip() or None,
            "checking_acct": checking_acct.strip() or None,
            "payables_acct": payables_acct.strip() or None,
        }

        resolved = {k: overrides[k] if overrides[k] is not None else defaults[k] for k in defaults}

        out_keys = {"expense_acct": "expense_guid", "checking_acct": "checking_guid", "payables_acct": "ap_guid"}
        result = {}
        for field, out_key in out_keys.items():
            value = resolved[field]
            if value is None:
                raise ValueError(f"No {field} configured for this bill")
            result[out_key] = self._to_guid(field, value)

        return result

    def _to_guid(self, field: str, value) -> str:
        if isinstance(value, dict):
            guid = value.get("guid", "")
            if guid:
                return guid
            name = value.get("name", "")
            if not name:
                raise ValueError(f"Preset {field} has neither name nor guid")
            return self._db_lookup(name)

        label_entry = self._registry.get("labels", {}).get(value)
        if label_entry:
            guid = label_entry.get("guid", "")
            if guid:
                return guid
            return self._db_lookup(label_entry.get("name", value))

        return self._db_lookup(value)

    def _db_lookup(self, name: str) -> str:
        from bill_processor import gnucash_db
        account = gnucash_db.get_account_by_name(name)
        if account is None:
            raise ValueError(f"Account not found in GnuCash: '{name}'")
        logger.warning(f"Resolved account by name lookup (no GUID in registry): '{name}'")
        return account["guid"]

    def sync_guids(self) -> dict:
        """Populate empty GUIDs by name lookup. Returns {"updated": N, "failed": [...]}."""
        from bill_processor import gnucash_db
        updated = 0
        failed = []

        def _sync_entry(entry: dict) -> None:
            nonlocal updated
            if entry.get("guid"):
                return
            name = entry.get("name", "")
            if not name:
                return
            account = gnucash_db.get_account_by_name(name)
            if account:
                entry["guid"] = account["guid"]
                updated += 1
            else:
                failed.append({"name": name, "error": "Account not found in GnuCash"})

        for preset in self._registry.get("presets", {}).values():
            for acct_entry in preset.values():
                if isinstance(acct_entry, dict):
                    _sync_entry(acct_entry)

        for label_entry in self._registry.get("labels", {}).values():
            if isinstance(label_entry, dict):
                _sync_entry(label_entry)

        if updated:
            self._save()

        return {"updated": updated, "failed": failed}
```

- [ ] **Step 5: Run tests to confirm they pass**

```
uv run pytest tests/test_bill_account_resolver.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add data/bill_account_labels.json web/bill_account_resolver.py tests/test_bill_account_resolver.py
git commit -m "feat: add BillAccountResolver and label registry"
```

---

## Task 2: Extend parse_input_line for 4 new columns

**Files:**
- Modify: `utils.py:48-113`
- Modify: `tests/test_utils.py`

- [ ] **Step 1: Write failing tests**

Add this class to `tests/test_utils.py` (after the existing `TestParseInputLine` class):

```python
class TestParseInputLineNewColumns:
    def test_no_new_columns_defaults_to_empty_strings(self):
        result = parse_input_line("Acme, 100.00, memo, 2026-01-15")
        assert result["bill_type"] == ""
        assert result["expense_acct"] == ""
        assert result["checking_acct"] == ""
        assert result["payables_acct"] == ""

    def test_bill_type_only(self):
        result = parse_input_line("Acme, 100.00, memo, 2026-01-15, 1042, utility")
        assert result["check_number"] == "1042"
        assert result["bill_type"] == "utility"
        assert result["expense_acct"] == ""

    def test_all_four_new_columns(self):
        result = parse_input_line("Acme, 100.00, memo, 2026-01-15, 1042, utility, gas, secondary, ap")
        assert result["bill_type"] == "utility"
        assert result["expense_acct"] == "gas"
        assert result["checking_acct"] == "secondary"
        assert result["payables_acct"] == "ap"

    def test_empty_check_number_with_bill_type(self):
        result = parse_input_line("Acme, 100.00, memo, 2026-01-15, , utility")
        assert result["check_number"] == ""
        assert result["bill_type"] == "utility"

    def test_empty_bill_type_with_explicit_expense_acct(self):
        result = parse_input_line("Acme, 100.00, memo, 2026-01-15, , , Expenses:Custom, , ")
        assert result["bill_type"] == ""
        assert result["expense_acct"] == "Expenses:Custom"
        assert result["checking_acct"] == ""

    def test_existing_lines_unchanged(self):
        result = parse_input_line("Acme Corp, 100.00, supplies, 2026-01-15, 1234")
        assert result["vendor_name"] == "Acme Corp"
        assert result["check_number"] == "1234"
        assert result["bill_type"] == ""
```

- [ ] **Step 2: Run to confirm failure**

```
uv run pytest tests/test_utils.py::TestParseInputLineNewColumns -v
```

Expected: `KeyError: 'bill_type'`

- [ ] **Step 3: Update `parse_input_line` in `utils.py`**

Replace the `return {` block at line 107 and the `check_number` line at 105:

```python
    # Parse check number (optional 5th field)
    check_number = parts[4].strip() if len(parts) > 4 else ""

    # Parse new account routing fields (optional columns 6-9)
    bill_type     = parts[5].strip() if len(parts) > 5 else ""
    expense_acct  = parts[6].strip() if len(parts) > 6 else ""
    checking_acct = parts[7].strip() if len(parts) > 7 else ""
    payables_acct = parts[8].strip() if len(parts) > 8 else ""

    return {
        'vendor_name':   vendor_name,
        'amount':        amount,
        'memo':          memo,
        'date':          bill_date,
        'check_number':  check_number,
        'bill_type':     bill_type,
        'expense_acct':  expense_acct,
        'checking_acct': checking_acct,
        'payables_acct': payables_acct,
    }
```

- [ ] **Step 4: Run tests to confirm pass**

```
uv run pytest tests/test_utils.py -v
```

Expected: all tests pass (including existing ones).

- [ ] **Step 5: Commit**

```bash
git add utils.py tests/test_utils.py
git commit -m "feat: parse bill_type and account routing columns in parse_input_line"
```

---

## Task 3: Extend queue_io for 4 new columns

**Files:**
- Modify: `web/queue_io.py:44-81`
- Modify: `tests/test_queue_io.py`

- [ ] **Step 1: Write failing tests**

Add this class to `tests/test_queue_io.py`:

```python
class TestNewAccountColumns:
    def test_no_new_columns_format_unchanged(self, queue_path):
        queue_io.add_bill("Acme", 100.0, "supplies", date(2026, 1, 15))
        line = queue_path.read_text().strip()
        assert line == "Acme, 100.00, supplies, 2026-01-15"

    def test_check_number_only_format_unchanged(self, queue_path):
        queue_io.add_bill("Acme", 100.0, "supplies", date(2026, 1, 15), "1042")
        line = queue_path.read_text().strip()
        assert line == "Acme, 100.00, supplies, 2026-01-15, 1042"

    def test_bill_type_written_and_read_back(self, queue_path):
        queue_io.add_bill("Acme", 100.0, "memo", date(2026, 1, 15), "1042", "utility")
        result = queue_io.read_queue()
        assert result[0]["bill_type"] == "utility"
        assert result[0]["check_number"] == "1042"

    def test_all_four_new_columns_roundtrip(self, queue_path):
        queue_io.add_bill("Acme", 100.0, "memo", date(2026, 1, 15), "1042",
                          "utility", "gas_expense", "secondary", "ap")
        result = queue_io.read_queue()
        assert result[0]["bill_type"] == "utility"
        assert result[0]["expense_acct"] == "gas_expense"
        assert result[0]["checking_acct"] == "secondary"
        assert result[0]["payables_acct"] == "ap"

    def test_empty_check_number_with_bill_type(self, queue_path):
        queue_io.add_bill("Acme", 100.0, "memo", date(2026, 1, 15), "", "grocery")
        result = queue_io.read_queue()
        assert result[0]["check_number"] == ""
        assert result[0]["bill_type"] == "grocery"

    def test_update_bill_preserves_new_columns(self, queue_path):
        queue_io.add_bill("Acme", 100.0, "memo", date(2026, 1, 15), "1042", "utility")
        queue_io.update_bill(0, "Acme", 200.0, "updated", date(2026, 2, 1), "1043", "grocery")
        result = queue_io.read_queue()
        assert result[0]["amount"] == 200.0
        assert result[0]["bill_type"] == "grocery"
```

- [ ] **Step 2: Run to confirm failure**

```
uv run pytest tests/test_queue_io.py::TestNewAccountColumns -v
```

Expected: failures on `bill_type` key or wrong line format.

- [ ] **Step 3: Update `web/queue_io.py`**

Replace `_format_bill_line` and update `add_bill` and `update_bill` signatures:

```python
def _format_bill_line(
    vendor_name: str, amount: float, memo: str, bill_date: date,
    check_number: str = "",
    bill_type: str = "", expense_acct: str = "", checking_acct: str = "", payables_acct: str = "",
) -> str:
    memo = memo.strip() or "no memo"
    parts = [vendor_name, f"{amount:.2f}", memo, bill_date.isoformat()]
    new_cols = [bill_type, expense_acct, checking_acct, payables_acct]
    if any(new_cols):
        parts.append(check_number)
        parts.extend(new_cols)
    elif check_number:
        parts.append(check_number)
    return ", ".join(parts) + "\n"


def add_bill(
    vendor_name: str, amount: float, memo: str, bill_date: date,
    check_number: str = "",
    bill_type: str = "", expense_acct: str = "", checking_acct: str = "", payables_acct: str = "",
) -> None:
    """Append a bill to the queue file."""
    line = _format_bill_line(vendor_name, amount, memo, bill_date, check_number,
                             bill_type, expense_acct, checking_acct, payables_acct)
    config.BILLS_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.BILLS_INPUT_PATH, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info(f"Queued bill: {vendor_name} ${amount:.2f}")


def update_bill(
    file_line_index: int, vendor_name: str, amount: float, memo: str, bill_date: date,
    check_number: str = "",
    bill_type: str = "", expense_acct: str = "", checking_acct: str = "", payables_acct: str = "",
) -> bool:
    """Replace the bill at the given file line index with updated values."""
    lines = _read_raw_lines()
    if file_line_index < 0 or file_line_index >= len(lines):
        logger.warning(f"update_bill: line index {file_line_index} out of range (file has {len(lines)} lines)")
        return False
    lines[file_line_index] = _format_bill_line(vendor_name, amount, memo, bill_date, check_number,
                                                bill_type, expense_acct, checking_acct, payables_acct)
    _write_raw_lines(lines)
    return True
```

- [ ] **Step 4: Run tests to confirm pass**

```
uv run pytest tests/test_queue_io.py -v
```

Expected: all tests pass (including existing ones).

- [ ] **Step 5: Commit**

```bash
git add web/queue_io.py tests/test_queue_io.py
git commit -m "feat: add bill_type and account columns to queue_io"
```

---

## Task 4: Update app.py — BillIn, _serialize_bill, _process_one_bill, new endpoints

**Files:**
- Modify: `web/app.py:122-203`

- [ ] **Step 1: Update `BillIn` Pydantic model** at line 198

Replace:
```python
class BillIn(BaseModel):
    vendor_name: str
    amount: float
    memo: str = ""
    bill_date: str = ""
    check_number: str = ""
```

With:
```python
class BillIn(BaseModel):
    vendor_name: str
    amount: float
    memo: str = ""
    bill_date: str = ""
    check_number: str = ""
    bill_type: str = ""
    expense_acct: str = ""
    checking_acct: str = ""
    payables_acct: str = ""
```

- [ ] **Step 2: Update `_serialize_bill`** at line 182

Replace:
```python
def _serialize_bill(bill: dict) -> dict:
    """Convert a queue_io bill dict to a JSON-serializable form."""
    return {
        "index": bill["_index"],
        "vendor_name": bill["vendor_name"],
        "amount": bill["amount"],
        "memo": bill.get("memo", ""),
        "date": bill["date"].isoformat() if hasattr(bill["date"], "isoformat") else str(bill["date"]),
        "check_number": bill.get("check_number", ""),
    }
```

With:
```python
def _serialize_bill(bill: dict) -> dict:
    """Convert a queue_io bill dict to a JSON-serializable form."""
    return {
        "index": bill["_index"],
        "vendor_name": bill["vendor_name"],
        "amount": bill["amount"],
        "memo": bill.get("memo", ""),
        "date": bill["date"].isoformat() if hasattr(bill["date"], "isoformat") else str(bill["date"]),
        "check_number": bill.get("check_number", ""),
        "bill_type": bill.get("bill_type", ""),
        "expense_acct": bill.get("expense_acct", ""),
        "checking_acct": bill.get("checking_acct", ""),
        "payables_acct": bill.get("payables_acct", ""),
    }
```

- [ ] **Step 3: Update `add_bill` route** at line 325 to pass new fields

Replace:
```python
    queue_io.add_bill(bill.vendor_name, bill.amount, bill.memo, parsed_date, bill.check_number)
```
With:
```python
    queue_io.add_bill(bill.vendor_name, bill.amount, bill.memo, parsed_date, bill.check_number,
                      bill.bill_type, bill.expense_acct, bill.checking_acct, bill.payables_acct)
```

- [ ] **Step 4: Update `update_bill` route** at line 339 to pass new fields

Replace:
```python
    ok = queue_io.update_bill(index, bill.vendor_name, bill.amount, bill.memo, parsed_date, bill.check_number)
```
With:
```python
    ok = queue_io.update_bill(index, bill.vendor_name, bill.amount, bill.memo, parsed_date, bill.check_number,
                              bill.bill_type, bill.expense_acct, bill.checking_acct, bill.payables_acct)
```

- [ ] **Step 5: Update `_process_one_bill`** at line 122

Replace the full function body:
```python
def _process_one_bill(bill: dict) -> dict:
    """Process a single bill: create → post → pay in GnuCash."""
    from bill_processor.web.bill_account_resolver import BillAccountResolver
    resolver = BillAccountResolver()
    try:
        resolved = resolver.resolve(
            bill.get("bill_type", ""),
            bill.get("expense_acct", ""),
            bill.get("checking_acct", ""),
            bill.get("payables_acct", ""),
        )
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    if resolved:
        expense_guid   = resolved["expense_guid"]
        checking_guid  = resolved["checking_guid"]
        ap_guid        = resolved["ap_guid"]
    else:
        ap_guid        = settings.ap_account_guid
        checking_guid  = settings.checking_account_guid
        expense_guid   = settings.expense_account_guid
        if not ap_guid or not checking_guid or not expense_guid:
            return {
                "ok": False,
                "error": "Processing accounts not configured — visit Settings > Processing Accounts",
            }

    ap_account       = gnucash_db.get_account_by_guid(ap_guid)
    checking_account = gnucash_db.get_account_by_guid(checking_guid)
    if not ap_account or not checking_account:
        return {
            "ok": False,
            "error": "Configured account not found in GnuCash — update Settings > Processing Accounts",
        }
    logger.info("Using A/P account: {} ({})", ap_account["name"], ap_guid[:8])
    logger.info("Using checking account: {} ({})", checking_account["name"], checking_guid[:8])

    vm = VendorManager()
    vendor, match_type = vm.find_vendor(bill["vendor_name"])
    if vendor is None:
        return {"ok": False, "error": f"Vendor not found: {bill['vendor_name']}"}

    logger.info(f"Processing bill: {bill['vendor_name']} ${bill['amount']} on {bill['date']}")
    try:
        bill_guid = gnucash_db.create_bill(
            vendor_guid=vendor["gnucash_guid"],
            expense_account_guid=expense_guid,
            amount=bill["amount"],
            memo=bill.get("memo", ""),
            bill_date=bill["date"],
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill["date"],
            ap_account_guid=ap_guid,
        )
        gnucash_db.pay_bill(
            bill_guid=bill_guid,
            payment_date=bill["date"],
            checking_account_guid=checking_guid,
            check_number=bill.get("check_number", ""),
        )
        logger.info(f"Bill posted: {bill['vendor_name']} ${bill['amount']}")
        return {"ok": True}
    except Exception as exc:
        logger.exception(f"Bill processing failed for '{bill['vendor_name']}': {exc}")
        return {"ok": False, "error": str(exc)}
```

- [ ] **Step 6: Add bill-types endpoints** — add after the vendors section (after line ~449 in app.py):

```python
# ---------------------------------------------------------------------------
# API Routes: Bill Types
# ---------------------------------------------------------------------------

@app.get("/api/bill-types")
def get_bill_types():
    from bill_processor.web.bill_account_resolver import BillAccountResolver
    r = BillAccountResolver()
    return {
        "presets": r._registry.get("presets", {}),
        "labels": r._registry.get("labels", {}),
    }


@app.get("/api/bill-types/sync")
def sync_bill_type_guids():
    from bill_processor.web.bill_account_resolver import BillAccountResolver
    r = BillAccountResolver()
    result = r.sync_guids()
    return result
```

- [ ] **Step 7: Add GUID sync to startup lifespan in `web/app.py`**

In the `lifespan` function (around line 33), add bill-type GUID sync after the existing vendor sync block:

Find:
```python
    except Exception as e:
        logger.warning(f"Startup vendor sync failed: {e}")
    logger.info("Server running on http://127.0.0.1:7432")
```

Replace with:
```python
    except Exception as e:
        logger.warning(f"Startup vendor sync failed: {e}")
    try:
        from bill_processor.web.bill_account_resolver import BillAccountResolver
        report = BillAccountResolver().sync_guids()
        if report["updated"]:
            logger.info(f"Startup bill-type GUID sync: {report['updated']} updated")
        if report["failed"]:
            logger.warning(f"Startup bill-type GUID sync: {len(report['failed'])} failed")
    except Exception as e:
        logger.warning(f"Startup bill-type GUID sync failed: {e}")
    logger.info("Server running on http://127.0.0.1:7432")
```

- [ ] **Step 9: Run existing tests to confirm nothing broken**

```
uv run pytest tests/test_web_app.py -v
```

Expected: all existing tests pass.

- [ ] **Step 10: Commit**

```bash
git add web/app.py
git commit -m "feat: wire BillAccountResolver into _process_one_bill, add bill-types endpoints"
```

---

## Task 5: Update frontend TypeScript types

**Files:**
- Modify: `frontend/src/api/bills.ts`
- Create: `frontend/src/api/bill_types.ts`

- [ ] **Step 1: Update `frontend/src/api/bills.ts`**

Replace the file contents:
```typescript
import api from './client'

export interface Bill {
  index: number
  vendor_name: string
  amount: number
  memo: string
  date: string
  check_number: string
  bill_type: string
  expense_acct: string
  checking_acct: string
  payables_acct: string
}

export interface BillIn {
  vendor_name: string
  amount: number
  memo?: string
  bill_date?: string
  check_number?: string
  bill_type?: string
  expense_acct?: string
  checking_acct?: string
  payables_acct?: string
}

export const getBills     = () => api.get<Bill[]>('/bills').then(r => r.data)
export const addBill      = (b: BillIn) => api.post('/bills', b).then(r => r.data)
export const updateBill   = (index: number, b: BillIn) => api.put(`/bills/${index}`, b).then(r => r.data)
export const deleteBill   = (index: number) => api.delete(`/bills/${index}`).then(r => r.data)
export const postBill     = (index: number) => api.post(`/bills/${index}/post`).then(r => r.data)
export const postAllBills = () => api.post('/bills/post-all').then(r => r.data)
```

- [ ] **Step 2: Create `frontend/src/api/bill_types.ts`**

```typescript
import api from './client'

export interface AccountEntry {
  name: string
  guid: string
}

export interface Preset {
  expense_acct: AccountEntry
  checking_acct: AccountEntry
  payables_acct: AccountEntry
}

export interface BillTypesResponse {
  presets: Record<string, Preset>
  labels: Record<string, AccountEntry>
}

export const getBillTypes  = () => api.get<BillTypesResponse>('/bill-types').then(r => r.data)
export const syncBillTypes = () => api.get<{ updated: number; failed: { name: string; error: string }[] }>('/bill-types/sync').then(r => r.data)
```

- [ ] **Step 3: Confirm TypeScript compiles**

```
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/bills.ts frontend/src/api/bill_types.ts
git commit -m "feat: add bill_type fields to frontend Bill/BillIn types, add bill_types API client"
```

---

## Task 6: Update BillsQueue.tsx — add bill_type column

**Files:**
- Modify: `frontend/src/pages/BillsQueue.tsx`

The goal: add a `bill_type` column to the display table and a `bill_type` input to `EditableRow`.

- [ ] **Step 1: Add `bill_type` to `BillRow` display**

In `BillRow`, the `<tr>` currently has 5 data cells + 1 actions cell. Add a cell for `bill_type` between `check_number` and actions:

Find this block in `BillRow`:
```tsx
        <td className="px-3 py-2 text-sm text-slate-500">{bill.check_number}</td>
        <td className="px-3 py-2">
```

Replace with:
```tsx
        <td className="px-3 py-2 text-sm text-slate-500">{bill.check_number}</td>
        <td className="px-3 py-2 text-sm text-slate-400 italic">{bill.bill_type}</td>
        <td className="px-3 py-2">
```

Also update `colSpan={6}` in the error row to `colSpan={7}`.

- [ ] **Step 2: Add `bill_type` state and input to `EditableRow`**

Add state after the existing `check` state:
```tsx
  const [billType, setBillType] = useState(initial?.bill_type ?? '')
```

Add an input cell for bill_type between the check# cell and actions cell. Find:
```tsx
      <td className="px-2 py-1"><Input className="h-7 text-sm" value={check} onChange={e => setCheck(e.target.value)} placeholder="Check #" /></td>
      <td className="px-2 py-1">
```

Replace with:
```tsx
      <td className="px-2 py-1"><Input className="h-7 text-sm" value={check} onChange={e => setCheck(e.target.value)} placeholder="Check #" /></td>
      <td className="px-2 py-1"><Input className="h-7 text-sm" value={billType} onChange={e => setBillType(e.target.value)} placeholder="Bill type" /></td>
      <td className="px-2 py-1">
```

- [ ] **Step 3: Include `bill_type` in `handleSave`**

Find:
```tsx
    onSave({ vendor_name: vendor, amount: amt, memo, bill_date: date, check_number: check })
```

Replace with:
```tsx
    onSave({ vendor_name: vendor, amount: amt, memo, bill_date: date, check_number: check, bill_type: billType })
```

- [ ] **Step 4: Add `bill_type` column header to the table**

Find this block in `BillsQueue.tsx` (~line 375):
```tsx
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Check #</th>
              <th className="px-3 py-2 text-xs font-medium text-slate-500 uppercase">Actions</th>
```

Replace with:
```tsx
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Check #</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Bill Type</th>
              <th className="px-3 py-2 text-xs font-medium text-slate-500 uppercase">Actions</th>
```

- [ ] **Step 5: Build and verify no TypeScript errors**

```
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/BillsQueue.tsx
git commit -m "feat: add bill_type column to BillsQueue table and editor"
```

---

## Task 7: Update Settings.tsx — Bill Types section

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Import new API functions at top of `Settings.tsx`**

Add after the existing imports:
```tsx
import { getBillTypes, syncBillTypes, type BillTypesResponse } from '../api/bill_types'
```

- [ ] **Step 2: Add query and sync mutation state inside the `Settings` component**

Add after the existing `useQuery` calls:
```tsx
  const { data: billTypes, refetch: refetchBillTypes } = useQuery<BillTypesResponse>({
    queryKey: ['billTypes'],
    queryFn: getBillTypes,
  })
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<{ updated: number; failed: { name: string; error: string }[] } | null>(null)

  const handleSyncBillTypes = async () => {
    setSyncing(true)
    setSyncResult(null)
    try {
      const result = await syncBillTypes()
      setSyncResult(result)
      refetchBillTypes()
    } finally {
      setSyncing(false)
    }
  }
```

- [ ] **Step 3: Add Bill Types section to the JSX**

Add after the existing `<Section title="Processing Accounts">` block, before the Cash Entry section:

```tsx
      <Section title="Bill Types">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs text-slate-500">
            Presets map a label to expense, checking, and AP accounts.
            Edit <code className="bg-slate-100 px-1 rounded">data/bill_account_labels.json</code> to add or change presets.
          </p>
          <Button size="sm" variant="outline" onClick={handleSyncBillTypes} disabled={syncing}>
            {syncing ? 'Syncing...' : 'Sync GUIDs'}
          </Button>
        </div>
        {syncResult && (
          <div className={`text-xs mb-3 p-2 rounded ${syncResult.failed.length > 0 ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
            {syncResult.updated} account(s) updated.
            {syncResult.failed.length > 0 && (
              <ul className="mt-1 list-disc pl-4">
                {syncResult.failed.map((f, i) => (
                  <li key={i}>{f.name}: {f.error}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {!billTypes || Object.keys(billTypes.presets).length === 0 ? (
          <p className="text-xs text-slate-400 italic">No presets defined yet.</p>
        ) : (
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-slate-200">
                <th className="text-left py-1 pr-3 font-medium text-slate-600">Preset</th>
                <th className="text-left py-1 pr-3 font-medium text-slate-600">Expense</th>
                <th className="text-left py-1 pr-3 font-medium text-slate-600">Checking</th>
                <th className="text-left py-1 font-medium text-slate-600">AP</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(billTypes.presets).map(([name, p]) => (
                <tr key={name} className="border-b border-slate-100">
                  <td className="py-1 pr-3 font-medium text-slate-700">{name}</td>
                  <td className={`py-1 pr-3 ${p.expense_acct.guid ? 'text-slate-600' : 'text-amber-600'}`}>
                    {p.expense_acct.name || '—'}{!p.expense_acct.guid && ' ⚠'}
                  </td>
                  <td className={`py-1 pr-3 ${p.checking_acct.guid ? 'text-slate-600' : 'text-amber-600'}`}>
                    {p.checking_acct.name || '—'}{!p.checking_acct.guid && ' ⚠'}
                  </td>
                  <td className={`py-1 ${p.payables_acct.guid ? 'text-slate-600' : 'text-amber-600'}`}>
                    {p.payables_acct.name || '—'}{!p.payables_acct.guid && ' ⚠'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
```

- [ ] **Step 4: Build and verify no TypeScript errors**

```
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Settings.tsx
git commit -m "feat: add Bill Types section to Settings page with GUID sync"
```

---

## Task 8: Full test run and frontend build

- [ ] **Step 1: Run the full test suite**

```
uv run python tests/run_tests.py
```

Expected: all tests pass, 0 failures.

- [ ] **Step 2: Build the frontend**

```
cd frontend && npm run build
```

Expected: build succeeds, no TypeScript errors.

- [ ] **Step 3: Start the server and smoke-test**

```
uv run uvicorn bill_processor.web.app:app --reload --port 7432
```

Open http://localhost:7432, navigate to Bills Queue, add a bill with a bill_type value (e.g. `utility`), confirm it appears in the table.

Navigate to Settings, confirm the Bill Types section renders. If `data/bill_account_labels.json` has presets, confirm they appear in the table.

- [ ] **Step 4: Final commit if any last-minute fixes were needed**

```bash
git add -p
git commit -m "fix: post-integration corrections"
```

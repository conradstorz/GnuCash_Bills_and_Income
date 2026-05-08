# Bill Queue Account Labels Design

**Date:** 2026-05-08  
**Status:** Approved

## Problem

`bills_to_process.txt` stores what to pay (vendor, amount, memo, date, check number) but not *how* to route each bill through GnuCash accounts. The three accounts required for the create→post→pay workflow (expense, checking, accounts payable) come from global settings, forcing every bill to share the same accounts. Different bills need different expense accounts; some may also need different checking or AP accounts.

## Solution

Extend the queue file format with four new optional columns — `bill_type`, `expense_acct`, `checking_acct`, `payables_acct` — and introduce a label registry (`data/bill_account_labels.json`) that maps human-readable labels to GnuCash account names and GUIDs.

---

## 1. Queue File Format

File: `data/bills_to_process.txt`

### Column order

```
vendor_name, amount, memo, date, check_number, bill_type, expense_acct, checking_acct, payables_acct
```

Only `vendor_name` and `amount` are required. All other columns are optional. Existing files (no new columns) parse identically — fully backwards compatible.

### Example rows

```csv
Duke Energy, 120.00, electric, 2026-05-08, 1043, utility, , ,
Kroger, 45.00, groceries, 2026-05-08, 1042, grocery, , ,
Duke Energy, 45.00, gas line, 2026-05-08, 1044, utility, gas_expense, ,
AT&T, 89.00, cell phones, 2026-05-08, , telecom, , secondary_checking,
Plumber LLC, 500.00, emergency repair, 2026-05-08, , , Expenses:Repairs, main_checking, ap
```

### Resolution rules (applied per bill at processing time)

1. If `bill_type` is set, load the preset's three accounts as defaults.
2. Any non-empty per-column value overrides the corresponding preset value.
3. Resolved value (label string or bare account name) is looked up via the registry (see §2).
4. If all three columns are blank and `bill_type` is absent, fall back to global `settings` (existing behavior).
5. If no account can be resolved after all steps, raise a descriptive error — the bill is not processed.

---

## 2. Label Registry

File: `data/bill_account_labels.json`

Two top-level keys: `presets` (named bill-type categories) and `labels` (simple account aliases).

```json
{
  "presets": {
    "utility": {
      "expense_acct":  { "name": "Expenses:Utilities",           "guid": "" },
      "checking_acct": { "name": "Assets:Checking:Main",         "guid": "" },
      "payables_acct": { "name": "Liabilities:Accounts Payable", "guid": "" }
    },
    "grocery": {
      "expense_acct":  { "name": "Expenses:Groceries",           "guid": "" },
      "checking_acct": { "name": "Assets:Checking:Main",         "guid": "" },
      "payables_acct": { "name": "Liabilities:Accounts Payable", "guid": "" }
    },
    "telecom": {
      "expense_acct":  { "name": "Expenses:Phone & Internet",    "guid": "" },
      "checking_acct": { "name": "Assets:Checking:Main",         "guid": "" },
      "payables_acct": { "name": "Liabilities:Accounts Payable", "guid": "" }
    }
  },
  "labels": {
    "main_checking":      { "name": "Assets:Checking:Main",           "guid": "" },
    "secondary_checking": { "name": "Assets:Checking:Secondary",      "guid": "" },
    "ap":                 { "name": "Liabilities:Accounts Payable",   "guid": "" },
    "gas_expense":        { "name": "Expenses:Utilities:Gas",         "guid": "" }
  }
}
```

- `name` is the exact colon-separated GnuCash account path — human-readable and used as fallback.
- `guid` is the GnuCash account GUID — used as the fast path; populated by the sync utility.
- GUIDs left as `""` trigger a name-based DB lookup with a logged warning.

---

## 3. Resolution & Processing Logic

### New module: `web/bill_account_resolver.py`

```python
class BillAccountResolver:
    def resolve(self, bill_type: str, expense_acct: str,
                checking_acct: str, payables_acct: str) -> dict:
        """
        Returns {"expense_guid": ..., "checking_guid": ..., "ap_guid": ...}
        Raises ValueError with descriptive message on failure.
        """
```

**Resolution steps for each account column:**

1. Start with preset values from `bill_type` as defaults (if `bill_type` is set and found in registry).
2. Apply any non-empty per-column override, replacing the preset value.
3. For each resolved account value:
   - If it is a `{name, guid}` object (came from preset, no override): use `guid` directly; if `guid` is empty, look up by `name` in GnuCash DB and log a warning.
   - If it is a string (per-column override): check `labels` registry first → use `guid`; if not in `labels`, treat as a bare colon-separated account name path and look up GUID in GnuCash DB.
4. If resolution fails at all steps → raise `ValueError`.
5. If all columns are blank and no `bill_type` → use `settings` globals.

### Changes to existing code

| File | Change |
|---|---|
| `utils.py` `parse_input_line` | Parse 4 new optional columns; default all to `""` |
| `web/queue_io.py` `_format_bill_line`, `add_bill`, `update_bill` | Add 4 new optional parameters with `""` defaults |
| `web/app.py` `BillIn` | Add 4 new optional fields |
| `web/app.py` `_process_one_bill` | Call `resolver.resolve(...)` to get GUIDs; pass to existing DB calls |
| `web/app.py` `_serialize_bill` | Include 4 new fields in serialized output |

---

## 4. Registry Management

### GUID sync endpoint

`GET /api/bill-types/sync` — scans GnuCash accounts, matches by name, writes resolved GUIDs back into `bill_account_labels.json`. Called automatically at server startup (alongside vendor sync) and available as a manual trigger from the settings page.

### Settings page additions

- Read-only table: all presets and labels with their resolved account names (confirms GUIDs are valid)
- "Sync GUIDs" button calling the sync endpoint
- Full CRUD UI for presets/labels is a follow-on feature; file is edited directly for now

---

## 5. Error Handling

| Situation | Behavior |
|---|---|
| `bill_type` not in registry | `{"ok": false, "error": "Unknown bill type: 'foo'"}` |
| Label not found, name lookup fails | Descriptive error surfaced to UI |
| GUID stale (account deleted in GnuCash) | Falls back to name lookup; fails with error if name also not found |
| All columns blank, no `bill_type`, no global settings | `{"ok": false, "error": "No accounts configured for this bill"}` |
| Existing bills (no new columns) | Resolved via global settings — backwards compatible |

---

## 6. Out of Scope

- Full CRUD UI for managing presets and labels (follow-on)
- Automatic preset suggestion based on vendor history
- Multi-currency support per bill type

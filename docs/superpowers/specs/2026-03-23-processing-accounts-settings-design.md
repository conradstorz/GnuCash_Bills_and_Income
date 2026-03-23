# Processing Accounts Settings — Design Spec

**Date:** 2026-03-23
**Status:** Approved

## Problem

The bill processing pipeline selects the A/P account via `ensure_ap_account_exists()` (first PAYABLE account found) and the checking account via `get_checking_accounts()[0]` (first BANK account alphabetically). Neither selection is logged or surfaced to the user. If the wrong account is used, the only way to notice is by inspecting GnuCash directly. Processing must be blocked until the user explicitly configures both accounts.

## Goal

Add a dedicated settings page where the user selects one A/P account and one checking account. These persist across sessions. Bill processing is blocked until both are configured, and both are logged at INFO level when a bill is processed.

---

## New `gnucash_db` Function

A new function `get_payable_accounts() -> List[Dict]` must be added to `gnucash_db.py`, following the exact same pattern as `get_checking_accounts()`:

```python
def get_payable_accounts() -> List[Dict]:
    """Get all non-placeholder Accounts Payable (PAYABLE-type) accounts."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT guid, name, description FROM accounts
            WHERE account_type = ? AND placeholder = ?
            ORDER BY name
        """, (config.ACCOUNT_TYPE_PAYABLE, config.PLACEHOLDER_FALSE))
        return [dict(row) for row in cursor]
```

This is required by the settings page route. The existing `get_ap_account_guid()` and `ensure_ap_account_exists()` are single-account helpers and are not used by the new settings page.

---

## Data Model & Persistence

Two new fields in `settings_manager.py`, persisted to `data/user_settings.json`:

- `ap_account_guid: Optional[str]` — GUID of the selected A/P (PAYABLE) account. Default `None`.
- `checking_account_guid: Optional[str]` — GUID of the selected checking (BANK) account. Default `None`.

A convenience property:

```python
@property
def processing_accounts_configured(self) -> bool:
    return bool(self.ap_account_guid and self.checking_account_guid)
```

**Reset behavior:** Both fields default to `None`. A settings reset (via the `/settings` Reset button) intentionally clears these fields, re-blocking processing until the user reconfigures them. This is correct behavior — after a database switch, the previously selected GUIDs may not exist in the new database.

---

## New Routes

| Method | Route | Purpose |
|--------|-------|---------|
| `GET` | `/settings/processing-accounts` | Renders the page — loads all PAYABLE and BANK accounts from GnuCash via `get_payable_accounts()` and `get_checking_accounts()`, passes current selections from settings |
| `POST` | `/settings/processing-accounts/ap-account` | HTMX — receives `ap_account_guid`, validates it exists in GnuCash, saves to settings, returns updated A/P section partial |
| `POST` | `/settings/processing-accounts/checking-account` | HTMX — receives `checking_account_guid`, validates it exists in GnuCash, saves to settings, returns updated checking section partial |

**GUID validation on POST:** Before saving, each POST route verifies the submitted GUID exists in GnuCash by checking whether it appears in the respective account list (`get_payable_accounts()` or `get_checking_accounts()`). An invalid or unknown GUID returns the section partial with an inline error message and does not update settings.

**HTMX partial response content:** Each POST returns the full updated section (radio button list with the new selection reflected, plus an inline `✓ Saved` confirmation). This matches the pattern used on the existing `/settings` page.

---

## Template & Navigation

**New template:** `web/templates/settings_processing_accounts.html`

Two independent HTMX sections:

- **A/P Accounts section** — radio buttons listing all PAYABLE accounts (`name`, `guid`). Current selection pre-checked. On change, POSTs to `/settings/processing-accounts/ap-account`. Shows inline `✓ Saved` confirmation after successful save, inline error on invalid GUID.
- **Checking Accounts section** — same pattern for all BANK accounts, POSTs to `/settings/processing-accounts/checking-account`.

**Navigation additions:**
- `/settings` page gets a "Processing Accounts →" link at the top.
- Dashboard queued-bills card gets a "Configure processing accounts" link near the process buttons — always visible, especially prominent when buttons are greyed out.

---

## Dashboard Button Gating

The following routes pass `processing_accounts_configured` (bool) to their templates:

- `GET /` — main dashboard
- `GET /partials/queued-bills` — the queued bills HTMX partial (already used for the 30s auto-refresh and manual refresh)

No other template context changes are needed for these routes — `processing_accounts_configured` is the only addition.

When `False`:
- "Process" and "Process All" buttons render with `disabled` attribute and muted style.
- "Configure processing accounts" link is shown alongside them.

When `True`:
- Buttons are active as normal.

---

## `_process_one_bill` Changes

1. **Guard at top:** reads `settings.ap_account_guid` and `settings.checking_account_guid`. If either is `None`, returns immediately with no GnuCash calls:
   ```python
   {"ok": False, "error": "Processing accounts not configured — visit Settings > Processing Accounts"}
   ```

2. **Account name resolution for logging:** uses the existing `gnucash_db.get_account_by_guid(guid)` function (which already exists and SELECTs by GUID) to look up account names.

3. **INFO logging before try block:**
   ```
   Using A/P account: Accounts Payable (abc123...)
   Using checking account: Checking (def456...)
   ```

4. **Explicit account passing:**
   - `post_bill(..., ap_account_guid=settings.ap_account_guid)` — no longer relies on `ensure_ap_account_exists()`.
   - `pay_bill(..., checking_account_guid=settings.checking_account_guid)` — no longer uses `get_checking_accounts()[0]`.

**Note on A/P at payment time:** `pay_bill()` does not accept an `ap_account_guid` parameter — it reads `bill['post_acc']` from the database (set when `post_bill` ran). The A/P account at payment time is therefore always whatever was recorded during posting. The two settings are not symmetric: `ap_account_guid` controls posting only; the payment A/P reference is implicit from the bill record.

---

## Tests

### `TestProcessOneBill` additions

All four tests set the *other* GUID to a valid value so each test isolates exactly one missing configuration:

| Test | Setup | What it verifies |
|------|-------|-----------------|
| `test_uses_configured_ap_account_guid` | Both GUIDs set | `post_bill` called with `ap_account_guid` from settings |
| `test_uses_configured_checking_account_guid` | Both GUIDs set | `pay_bill` called with `checking_account_guid` from settings |
| `test_blocks_when_ap_account_not_configured` | `ap_account_guid=None`, checking set | Error returned, no GnuCash calls made |
| `test_blocks_when_checking_account_not_configured` | `checking_account_guid=None`, AP set | Error returned, no GnuCash calls made |

### New `TestProcessingAccountsSettings` class

| Test | What it verifies |
|------|-----------------|
| `test_get_page_returns_200` | Page renders without error |
| `test_save_ap_account_persists_to_settings` | Valid GUID → saved to settings, partial returned |
| `test_save_checking_account_persists_to_settings` | Valid GUID → saved to settings, partial returned |
| `test_save_invalid_ap_account_guid_returns_error` | Unknown GUID → settings unchanged, error in response |
| `test_save_invalid_checking_account_guid_returns_error` | Unknown GUID → settings unchanged, error in response |

### Dashboard gating tests

| Test | What it verifies |
|------|-----------------|
| `test_process_buttons_disabled_when_accounts_not_configured` | `disabled` attribute present on both buttons |
| `test_process_buttons_enabled_when_accounts_configured` | Buttons are active (no `disabled`) when both GUIDs set |

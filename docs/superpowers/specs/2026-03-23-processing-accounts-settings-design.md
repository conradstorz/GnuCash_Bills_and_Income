# Processing Accounts Settings — Design Spec

**Date:** 2026-03-23
**Status:** Approved

## Problem

The bill processing pipeline selects the A/P account via `ensure_ap_account_exists()` (first PAYABLE account found) and the checking account via `get_checking_accounts()[0]` (first BANK account alphabetically). Neither selection is logged or surfaced to the user. If the wrong account is used, the only way to notice is by inspecting GnuCash directly. Processing must be blocked until the user explicitly configures both accounts.

## Goal

Add a dedicated settings page where the user selects one A/P account and one checking account. These persist across sessions. Bill processing is blocked until both are configured, and both are logged at INFO level when a bill is processed.

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

This is the single gate used by the dashboard and processing logic.

---

## New Routes

| Method | Route | Purpose |
|--------|-------|---------|
| `GET` | `/settings/processing-accounts` | Renders the page — loads all PAYABLE and BANK accounts from GnuCash, passes current selections |
| `POST` | `/settings/processing-accounts/ap-account` | HTMX — receives `ap_account_guid`, saves to settings, returns updated A/P partial |
| `POST` | `/settings/processing-accounts/checking-account` | HTMX — receives `checking_account_guid`, saves to settings, returns updated checking partial |

Each POST returns only its own section partial so the two sections are independent.

---

## Template & Navigation

**New template:** `web/templates/settings_processing_accounts.html`

Two independent HTMX sections:

- **A/P Accounts** — radio buttons listing all PAYABLE accounts (`name`, `guid`). On change, POSTs to `/settings/processing-accounts/ap-account`. Shows inline confirmation after save.
- **Checking Accounts** — same pattern for all BANK accounts.

**Navigation additions:**
- `/settings` page gets a "Processing Accounts →" link at the top.
- Dashboard queued-bills card gets a "Configure processing accounts" link near the process buttons — always visible, but especially prominent when buttons are greyed out.

---

## Dashboard Button Gating

The `GET /` and `GET /partials/queued-bills` routes pass `processing_accounts_configured` (bool) to the template.

When `False`:
- "Process" and "Process All" buttons render with `disabled` attribute and muted style.
- "Configure processing accounts" link is shown alongside them.

When `True`:
- Buttons are active as normal.

---

## `_process_one_bill` Changes

1. **Guard at top:** reads `settings.ap_account_guid` and `settings.checking_account_guid`. If either is `None`, returns immediately:
   ```python
   {"ok": False, "error": "Processing accounts not configured — visit Settings > Processing Accounts"}
   ```
   No GnuCash calls are made.

2. **Account name resolution:** a small helper `get_account_name_by_guid(guid) -> str` looks up the account name from GnuCash by GUID (used for logging only).

3. **INFO logging before try block:**
   ```
   Using A/P account: Accounts Payable (abc123...)
   Using checking account: Checking (def456...)
   ```

4. **Explicit account passing:**
   - `post_bill(bill_guid=..., post_date=..., due_date=..., ap_account_guid=settings.ap_account_guid)` — no longer relies on `ensure_ap_account_exists()`.
   - `pay_bill(bill_guid=..., checking_account_guid=settings.checking_account_guid, ...)` — no longer uses `get_checking_accounts()[0]`.

---

## Tests

### `TestProcessOneBill` additions

| Test | What it verifies |
|------|-----------------|
| `test_uses_configured_ap_account_guid` | `post_bill` called with `ap_account_guid` from settings |
| `test_uses_configured_checking_account_guid` | `pay_bill` called with `checking_account_guid` from settings |
| `test_blocks_when_ap_account_not_configured` | `ap_account_guid=None` → error returned, no GnuCash calls made |
| `test_blocks_when_checking_account_not_configured` | `checking_account_guid=None` → same |

### New `TestProcessingAccountsSettings` class

| Test | What it verifies |
|------|-----------------|
| `test_get_page_returns_200` | Page renders without error |
| `test_save_ap_account_persists_to_settings` | POST saves GUID to settings, returns HTMX partial |
| `test_save_checking_account_persists_to_settings` | POST saves GUID to settings, returns HTMX partial |

### Dashboard gating tests

| Test | What it verifies |
|------|-----------------|
| `test_process_buttons_disabled_when_accounts_not_configured` | `disabled` attribute present on both buttons |
| `test_process_buttons_enabled_when_accounts_configured` | Buttons active when both GUIDs set |

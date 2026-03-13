# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Python tool suite for automating bill creation, posting, and payment in GnuCash (SQLite format). Implements a verified 3-step workflow against the GnuCash database directly.

## Commands

### Running the Application

```bash
# CLI bill processor (reads from bills_to_process.txt)
python main.py
python main.py --status          # Show database status
python main.py --list-vendors    # List known vendors
python main.py --dry-run         # Parse without creating bills

# GUI applications
python bill_entry_gui.py         # Bill entry Tkinter GUI
python vendor_manager_gui.py     # Vendor management Tkinter GUI

# Vendor sync (JSON <-> GnuCash)
python vendor_sync.py

# Web dashboard (use uv run — uvicorn is managed via uv)
uv run uvicorn bill_processor.web.app:app --reload --port 7432
# Or double-click GnuCash Bills.bat (desktop launcher — opens browser automatically)
# Access at http://localhost:7432

# First-time setup (after git clone)
uv run python install.py
# Searches Documents for .gnucash files, updates config.py, generates launcher
```

### Testing

```bash
# Run all tests
python tests/run_tests.py

# Run specific test files
pytest tests/test_bill_workflow.py -v
pytest tests/test_vendor_manager.py -v
pytest tests/test_web_app.py -v

# With coverage
pytest --cov=bill_processor tests/
```

### Debugging with Columbo

`columbo.py` is a self-contained database snapshot/diff tool (no imports from the rest of the project):

```bash
# Capture "before" state
python columbo.py path/to/book.gnucash

# After making changes, capture "after" and generate diff report
python columbo.py path/to/book.gnucash
# Outputs: snapshot_before.json, snapshot_after.json, columbo_report.txt
```

## Architecture

### Three-Tier Structure

**Data Layer** (`gnucash_db.py`) — Direct SQLite access to the GnuCash database. Implements the 3-step bill workflow:
1. `create_bill()` — Creates unposted invoice record + entry
2. `post_bill()` — Creates lot and transaction, posts to Accounts Payable
3. `pay_bill()` — Creates payment transaction from checking account

**Business Logic** (`vendor_manager.py`, `utils.py`, `address_lookup.py`, `vendor_sync.py`) — Vendor lookup with fuzzy matching (threshold: 70%), alias management, address resolution via Google Places API (primary) or OpenStreetMap (fallback), and JSON↔GnuCash sync.

**Presentation Layer** — Three independent interfaces all calling the same underlying logic:
- CLI (`main.py`)
- Tkinter GUIs (`bill_entry_gui.py`, `vendor_manager_gui.py`)
- FastAPI + HTMX web app (`web/app.py`)

### Key Supporting Modules

- **Configuration Architecture — Hybrid System (config.py + settings_manager.py)**
  
  **`config.py`** — **SYSTEM CONSTANTS** (immutable, developer-modified only):
  - GnuCash Schema Constants: Account types (ROOT, EXPENSE, PAYABLE, BANK, LIABILITY, ASSET, INCOME), placeholder flags, active/inactive flags
  - ID Format Patterns: VENDOR_ID_FORMAT, BILL_ID_FORMAT
  - System-Level: Earth radius (Haversine formula), date format patterns, business name suffixes, OSM endpoints
  - Feature Domains: 5 organized sections (Application Setup, Bill & Vendor Management, Address Lookup Services, User Interface, System Constants)
  - `PROJECT_ROOT` auto-detected via `Path(__file__).parent.resolve()` for portability
  
  **`settings_manager.py`** — **USER SETTINGS** (runtime-modifiable via GUI/web/API):
  - Persists to `data/user_settings.json` (gitignored, contains PII)
  - SettingsManager class with property accessors and convenience methods
  - Automatically loads from file or falls back to config.py defaults
  - Auto-saves on any change (`set()`, `update()`, property setters)
  - User-Configurable Settings:
    - Database & Paths: `gnucash_db_path` (user can switch databases)
    - Locality: `locality_city`, `locality_state`, `home_latitude`, `home_longitude`, `search_radius_miles`
    - GnuCash Accounts: `accounts_payable_path`, `default_expense_parent`, `cash_on_hand_account_name`
    - Defaults: `default_memo`, `default_currency`
    - Fuzzy Matching: `fuzzy_match_threshold`, `fuzzy_ambiguous_threshold`, autocomplete thresholds
    - Address Lookup: API timeouts, rate limits, search result limits
    - UI Dimensions: All window sizes, widget widths, treeview columns, autocomplete appearance
    - Display: `terminal_width`, `log_level`, server shutdown delay
  
  **Usage:**
  ```python
  from settings_manager import settings  # Runtime-configurable
  import config                          # System constants
  
  settings.gnucash_db_path = Path('/new/db.gnucash')
  settings.update_locality('Cincinnati', 'OH', 'US', 39.1031, -84.5120)
  settings.fuzzy_match_threshold = 85
  
  account_type = config.ACCOUNT_TYPE_EXPENSE  # Immutable constant
  ```
  
  **Migration Path:** Existing code using `from config import SETTING` still works during transition period via `__getattr__` fallback.

- **`schema_discovery.py`** — Handles GnuCash version differences by detecting column names at runtime; caches results in `gnucash_schema.json`.
- **`logging_setup.py`** — loguru-based logging; console=INFO, file=DEBUG at `logs/bill_processor.log`.

### Cash-on-Hand Entry (web dashboard, right panel)

The dashboard uses a split-screen layout: bills panel (left) and cash entry panel (right).

**Cash entry DB functions** (`gnucash_db.py`):
- `create_cash_entry()` — creates the multi-split batch transaction in GnuCash (SAMUSE + N income/asset splits)
- `create_cash_deposit()` — creates an independent bank deposit transaction (SAMUSE → bank account; amount unrelated to batch total)
- `get_samuse_account_guid()` — looks up and caches the SAMUSE Cash-on-hand account GUID
- `get_cash_accounts()` — returns selectable income/asset accounts

**Sign convention:** positive amount = cash into SAMUSE; negative = cash out. The SAMUSE split is auto-calculated as the balancing entry.

**Dashboard DB health check:** `GET /` calls `check_db_health()` before rendering. If the database is missing or locked, renders `db_unavailable.html` with full details and recovery options (browse for file, refresh, shut down).

**New web routes** (`web/app.py`):

| Route | Purpose |
|---|---|
| `GET /cash/add-row` | HTMX — append a new cash entry row |
| `GET /clients/datalist` | Returns `<datalist>` HTML for client autocomplete |
| `GET /clients/search` | JSON client name search |
| `POST /cash/submit` | Validates and posts cash batch to GnuCash |
| `GET /accounts/asset` | JSON list of all asset account names |
| `GET /accounts/all` | JSON list of all account names (any type) |
| `GET /accounts/validate` | HTMX — validates account name, returns HTML feedback |
| `GET /accounts/datalist` | Returns `<datalist>` HTML for account autocomplete (all account types) |
| `GET /db/browse` | Opens native Windows file picker (tkinter subprocess), returns `{"path": "..."}` |
| `POST /db/set-path` | Validates path, writes new `GNUCASH_DB_PATH` to `config.py`, reloads config, redirects to `/` |

**Cash-related data files:**
- `data/clients.json` — flat list of 15–45 client names for autocomplete; edit manually
- `data/cash_accounts.json` — 5–10 income/asset accounts for the account dropdown; each entry needs `name` and `guid`

### Settings Page (`/settings`)

Web-based configuration interface for user-modifiable settings:
- **Cash Entry Accounts** — checkbox grid to enable/disable accounts in cash entry dropdown
- **Cash-on-Hand Account** — text input with live validation (HTMX autocomplete, validates account exists in GnuCash)
- **Locality Settings** — city, state, coordinates, search radius
- **Fuzzy Matching** — match and ambiguous thresholds
- **Reset** — restore all settings to config.py defaults

**Live validation**: Cash-on-hand account field validates against GnuCash chart of accounts as you type (300ms debounce). Autocomplete shows all non-placeholder accounts from the database and accepts any valid account name.

### Vendor Data Model

Vendors are stored in `data/vendor_database.json` as:
```json
{
  "vendors": { "vendor_key": { "display_name": "", "gnucash_guid": "", "addr_line1": "", ... } },
  "aliases": { "alias_name": "vendor_key" }
}
```
GnuCash GUIDs are the authoritative link between JSON and the database.

### Bill Queue Format

`data/bills_to_process.txt` — one bill per line:
```
Vendor Name, 123.45, Optional Memo, 2026-01-15
```

### Test Fixtures (`tests/conftest.py`)

Tests operate on a temporary copy of the real database. Key fixtures: `test_db_path`, `db_connection`, `test_vendor_guid`, `test_accounts`, `bill_data`.

## Environment Setup

Google Places API key goes in `.env` as `GOOGLE_PLACES_API_KEY`. Without it, OSM Nominatim is used automatically. See `setup_google_api.py` or `GOOGLE_API_SETUP.md`.

## Package Entry Points

```
bill-processor        → main:main
bill-entry            → bill_entry_gui:main
vendor-manager-gui    → vendor_manager_gui:main
vendor-sync           → vendor_sync:main
```

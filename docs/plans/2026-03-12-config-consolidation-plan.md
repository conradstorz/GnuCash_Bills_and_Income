# Plan: Centralize Configuration Constants

**Date:** March 12, 2026  
**Status:** Planning

## TL;DR

Consolidate 40+ scattered configuration constants from 8 modules into config.py, organized into logical sections with clear documentation. This improves maintainability, discoverability, and allows users to customize behavior without editing code across multiple files.

**Approach:** Group constants by category (API, Business Rules, UI, GnuCash Schema), add comprehensive inline documentation, update all module references, verify with tests.

---

## Phase 1: Add Constants to config.py (Grouped by Category)

### 1.1 ADDRESS LOOKUP API SETTINGS (expand existing section)
Add to existing "ADDRESS LOOKUP API SETTINGS" section:
- `API_REQUEST_TIMEOUT_SECONDS = 10` — HTTP timeout for both Google and OSM APIs (prevents hanging on network issues)
- `OSM_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"` — OSM search endpoint (allows using alternative instances)
- `OSM_RATE_LIMIT_SECONDS = 1.1` — Delay between OSM requests per their ToS (1req/sec max, we use 1.1s buffer)
- `OSM_SEARCH_LIMIT = 50` — Number of results requested from OSM API (more = better coverage, slower response)
- `ADDRESS_SEARCH_MAX_RESULTS = 20` — Limit final results shown to user (prevents overwhelming UI)
- `ADDRESS_LOOKUP_MIN_WORD_MATCHES = 2` — Minimum word overlap for result filtering (reduces false matches)
- `BUSINESS_NAME_SUFFIXES = [' inc', ' llc', ' ltd', ' corp', ' corporation', ' company', ' co', ' incorporated', ' store', ' supercenter', ' center', ' market']` — Suffixes stripped during vendor name fuzzy matching (improves "Walmart" vs "Walmart Inc" matching)

**Rationale:** These control external API behavior and are currently duplicated across address_lookup.py (6 hardcoded timeout=10, 3 time.sleep(1.1), 2 results[:20]). Centralizing allows tuning for network conditions, rate limits, or result quality.

### 1.2 FUZZY MATCHING SETTINGS (expand existing section)
Add to existing "FUZZY MATCHING SETTINGS" section:
- `AUTOCOMPLETE_MATCH_THRESHOLD = 50` — Lower threshold for GUI autocomplete (more permissive than main matching)
- `AUTOCOMPLETE_PREFIX_MATCH_SCORE = 90` — Boost score when search text is name prefix (e.g., "Wal" matches "Walmart")
- `AUTOCOMPLETE_CONTAINS_MATCH_SCORE = 70` — Score when search text appears anywhere in name
- `AUTOCOMPLETE_MAX_RESULTS = 10` — Limit autocomplete dropdown items (prevents UI clutter)
- `WEB_VENDOR_SEARCH_MIN_SCORE = 40` — Minimum score for web vendor dropdown (even more permissive for web UI)
- `WEB_VENDOR_DROPDOWN_MAX_RESULTS = 6` — Limit web vendor dropdown (smaller than GUI autocomplete for cleaner web UX)
- `CLIENT_SEARCH_MAX_RESULTS = 10` — Limit client name suggestions in cash entry

**Rationale:** Currently scattered in bill_entry_gui.py (lines 732, 752, 760), web/app.py (line 36, 279), web/cash_io.py (line 20). Different thresholds exist for different contexts (main matching=70, autocomplete=50, web=40), but magic numbers are undocumented.

### 1.3 GNUCASH SETTINGS (expand existing section)
Add to existing "GNUCASH SETTINGS" section:
- `DEFAULT_EXPENSE_PARENT = "Expenses root"` — Expected name of top-level expense account in chart of accounts
- `PAYABLE_ACCOUNT_NAME_PATTERN = "payable"` — Fallback search term when PAYABLE account type not found
- `DEFAULT_VENDOR_ACTIVE = 1` — New vendors created as active (1) or inactive (0)
- `DEFAULT_VENDOR_TAX_OVERRIDE = 0` — Default tax override for new vendors
- `LOCK_HOSTNAME_PREFIX = "BillProcessor"` — Prefix for database lock hostname (distinguishes from GnuCash locks)

**Rationale:** Business rules currently hardcoded in gnucash_db.py. Moving to config makes them explicit and user-configurable (e.g., user might want "Expenses" instead of "Expenses root").

### 1.4 GNUCASH SCHEMA CONSTANTS (new section)
Add new section after GNUCASH SETTINGS:
```python
# =============================================================================
# GNUCASH SCHEMA CONSTANTS
# =============================================================================
# These match GnuCash's internal database schema and should rarely be changed

# Account types
ACCOUNT_TYPE_ROOT = "ROOT"
ACCOUNT_TYPE_EXPENSE = "EXPENSE"
ACCOUNT_TYPE_PAYABLE = "PAYABLE"
ACCOUNT_TYPE_BANK = "BANK"
ACCOUNT_TYPE_LIABILITY = "LIABILITY"
ACCOUNT_TYPE_ASSET = "ASSET"
ACCOUNT_TYPE_INCOME = "INCOME"

# Placeholder flags (SQLite boolean: 0=false, 1=true)
PLACEHOLDER_FALSE = 0
PLACEHOLDER_TRUE = 1

# Active flags (SQLite boolean: 0=false, 1=true)
ACTIVE_FALSE = 0
ACTIVE_TRUE = 1
```

**Rationale:** Currently raw strings ('EXPENSE', 'PAYABLE') duplicated 30+ times across gnucash_db.py queries. Named constants prevent typos, enable IDE autocomplete, make schema version changes easier to manage.

### 1.5 DATE PARSING (new section)
Add new section:
```python
# =============================================================================
# DATE PARSING
# =============================================================================

# Alternative date formats tried when primary format fails
ALTERNATIVE_DATE_FORMATS = ["%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"]
```

**Rationale:** Currently hardcoded in utils.py line 78. User might need different formats for international dates.

### 1.6 DISTANCE CALCULATION (new section)
Add new section:
```python
# =============================================================================
# DISTANCE CALCULATION
# =============================================================================

# Earth radius in miles for Haversine distance formula
EARTH_RADIUS_MILES = 3959
```

**Rationale:** Implicit in utils.py Haversine formula. Explicit constant documents what the magic distance calculation does and allows switching to kilometers if desired.

### 1.7 UI SETTINGS (new section)
Add new section:
```python
# =============================================================================
# UI SETTINGS (Tkinter GUIs)
# =============================================================================

# Main window sizes
BILL_ENTRY_WINDOW_WIDTH = 800
BILL_ENTRY_WINDOW_HEIGHT = 700
VENDOR_MANAGER_WINDOW_WIDTH = 800
VENDOR_MANAGER_WINDOW_HEIGHT = 600

# Dialog window size
DIALOG_WINDOW_WIDTH = 600
DIALOG_WINDOW_HEIGHT = 400

# Widget dimensions
COMBOBOX_WIDTH = 70
ENTRY_FIELD_WIDTH_VENDOR = 50
ENTRY_FIELD_WIDTH_AMOUNT = 20
ENTRY_FIELD_WIDTH_MEMO = 50
ENTRY_FIELD_WIDTH_DATE = 15

# Treeview column widths (pixels)
TREEVIEW_COLUMN_WIDTH_VENDOR = 200
TREEVIEW_COLUMN_WIDTH_AMOUNT = 80
TREEVIEW_COLUMN_WIDTH_MEMO = 250
TREEVIEW_COLUMN_WIDTH_DATE = 80

# Autocomplete dropdown appearance
AUTOCOMPLETE_ROW_HEIGHT = 25
AUTOCOMPLETE_MAX_HEIGHT = 250
```

**Rationale:** Currently hardcoded in bill_entry_gui.py and vendor_manager_gui.py. Centralizing makes UI consistency easier and allows users to adjust for different screen resolutions or accessibility needs.

### 1.8 WEB SERVER (new section)
Add new section:
```python
# =============================================================================
# WEB SERVER
# =============================================================================

# Delay before shutdown (allows graceful cleanup)
SERVER_SHUTDOWN_DELAY_SECONDS = 1.0
```

**Rationale:** Currently magic number in web/app.py line 629.

---

## Phase 2: Update Module Imports

### 2.1 address_lookup.py
**Change:** Add `from bill_processor import config` at top, update references:
- Replace `timeout=10` → `timeout=config.API_REQUEST_TIMEOUT_SECONDS` (6 locations)
- Replace `time.sleep(1.1)` → `time.sleep(config.OSM_RATE_LIMIT_SECONDS)` (3 locations)
- Replace `results[:20]` → `results[:config.ADDRESS_SEARCH_MAX_RESULTS]` (2 locations)
- Replace hardcoded `suffixes` list → use `config.BUSINESS_NAME_SUFFIXES`
- Replace `min_word_matches=2` → `min_word_matches=config.ADDRESS_LOOKUP_MIN_WORD_MATCHES`
- Replace OSM URL string → `config.OSM_NOMINATIM_URL`
- Replace `'limit': 50` → `'limit': config.OSM_SEARCH_LIMIT`

**Dependencies:** address_lookup.py already imports config for CENTER_LAT, CENTER_LON, etc., so no new import needed.

### 2.2 gnucash_db.py
**Change:** Update references throughout:
- Replace `'EXPENSE'`, `'PAYABLE'`, etc. → `config.ACCOUNT_TYPE_EXPENSE`, `config.ACCOUNT_TYPE_PAYABLE` in all queries
- Replace `'active': 1` → `'active': config.DEFAULT_VENDOR_ACTIVE`
- Replace `'tax_override': 0` → `'tax_override': config.DEFAULT_VENDOR_TAX_OVERRIDE`
- Replace `"Expenses root"` → `config.DEFAULT_EXPENSE_PARENT`
- Replace `f"BillProcessor@{...}"` → `f"{config.LOCK_HOSTNAME_PREFIX}@{...}"`
- Replace `placeholder = 0` → `placeholder = config.PLACEHOLDER_FALSE` in queries
- Replace `'USD'` literal → `config.DEFAULT_CURRENCY` in queries

**Dependencies:** gnucash_db.py already imports config for GNUCASH_DB_PATH, DEFAULT_CURRENCY, SAMUSE_ACCOUNT_NAME.

### 2.3 utils.py
**Change:**
- Replace date formats list → `config.ALTERNATIVE_DATE_FORMATS`
- Replace business suffixes list → `config.BUSINESS_NAME_SUFFIXES`
- Add `EARTH_RADIUS_MILES = config.EARTH_RADIUS_MILES` constant before Haversine function

**Dependencies:** utils.py does NOT currently import config — add `from bill_processor import config` at top.

### 2.4 bill_entry_gui.py
**Change:**
- Replace all window/dialog geometry strings → use config constants
- Replace widget dimension numbers → use config constants
- Replace `threshold=50` → `threshold=config.AUTOCOMPLETE_MATCH_THRESHOLD`
- Replace autocomplete scoring numbers → use config constants
- Replace `[:10]` limit → `[:config.AUTOCOMPLETE_MAX_RESULTS]`

**Dependencies:** bill_entry_gui.py does NOT import config — add import.

### 2.5 vendor_manager_gui.py
**Change:** Similar to bill_entry_gui.py for window sizes and widget dimensions.

**Dependencies:** Add config import.

### 2.6 web/app.py
**Change:**
- Replace module constant `VENDOR_SEARCH_MIN_SCORE` → use `config.WEB_VENDOR_SEARCH_MIN_SCORE`
- Replace `results[:6]` → `results[:config.WEB_VENDOR_DROPDOWN_MAX_RESULTS]`
- Replace `time.sleep(1.0)` → `time.sleep(config.SERVER_SHUTDOWN_DELAY_SECONDS)`

**Dependencies:** web/app.py already imports config for paths.

### 2.7 web/cash_io.py
**Change:**
- Replace `limit: int = 10` → `limit: int = config.CLIENT_SEARCH_MAX_RESULTS` in function signature

**Dependencies:** Add config import.

---

## Phase 3: Backward Compatibility

### 3.1 Deprecated Constants
For external code that might reference old module-level constants, consider adding deprecation warnings:
- web/app.py: Keep `VENDOR_SEARCH_MIN_SCORE` as alias with deprecation warning (remove in future version)

### 3.2 Alias Strategy
Config.py already uses aliases (e.g., `DEFAULT_INPUT_FILE` for `BILLS_INPUT_PATH`). No new aliases needed for this refactor.

---

## Phase 4: Documentation Updates

### 4.1 Inline Documentation
Each new constant in config.py includes comment explaining:
- **What it controls**
- **Why that value**
- **Impact of changing it**

### 4.2 CLAUDE.md Updates
Add section documenting the new config sections and noting that all configuration is now centralized.

---

## Verification

### Step 1: Run test suite
```bash
pytest tests/ -v
```
All existing tests should pass without modification (config constants used in tests should continue working).

### Step 2: Manual testing
1. Launch bill_entry_gui.py — verify window size and autocomplete behavior
2. Launch web dashboard — verify vendor search dropdown
3. Run address lookup — verify OSM rate limiting (add debug logs to confirm sleep time)
4. Create test vendor — verify active=1, tax_override=0 defaults
5. Parse bills from bills_to_process.txt — verify date parsing works

### Step 3: Verify no hardcoded remnants
```bash
# Search for likely magic numbers that should be constants
grep -r "timeout=10" --include="*.py" .
grep -r "time.sleep(1.1)" --include="*.py" .
grep -r "'EXPENSE'" --include="*.py" .
grep -r "placeholder = 0" --include="*.py" .
```
Should return zero results (except in config.py definitions).

---

## Implementation Order

1. **Add all constants to config.py** (Phase 1) — Single focused PR
2. **Update imports one module at a time** (Phase 2) — Separate commit per module for easy review/rollback
   - Start with utils.py (smallest, simple changes)
   - Then address_lookup.py (medium, most duplicates)
   - Then gnucash_db.py (largest, most critical)
   - Then GUI modules (bill_entry_gui, vendor_manager_gui)
   - Finally web modules (app.py, cash_io.py)
3. **Run tests after each module** — Catch issues early
4. **Update docs** (Phase 4) — After all code working

---

## Decisions

**Should we consolidate completely or be selective?**
- **Recommendation:** Consolidate all user-facing settings and duplicated constants. Keep module-internal helpers (like private regex patterns used only once) in modules.

**Should GnuCash schema constants like 'EXPENSE' be configurable?**
- **Recommendation:** Yes, move to config but in separate "SCHEMA" section with warning comment. Allows handling future GnuCash versions that might change types, but documents these are rarely changed.

**Should UI constants be configurable or hardcoded?**
- **Recommendation:** Make configurable. Small effort, enables accessibility adjustments (larger fonts = need wider fields) and multi-monitor setups.

**Should we use environment variables for any of these?**
- **Recommendation:** Only for sensitive data (API keys already use .env). Most constants don't need env overrides — config.py edits are sufficient.

---

## Further Considerations

1. **Config validation:** Should we add a `validate_config()` function that checks:
   - Paths exist and are readable
   - Numeric values are positive/in valid ranges
   - Threshold values are 0-100
   
   **Recommendation:** Add as separate follow-up task after consolidation complete.

2. **Config file templates:** Should we provide config.py.example with placeholder paths?
   
   **Recommendation:** Current approach (edit config.py directly) is fine for single-user project. For multi-user, consider this later.

3. **Hot reload:** Should config changes take effect without restart?
   
   **Recommendation:** No — too complex for benefit. Simple restart is acceptable.

---

## Constants Inventory

### Already in config.py
- `FUZZY_MATCH_THRESHOLD = 70`
- `FUZZY_AMBIGUOUS_THRESHOLD = 85`
- `TERMINAL_WIDTH = 80`
- `OSM_USER_AGENT = "GnuCashBillProcessor/1.0 (personal use)"`
- `DEFAULT_MEMO = "no memo"`
- `DEFAULT_CURRENCY = "USD"`
- `SAMUSE_ACCOUNT_NAME = "SAMUSE Cash-on-hand"`

### To be added (40+ new constants)

**ADDRESS LOOKUP (7 constants)**
- `API_REQUEST_TIMEOUT_SECONDS` — duplicated 6× in address_lookup.py
- `OSM_RATE_LIMIT_SECONDS` — duplicated 3×
- `OSM_NOMINATIM_URL` — hardcoded URL
- `OSM_SEARCH_LIMIT` — hardcoded 50
- `ADDRESS_SEARCH_MAX_RESULTS` — duplicated 2×, hardcoded 20
- `ADDRESS_LOOKUP_MIN_WORD_MATCHES` — hardcoded 2
- `BUSINESS_NAME_SUFFIXES` — duplicated list in address_lookup.py and utils.py

**FUZZY MATCHING (7 constants)**
- `AUTOCOMPLETE_MATCH_THRESHOLD` — bill_entry_gui.py line 732
- `AUTOCOMPLETE_PREFIX_MATCH_SCORE` — bill_entry_gui.py line 752
- `AUTOCOMPLETE_CONTAINS_MATCH_SCORE` — bill_entry_gui.py line 752
- `AUTOCOMPLETE_MAX_RESULTS` — bill_entry_gui.py line 760
- `WEB_VENDOR_SEARCH_MIN_SCORE` — web/app.py line 36
- `WEB_VENDOR_DROPDOWN_MAX_RESULTS` — web/app.py line 279
- `CLIENT_SEARCH_MAX_RESULTS` — web/cash_io.py line 20

**GNUCASH BUSINESS RULES (5 constants)**
- `DEFAULT_EXPENSE_PARENT` — gnucash_db.py lines 1052, 1247
- `PAYABLE_ACCOUNT_NAME_PATTERN` — gnucash_db.py line 1163
- `DEFAULT_VENDOR_ACTIVE` — gnucash_db.py lines 726, 1321
- `DEFAULT_VENDOR_TAX_OVERRIDE` — gnucash_db.py lines 726, 1321
- `LOCK_HOSTNAME_PREFIX` — gnucash_db.py line 418

**GNUCASH SCHEMA (10 constants)**
- 7 account types (ROOT, EXPENSE, PAYABLE, BANK, LIABILITY, ASSET, INCOME)
- PLACEHOLDER_FALSE, PLACEHOLDER_TRUE
- ACTIVE_FALSE, ACTIVE_TRUE

**DATE/CALCULATION (2 constants)**
- `ALTERNATIVE_DATE_FORMATS` — utils.py line 78
- `EARTH_RADIUS_MILES` — utils.py (implicit in Haversine)

**UI SETTINGS (10+ constants)**
- Window sizes (4)
- Widget dimensions (5)
- Treeview columns (4)
- Autocomplete appearance (2)

**WEB SERVER (1 constant)**
- `SERVER_SHUTDOWN_DELAY_SECONDS` — web/app.py line 629

---

## Files to Modify

1. `config.py` — Add 8 new/expanded sections with 40+ constants
2. `address_lookup.py` — 15+ reference updates
3. `gnucash_db.py` — 30+ reference updates (account types, business rules)
4. `utils.py` — 3 updates + add config import
5. `bill_entry_gui.py` — 10+ updates + add config import
6. `vendor_manager_gui.py` — 5+ updates + add config import
7. `web/app.py` — 3 updates
8. `web/cash_io.py` — 1 update + add config import
9. `CLAUDE.md` — Document config consolidation

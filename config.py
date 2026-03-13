"""
Bill Processor Configuration - System Constants

This file contains IMMUTABLE SYSTEM CONSTANTS that define application behavior.
For RUNTIME USER-CONFIGURABLE SETTINGS, see settings_manager.py and user_settings.json.

⚠️ CONFIGURATION ARCHITECTURE:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
config.py (this file)          → System constants (account types, formats, etc.)
                                 Never change at runtime
                                 Modified by developers only

settings_manager.py            → SettingsManager class with load/save/update methods
user_settings.json            → User preferences (paths, thresholds, UI dimensions)
                                 Change at runtime via GUI/web interface
                                 User-editable JSON file
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

USAGE:
    from settings_manager import settings  # For runtime-configurable settings
    import config                          # For system constants

EXAMPLES:
    settings.gnucash_db_path              # User's database path (changeable)
    settings.fuzzy_match_threshold        # User's matching threshold (changeable)
    config.ACCOUNT_TYPE_EXPENSE           # GnuCash schema constant (immutable)
    config.VENDOR_ID_FORMAT               # ID format pattern (immutable)

⚠️ SECURITY NOTE - CONTAINS PERSONALLY IDENTIFIABLE INFORMATION (PII):
This file contains location-specific data that should be reviewed before sharing:
- GPS coordinates (LOCALITY_CENTER_LAT/LON) pinpoint a specific geographic location
- DEFAULT_LOCALITY reveals the city/state of operation

For cross-platform compatibility and privacy:
- User-specific values have been moved to user_settings.json
- System defaults remain here as fallbacks
- Use environment variables or .env file for sensitive API keys
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# 1. APPLICATION SETUP
# =============================================================================
# Core application configuration: paths, logging, environment

# Project root directory (auto-detected from config.py location)
PROJECT_ROOT = Path(__file__).parent.resolve()

# Data file paths
VENDOR_DB_PATH = PROJECT_ROOT / "data" / "vendor_database.json"
VENDOR_DATABASE_PATH = VENDOR_DB_PATH  # Alias for compatibility
CLIENTS_PATH = PROJECT_ROOT / "data" / "clients.json"
CASH_ACCOUNTS_PATH = PROJECT_ROOT / "data" / "cash_accounts.json"
MEMO_HISTORY_PATH = PROJECT_ROOT / "data" / "memo_history.json"
BILLS_INPUT_PATH = PROJECT_ROOT / "data" / "bills_to_process.txt"
DEFAULT_INPUT_FILE = BILLS_INPUT_PATH  # Alias for compatibility

# GnuCash database file (SQLite format) - customize for your environment
# Note: Path.home() doesn't work here because Documents folder is on D: drive
GNUCASH_DB_PATH = Path(r"D:\Users\Conrad\Documents\GnuCash\gnuCash414\CFSIV_Sqlite3_database.gnucash")

# Logging configuration
LOG_FILE_PATH = PROJECT_ROOT / "logs" / "bill_processor.log"
LOG_FILE = LOG_FILE_PATH  # Alias for compatibility
LOG_LEVEL = "INFO"  # Options: DEBUG, INFO, WARNING, ERROR


# =============================================================================
# 2. BILL & VENDOR MANAGEMENT
# =============================================================================
# Settings for bill processing, vendor management, and fuzzy matching

# --- GnuCash Account Settings ---
ACCOUNTS_PAYABLE_PATH = "Liabilities:Accounts Payable"
DEFAULT_EXPENSE_PARENT = "Expenses root"  # Top-level expense account
CASH_ON_HAND_ACCOUNT_NAME = "SAM Cash-on-hand"
PAYABLE_ACCOUNT_NAME_PATTERN = "payable"  # Fallback search pattern

# --- Bill and Vendor ID Formats ---
VENDOR_ID_PREFIX = ""
VENDOR_ID_FORMAT = "{prefix}{num:06d}"  # e.g., 000001, 000002
BILL_ID_PREFIX = "B-"
BILL_ID_FORMAT = "{prefix}{num:04d}"  # e.g., B-0001, B-0002

# --- Default Values ---
DEFAULT_MEMO = "no memo"
DEFAULT_CURRENCY = "USD"
DEFAULT_VENDOR_ACTIVE = 1  # 1 = active, 0 = inactive
DEFAULT_VENDOR_TAX_OVERRIDE = 0  # 0 = use default tax settings

# --- Database Operations ---
LOCK_HOSTNAME_PREFIX = "BillProcessor"  # Distinguishes from GnuCash locks

# --- Fuzzy Matching & Search ---
# Core matching thresholds (0-100 scale)
FUZZY_MATCH_THRESHOLD = 70  # Minimum score for valid match
FUZZY_AMBIGUOUS_THRESHOLD = 85  # Flag matches above this as ambiguous

# GUI autocomplete (more permissive for better UX)
AUTOCOMPLETE_MATCH_THRESHOLD = 50
AUTOCOMPLETE_PREFIX_MATCH_SCORE = 90  # Boost for prefix matches
AUTOCOMPLETE_CONTAINS_MATCH_SCORE = 70  # Score for substring matches
AUTOCOMPLETE_MAX_RESULTS = 10

# Web vendor search (most permissive)
WEB_VENDOR_SEARCH_MIN_SCORE = 40
WEB_VENDOR_DROPDOWN_MAX_RESULTS = 6

# Client search
CLIENT_SEARCH_MAX_RESULTS = 10

# Business name suffixes stripped during matching
# Improves matching: "Walmart" matches "Walmart Inc", etc.
BUSINESS_NAME_SUFFIXES = [
    ' inc', ' llc', ' ltd', ' corp', ' corporation', ' company', ' co', 
    ' incorporated', ' store', ' supercenter', ' center', ' market'
]


# =============================================================================
# 3. ADDRESS LOOKUP SERVICES
# =============================================================================
# Geographic search, external APIs, and distance calculation

# --- Locality Settings ---
# Your geographic location - used to narrow address searches
LOCALITY_CITY = "Louisville"
LOCALITY_STATE = "KY"
LOCALITY_COUNTRY = "US"
DEFAULT_LOCALITY = f"{LOCALITY_CITY}, {LOCALITY_STATE}"

# Coordinates for distance calculations and "pick closest" logic
HOME_LATITUDE = 38.2527
HOME_LONGITUDE = -85.7585
LOCALITY_CENTER_LAT = HOME_LATITUDE  # Center point for search radius
LOCALITY_CENTER_LON = HOME_LONGITUDE

# Search radius (Google Places API max: 50,000 meters ≈ 31 miles)
SEARCH_RADIUS_MILES = 30

# --- Google Places API ---
# Most accurate results, requires API key
# Setup: run `python setup_google_api.py` or see GOOGLE_API_SETUP.md
# API key stored in .env file for security
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# --- OpenStreetMap Nominatim ---
# Free fallback when Google API key not configured
USE_OPENSTREETMAP = True
OSM_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSM_USER_AGENT = "GnuCashBillProcessor/1.0 (personal use)"
OSM_RATE_LIMIT_SECONDS = 1.1  # ToS requires max 1 req/sec; 1.1s buffer
OSM_SEARCH_LIMIT = 50  # More results = better coverage but slower

# --- Address Search Behavior ---
API_REQUEST_TIMEOUT_SECONDS = 10  # Prevents hanging on network issues
ADDRESS_SEARCH_MAX_RESULTS = 20  # Limit results shown to user
ADDRESS_LOOKUP_MIN_WORD_MATCHES = 2  # Min word overlap for filtering

# --- Distance Calculation ---
EARTH_RADIUS_MILES = 3959  # For Haversine formula; use 6371 for kilometers


# =============================================================================
# 4. USER INTERFACE
# =============================================================================
# GUI dimensions, web server, and display settings

# --- Tkinter Window Sizes (pixels) ---
BILL_ENTRY_WINDOW_WIDTH = 800
BILL_ENTRY_WINDOW_HEIGHT = 700
VENDOR_MANAGER_WINDOW_WIDTH = 800
VENDOR_MANAGER_WINDOW_HEIGHT = 600
DIALOG_WINDOW_WIDTH = 600  # Sync dialogs, account selection, etc.
DIALOG_WINDOW_HEIGHT = 400

# --- Widget Dimensions ---
COMBOBOX_WIDTH = 70  # Characters
ENTRY_FIELD_WIDTH_VENDOR = 50
ENTRY_FIELD_WIDTH_AMOUNT = 20
ENTRY_FIELD_WIDTH_MEMO = 50
ENTRY_FIELD_WIDTH_DATE = 15

# --- Treeview Column Widths (pixels) ---
TREEVIEW_COLUMN_WIDTH_VENDOR = 200
TREEVIEW_COLUMN_WIDTH_AMOUNT = 80
TREEVIEW_COLUMN_WIDTH_MEMO = 250
TREEVIEW_COLUMN_WIDTH_DATE = 80

# --- Autocomplete Dropdown Appearance ---
AUTOCOMPLETE_ROW_HEIGHT = 25  # Pixels per suggestion
AUTOCOMPLETE_MAX_HEIGHT = 250  # Maximum dropdown height

# --- Web Server ---
SERVER_SHUTDOWN_DELAY_SECONDS = 1.0  # Graceful connection cleanup

# --- Terminal Display ---
TERMINAL_WIDTH = 80  # For formatted output


# =============================================================================
# 5. SYSTEM CONSTANTS
# =============================================================================
# GnuCash schema definitions and system-level constants (rarely modified)

# --- GnuCash Account Types ---
ACCOUNT_TYPE_ROOT = "ROOT"
ACCOUNT_TYPE_EXPENSE = "EXPENSE"
ACCOUNT_TYPE_PAYABLE = "PAYABLE"
ACCOUNT_TYPE_BANK = "BANK"
ACCOUNT_TYPE_LIABILITY = "LIABILITY"
ACCOUNT_TYPE_ASSET = "ASSET"
ACCOUNT_TYPE_INCOME = "INCOME"

# --- GnuCash Boolean Flags (SQLite: 0=false, 1=true) ---
PLACEHOLDER_FALSE = 0
PLACEHOLDER_TRUE = 1
ACTIVE_FALSE = 0
ACTIVE_TRUE = 1

# --- Date Parsing ---
# Alternative formats tried when primary format fails
ALTERNATIVE_DATE_FORMATS = ["%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"]

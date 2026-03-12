"""
Bill Processor Configuration
Edit these settings for your environment.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# =============================================================================
# PATHS
# =============================================================================

# Project root directory
PROJECT_ROOT = Path(r"D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections")

# GnuCash database file (SQLite format)
# Using local test database copy for development
GNUCASH_DB_PATH = Path(r"D:\Users\Conrad\Documents\GnuCash\gnuCash414\CFSIV_Sqlite3_database.gnucash")

# Vendor database JSON file
VENDOR_DB_PATH = PROJECT_ROOT / "data" / "vendor_database.json"
VENDOR_DATABASE_PATH = VENDOR_DB_PATH  # Alias for compatibility

# Client name list for cash entry memo autocomplete
CLIENTS_PATH = PROJECT_ROOT / "data" / "clients.json"

# Cash/income accounts available in the cash entry dropdown
CASH_ACCOUNTS_PATH = PROJECT_ROOT / "data" / "cash_accounts.json"

# Input file for bills to process
BILLS_INPUT_PATH = PROJECT_ROOT / "data" / "bills_to_process.txt"
DEFAULT_INPUT_FILE = BILLS_INPUT_PATH  # Alias for compatibility

# =============================================================================
# LOCALITY SETTINGS (for address lookup)
# =============================================================================

# Your city and state - used to narrow address searches
LOCALITY_CITY = "Louisville"
LOCALITY_STATE = "KY"
LOCALITY_COUNTRY = "US"

# Search radius in miles for address lookups
# Note: Google Places API (New) max radius is 50,000 meters (~31 miles)
SEARCH_RADIUS_MILES = 30

# Your approximate coordinates (Louisville, KY downtown)
# Used for distance calculations and "pick closest" logic
HOME_LATITUDE = 38.2527
HOME_LONGITUDE = -85.7585
CENTER_LAT = HOME_LATITUDE  # Alias for address_lookup
CENTER_LON = HOME_LONGITUDE  # Alias for address_lookup

# Default locality string for searches
DEFAULT_LOCALITY = f"{LOCALITY_CITY}, {LOCALITY_STATE}"

# =============================================================================
# GNUCASH SETTINGS
# =============================================================================

# Accounts Payable account path
ACCOUNTS_PAYABLE_PATH = "Liabilities:Accounts Payable"

# Vendor ID prefix and format
VENDOR_ID_PREFIX = ""
VENDOR_ID_FORMAT = "{prefix}{num:06d}"  # 000001, 000002, etc.

# Bill ID prefix and format  
BILL_ID_PREFIX = "B-"
BILL_ID_FORMAT = "{prefix}{num:04d}"  # B-0001, B-0002, etc.

# Default memo when none provided
DEFAULT_MEMO = "no memo"

# Currency
DEFAULT_CURRENCY = "USD"

# Cash-on-hand account name
SAMUSE_ACCOUNT_NAME = "SAMUSE Cash-on-hand"

# Expected name of top-level expense account in chart of accounts
DEFAULT_EXPENSE_PARENT = "Expenses root"

# Fallback search pattern when PAYABLE account type not found
PAYABLE_ACCOUNT_NAME_PATTERN = "payable"

# New vendor defaults
DEFAULT_VENDOR_ACTIVE = 1  # 1 = active, 0 = inactive
DEFAULT_VENDOR_TAX_OVERRIDE = 0  # 0 = use default tax settings

# Database lock hostname prefix (distinguishes from GnuCash locks)
LOCK_HOSTNAME_PREFIX = "BillProcessor"

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

# SQLite boolean flags (0=false, 1=true)
PLACEHOLDER_FALSE = 0
PLACEHOLDER_TRUE = 1
ACTIVE_FALSE = 0
ACTIVE_TRUE = 1

# =============================================================================
# ADDRESS LOOKUP API SETTINGS
# =============================================================================

# HTTP request timeout in seconds (prevents hanging on network issues)
API_REQUEST_TIMEOUT_SECONDS = 10

# Google Places API (most accurate, requires API key)
# 
# HOW TO GET A GOOGLE PLACES API KEY:
# Run the setup script: python setup_google_api.py
# Or see GOOGLE_API_SETUP.md for manual setup instructions
#
# The API key is stored in the .env file (NOT in this config file for security)
# Get it from environment variable, default to empty string
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")

# OpenStreetMap Nominatim (free fallback, no key needed)
# Automatically used when Google API key is not configured
# Be respectful of usage limits: max 1 request per second
USE_OPENSTREETMAP = True

# OpenStreetMap API endpoint (can be changed to use alternative instances)
OSM_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# User agent for OSM requests (required by their terms)
OSM_USER_AGENT = "GnuCashBillProcessor/1.0 (personal use)"

# OSM rate limiting: delay between requests (ToS requires max 1 req/sec)
# We use 1.1s as a safety buffer
OSM_RATE_LIMIT_SECONDS = 1.1

# Number of results requested from OSM API
# More results = better coverage but slower response
OSM_SEARCH_LIMIT = 50

# Limit final address search results shown to user
# Prevents overwhelming UI with too many options
ADDRESS_SEARCH_MAX_RESULTS = 20

# Minimum word overlap required for address result filtering
# Higher values reduce false matches but may miss valid results
ADDRESS_LOOKUP_MIN_WORD_MATCHES = 2

# Business name suffixes stripped during fuzzy matching
# Improves matching: "Walmart" matches "Walmart Inc", "Kroger" matches "Kroger Store #123"
BUSINESS_NAME_SUFFIXES = [
    ' inc', ' llc', ' ltd', ' corp', ' corporation', ' company', ' co', 
    ' incorporated', ' store', ' supercenter', ' center', ' market'
]

# =============================================================================
# FUZZY MATCHING SETTINGS
# =============================================================================

# Minimum score (0-100) to consider a fuzzy match valid
FUZZY_MATCH_THRESHOLD = 70

# If two vendors both score above this, flag as ambiguous
FUZZY_AMBIGUOUS_THRESHOLD = 85

# GUI autocomplete settings (more permissive than main matching)
AUTOCOMPLETE_MATCH_THRESHOLD = 50  # Lower threshold for dropdown suggestions
AUTOCOMPLETE_PREFIX_MATCH_SCORE = 90  # Boost when search text is name prefix
AUTOCOMPLETE_CONTAINS_MATCH_SCORE = 70  # Score when search text appears anywhere
AUTOCOMPLETE_MAX_RESULTS = 10  # Limit dropdown items to prevent UI clutter

# Web UI vendor search settings (even more permissive for better UX)
WEB_VENDOR_SEARCH_MIN_SCORE = 40  # Minimum score for web vendor dropdown
WEB_VENDOR_DROPDOWN_MAX_RESULTS = 6  # Smaller limit for cleaner web interface

# Cash entry client name suggestions
CLIENT_SEARCH_MAX_RESULTS = 10

# =============================================================================
# DISPLAY SETTINGS
# =============================================================================

# Terminal width for formatting
TERMINAL_WIDTH = 80

# =============================================================================
# LOGGING
# =============================================================================

# Log file path (None to disable file logging)
LOG_FILE_PATH = PROJECT_ROOT / "logs" / "bill_processor.log"
LOG_FILE = LOG_FILE_PATH  # Alias for compatibility

# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL = "INFO"

# =============================================================================
# DATE PARSING
# =============================================================================

# Alternative date formats tried when primary format fails
# Add additional formats here for international date support
ALTERNATIVE_DATE_FORMATS = ["%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"]

# =============================================================================
# DISTANCE CALCULATION
# =============================================================================

# Earth radius in miles for Haversine distance formula
# Change to 6371 for kilometers
EARTH_RADIUS_MILES = 3959

# =============================================================================
# UI SETTINGS (Tkinter GUIs)
# =============================================================================

# Main window sizes (width x height in pixels)
BILL_ENTRY_WINDOW_WIDTH = 800
BILL_ENTRY_WINDOW_HEIGHT = 700
VENDOR_MANAGER_WINDOW_WIDTH = 800
VENDOR_MANAGER_WINDOW_HEIGHT = 600

# Dialog window size (used for sync dialogs, account selection, etc.)
DIALOG_WIDTH = 600
DIALOG_HEIGHT = 400

# Widget dimensions
COMBOBOX_WIDTH = 70  # Width in characters for dropdown boxes
ENTRY_FIELD_WIDTH_VENDOR = 50  # Vendor name entry field
ENTRY_FIELD_WIDTH_AMOUNT = 20  # Amount entry field
ENTRY_FIELD_WIDTH_MEMO = 50  # Memo entry field
ENTRY_FIELD_WIDTH_DATE = 15  # Date entry field

# Treeview column widths (pixels)
TREEVIEW_COLUMN_WIDTH_VENDOR = 200
TREEVIEW_COLUMN_WIDTH_AMOUNT = 80
TREEVIEW_COLUMN_WIDTH_MEMO = 250
TREEVIEW_COLUMN_WIDTH_DATE = 80

# Autocomplete dropdown appearance
AUTOCOMPLETE_ROW_HEIGHT = 25  # Height per suggestion row in pixels
AUTOCOMPLETE_MAX_HEIGHT = 250  # Maximum dropdown height in pixels

# =============================================================================
# WEB SERVER
# =============================================================================

# Delay before shutdown (allows graceful cleanup of connections)
SERVER_SHUTDOWN_DELAY_SECONDS = 1.0

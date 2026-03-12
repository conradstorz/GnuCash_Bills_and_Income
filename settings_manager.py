"""
Settings Manager - Runtime User-Configurable Settings

Provides a centralized manager for user-modifiable settings that can be changed
through the GUI/web interface without editing config.py. Settings automatically
persist to user_settings.json.

System constants (account types, formats, etc.) remain in config.py.
User preferences (paths, thresholds, UI dimensions) are managed here.
"""

import json
from pathlib import Path
from typing import Optional
from loguru import logger

import config


class SettingsManager:
    """Manages runtime user-configurable settings with automatic persistence."""
    
    def __init__(self, settings_file: Optional[Path] = None):
        """
        Initialize settings manager.
        
        Args:
            settings_file: Path to user_settings.json (defaults to data/user_settings.json)
        """
        self.settings_file = settings_file or (config.PROJECT_ROOT / "data" / "user_settings.json")
        self._settings = {}
        self.load()
    
    def load(self):
        """Load settings from file, falling back to config.py defaults."""
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r') as f:
                    self._settings = json.load(f)
                logger.info(f"Loaded user settings from {self.settings_file}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load user settings: {e}, using defaults")
                self._load_defaults()
        else:
            logger.info("No user settings file found, using config.py defaults")
            self._load_defaults()
            self.save()  # Create initial settings file
    
    def _load_defaults(self):
        """Load default values from config.py."""
        self._settings = {
            # Database & Paths
            "gnucash_db_path": str(config.GNUCASH_DB_PATH),
            
            # Locality Settings
            "locality_city": config.LOCALITY_CITY,
            "locality_state": config.LOCALITY_STATE,
            "locality_country": config.LOCALITY_COUNTRY,
            "home_latitude": config.HOME_LATITUDE,
            "home_longitude": config.HOME_LONGITUDE,
            "search_radius_miles": config.SEARCH_RADIUS_MILES,
            
            # GnuCash Account Paths (business-specific)
            "accounts_payable_path": config.ACCOUNTS_PAYABLE_PATH,
            "default_expense_parent": config.DEFAULT_EXPENSE_PARENT,
            "cash_on_hand_account_name": config.CASH_ON_HAND_ACCOUNT_NAME,
            
            # Default Values
            "default_memo": config.DEFAULT_MEMO,
            "default_currency": config.DEFAULT_CURRENCY,
            
            # Fuzzy Matching Thresholds
            "fuzzy_match_threshold": config.FUZZY_MATCH_THRESHOLD,
            "fuzzy_ambiguous_threshold": config.FUZZY_AMBIGUOUS_THRESHOLD,
            "autocomplete_match_threshold": config.AUTOCOMPLETE_MATCH_THRESHOLD,
            "autocomplete_prefix_match_score": config.AUTOCOMPLETE_PREFIX_MATCH_SCORE,
            "autocomplete_contains_match_score": config.AUTOCOMPLETE_CONTAINS_MATCH_SCORE,
            "autocomplete_max_results": config.AUTOCOMPLETE_MAX_RESULTS,
            "web_vendor_search_min_score": config.WEB_VENDOR_SEARCH_MIN_SCORE,
            "web_vendor_dropdown_max_results": config.WEB_VENDOR_DROPDOWN_MAX_RESULTS,
            "client_search_max_results": config.CLIENT_SEARCH_MAX_RESULTS,
            
            # Address Lookup
            "api_request_timeout_seconds": config.API_REQUEST_TIMEOUT_SECONDS,
            "osm_rate_limit_seconds": config.OSM_RATE_LIMIT_SECONDS,
            "osm_search_limit": config.OSM_SEARCH_LIMIT,
            "address_search_max_results": config.ADDRESS_SEARCH_MAX_RESULTS,
            "address_lookup_min_word_matches": config.ADDRESS_LOOKUP_MIN_WORD_MATCHES,
            
            # UI Dimensions - Tkinter Windows
            "bill_entry_window_width": config.BILL_ENTRY_WINDOW_WIDTH,
            "bill_entry_window_height": config.BILL_ENTRY_WINDOW_HEIGHT,
            "vendor_manager_window_width": config.VENDOR_MANAGER_WINDOW_WIDTH,
            "vendor_manager_window_height": config.VENDOR_MANAGER_WINDOW_HEIGHT,
            "dialog_window_width": config.DIALOG_WINDOW_WIDTH,
            "dialog_window_height": config.DIALOG_WINDOW_HEIGHT,
            
            # UI Dimensions - Widgets
            "combobox_width": config.COMBOBOX_WIDTH,
            "entry_field_width_vendor": config.ENTRY_FIELD_WIDTH_VENDOR,
            "entry_field_width_amount": config.ENTRY_FIELD_WIDTH_AMOUNT,
            "entry_field_width_memo": config.ENTRY_FIELD_WIDTH_MEMO,
            "entry_field_width_date": config.ENTRY_FIELD_WIDTH_DATE,
            
            # UI Dimensions - Treeview Columns
            "treeview_column_width_vendor": config.TREEVIEW_COLUMN_WIDTH_VENDOR,
            "treeview_column_width_amount": config.TREEVIEW_COLUMN_WIDTH_AMOUNT,
            "treeview_column_width_memo": config.TREEVIEW_COLUMN_WIDTH_MEMO,
            "treeview_column_width_date": config.TREEVIEW_COLUMN_WIDTH_DATE,
            
            # UI Dimensions - Autocomplete
            "autocomplete_row_height": config.AUTOCOMPLETE_ROW_HEIGHT,
            "autocomplete_max_height": config.AUTOCOMPLETE_MAX_HEIGHT,
            
            # Web Server
            "server_shutdown_delay_seconds": config.SERVER_SHUTDOWN_DELAY_SECONDS,
            
            # Display
            "terminal_width": config.TERMINAL_WIDTH,
            "log_level": config.LOG_LEVEL,
        }
    
    def save(self):
        """Persist current settings to JSON file."""
        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.settings_file, 'w') as f:
                json.dump(self._settings, f, indent=2)
            logger.debug(f"Saved user settings to {self.settings_file}")
        except IOError as e:
            logger.error(f"Failed to save user settings: {e}")
    
    def get(self, key: str, default=None):
        """Get a setting value by key."""
        return self._settings.get(key, default)
    
    def set(self, key: str, value):
        """Set a setting value and save to disk."""
        self._settings[key] = value
        self.save()
    
    def update(self, **kwargs):
        """Update multiple settings at once."""
        self._settings.update(kwargs)
        self.save()
    
    def reset_to_defaults(self):
        """Reset all settings to config.py defaults."""
        self._load_defaults()
        self.save()
        logger.info("Reset all settings to defaults")
    
    # Convenience property accessors for commonly used settings
    
    @property
    def gnucash_db_path(self) -> Path:
        """Path to GnuCash database file."""
        return Path(self._settings["gnucash_db_path"])
    
    @gnucash_db_path.setter
    def gnucash_db_path(self, value: Path):
        self.set("gnucash_db_path", str(value))
    
    @property
    def locality_city(self) -> str:
        return self._settings["locality_city"]
    
    @property
    def locality_state(self) -> str:
        return self._settings["locality_state"]
    
    @property
    def locality_coordinates(self) -> tuple[float, float]:
        """Returns (latitude, longitude) tuple."""
        return (self._settings["home_latitude"], self._settings["home_longitude"])
    
    def update_locality(self, city: str, state: str, country: str, 
                       latitude: float, longitude: float, 
                       search_radius: Optional[int] = None):
        """Update all locality-related settings at once."""
        updates = {
            "locality_city": city,
            "locality_state": state,
            "locality_country": country,
            "home_latitude": latitude,
            "home_longitude": longitude,
        }
        if search_radius is not None:
            updates["search_radius_miles"] = search_radius
        self.update(**updates)
        logger.info(f"Updated locality settings: {city}, {state}")
    
    @property
    def fuzzy_match_threshold(self) -> int:
        return self._settings["fuzzy_match_threshold"]
    
    @fuzzy_match_threshold.setter
    def fuzzy_match_threshold(self, value: int):
        self.set("fuzzy_match_threshold", value)
    
    @property
    def log_level(self) -> str:
        return self._settings.get("log_level", "INFO")
    
    @log_level.setter
    def log_level(self, value: str):
        self.set("log_level", value.upper())
    
    def to_dict(self) -> dict:
        """Export all settings as dictionary."""
        return self._settings.copy()


# Global settings instance
settings = SettingsManager()


# Backward compatibility: allow importing like config.SETTING_NAME
# This provides a migration path for existing code
def __getattr__(name):
    """
    Fallback for attribute access - tries settings, then config.
    
    This allows existing code like `from config import FUZZY_MATCH_THRESHOLD`
    to work with minimal changes during migration.
    """
    # Try settings manager first
    setting_key = name.lower()
    if setting_key in settings._settings:
        return settings._settings[setting_key]
    
    # Fall back to config.py
    if hasattr(config, name):
        return getattr(config, name)
    
    raise AttributeError(f"Setting '{name}' not found in settings or config")

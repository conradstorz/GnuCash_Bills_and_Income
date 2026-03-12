"""
Tests for SettingsManager - runtime user-configurable settings.
"""

import json
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from settings_manager import SettingsManager
import config


@pytest.fixture
def temp_settings_file(tmp_path):
    """Create a temporary settings file for testing."""
    settings_file = tmp_path / "test_user_settings.json"
    return settings_file


@pytest.fixture
def settings_manager(temp_settings_file):
    """Create a fresh SettingsManager instance with temp file."""
    return SettingsManager(settings_file=temp_settings_file)


class TestSettingsManagerInit:
    """Test SettingsManager initialization and default loading."""
    
    def test_creates_settings_file_on_first_run(self, temp_settings_file):
        """Should create settings file if it doesn't exist."""
        assert not temp_settings_file.exists()
        
        manager = SettingsManager(settings_file=temp_settings_file)
        
        assert temp_settings_file.exists()
        assert manager._settings is not None
    
    def test_loads_defaults_from_config(self, settings_manager):
        """Should load default values from config.py."""
        # Check a few key settings match config.py
        assert settings_manager.get("locality_city") == config.LOCALITY_CITY
        assert settings_manager.get("fuzzy_match_threshold") == config.FUZZY_MATCH_THRESHOLD
        assert settings_manager.get("search_radius_miles") == config.SEARCH_RADIUS_MILES
    
    def test_loads_existing_settings_file(self, temp_settings_file):
        """Should load settings from existing file."""
        # Create a settings file with custom values
        custom_settings = {
            "locality_city": "TestCity",
            "fuzzy_match_threshold": 85,
            "search_radius_miles": 50,
        }
        with open(temp_settings_file, 'w') as f:
            json.dump(custom_settings, f)
        
        manager = SettingsManager(settings_file=temp_settings_file)
        
        assert manager.get("locality_city") == "TestCity"
        assert manager.get("fuzzy_match_threshold") == 85
        assert manager.get("search_radius_miles") == 50


class TestSettingsManagerPersistence:
    """Test settings save/load functionality."""
    
    def test_save_persists_to_file(self, settings_manager, temp_settings_file):
        """Should save settings to JSON file."""
        settings_manager.set("fuzzy_match_threshold", 99)
        
        # Read file directly
        with open(temp_settings_file, 'r') as f:
            data = json.load(f)
        
        assert data["fuzzy_match_threshold"] == 99
    
    def test_set_saves_automatically(self, settings_manager, temp_settings_file):
        """Should automatically save when using set()."""
        settings_manager.set("locality_city", "NewCity")
        
        # Create new manager instance to verify persistence
        new_manager = SettingsManager(settings_file=temp_settings_file)
        assert new_manager.get("locality_city") == "NewCity"
    
    def test_update_saves_multiple_settings(self, settings_manager):
        """Should update multiple settings with one save."""
        settings_manager.update(
            locality_city="UpdatedCity",
            fuzzy_match_threshold=88,
            search_radius_miles=40
        )
        
        assert settings_manager.get("locality_city") == "UpdatedCity"
        assert settings_manager.get("fuzzy_match_threshold") == 88
        assert settings_manager.get("search_radius_miles") == 40


class TestSettingsManagerLocality:
    """Test locality-specific convenience methods."""
    
    def test_update_locality_sets_all_fields(self, settings_manager):
        """Should update all locality fields at once."""
        settings_manager.update_locality(
            city="Cincinnati",
            state="OH",
            country="US",
            latitude=39.1031,
            longitude=-84.5120,
            search_radius=25
        )
        
        assert settings_manager.locality_city == "Cincinnati"
        assert settings_manager.locality_state == "OH"
        assert settings_manager.get("locality_country") == "US"
        assert settings_manager.locality_coordinates == (39.1031, -84.5120)
        assert settings_manager.get("search_radius_miles") == 25
    
    def test_locality_coordinates_property(self, settings_manager):
        """Should return (lat, lon) tuple."""
        coords = settings_manager.locality_coordinates
        
        assert isinstance(coords, tuple)
        assert len(coords) == 2
        assert coords[0] == config.HOME_LATITUDE
        assert coords[1] == config.HOME_LONGITUDE


class TestSettingsManagerProperties:
    """Test property accessors for common settings."""
    
    def test_gnucash_db_path_property(self, settings_manager):
        """Should return Path object for database."""
        db_path = settings_manager.gnucash_db_path
        
        assert isinstance(db_path, Path)
        assert str(db_path) == str(config.GNUCASH_DB_PATH)
    
    def test_gnucash_db_path_setter(self, settings_manager):
        """Should update database path."""
        new_path = Path("/test/path/database.gnucash")
        settings_manager.gnucash_db_path = new_path
        
        assert settings_manager.gnucash_db_path == new_path
    
    def test_fuzzy_match_threshold_property(self, settings_manager):
        """Should get/set fuzzy match threshold."""
        original = settings_manager.fuzzy_match_threshold
        
        settings_manager.fuzzy_match_threshold = 88
        assert settings_manager.fuzzy_match_threshold == 88
        
        # Verify it persisted
        assert settings_manager.get("fuzzy_match_threshold") == 88
    
    def test_log_level_property(self, settings_manager):
        """Should get/set log level with uppercase normalization."""
        settings_manager.log_level = "debug"
        
        assert settings_manager.log_level == "DEBUG"


class TestSettingsManagerReset:
    """Test reset to defaults functionality."""
    
    def test_reset_to_defaults_restores_config_values(self, settings_manager):
        """Should reset all settings to config.py defaults."""
        # Modify some settings
        settings_manager.update(
            locality_city="ModifiedCity",
            fuzzy_match_threshold=99,
            search_radius_miles=100
        )
        
        # Reset
        settings_manager.reset_to_defaults()
        
        # Should match config.py
        assert settings_manager.get("locality_city") == config.LOCALITY_CITY
        assert settings_manager.get("fuzzy_match_threshold") == config.FUZZY_MATCH_THRESHOLD
        assert settings_manager.get("search_radius_miles") == config.SEARCH_RADIUS_MILES


class TestSettingsManagerExport:
    """Test settings export functionality."""
    
    def test_to_dict_returns_copy(self, settings_manager):
        """Should return a copy of settings dict."""
        exported = settings_manager.to_dict()
        
        assert isinstance(exported, dict)
        assert len(exported) > 0
        
        # Modify exported dict shouldn't affect manager
        exported["locality_city"] = "ChangedCity"
        assert settings_manager.get("locality_city") != "ChangedCity"


class TestSettingsManagerGetSet:
    """Test basic get/set operations."""
    
    def test_get_existing_setting(self, settings_manager):
        """Should retrieve existing setting value."""
        value = settings_manager.get("locality_city")
        assert value is not None
    
    def test_get_nonexistent_setting_returns_default(self, settings_manager):
        """Should return default for non-existent keys."""
        value = settings_manager.get("nonexistent_key", "default_value")
        assert value == "default_value"
    
    def test_set_creates_new_setting(self, settings_manager):
        """Should allow setting new keys."""
        settings_manager.set("custom_setting", "custom_value")
        assert settings_manager.get("custom_setting") == "custom_value"


class TestSettingsManagerErrorHandling:
    """Test error handling for corrupted files, etc."""
    
    def test_handles_corrupted_json_file(self, temp_settings_file):
        """Should fall back to defaults if JSON is corrupted."""
        # Write invalid JSON
        with open(temp_settings_file, 'w') as f:
            f.write("{ invalid json }")
        
        # Should not crash, should use defaults
        manager = SettingsManager(settings_file=temp_settings_file)
        assert manager.get("locality_city") == config.LOCALITY_CITY
    
    def test_handles_missing_parent_directory(self, tmp_path):
        """Should create parent directories if they don't exist."""
        nested_file = tmp_path / "nested" / "dir" / "settings.json"
        
        manager = SettingsManager(settings_file=nested_file)
        manager.save()
        
        assert nested_file.exists()


class TestBackwardCompatibility:
    """Test backward compatibility with existing config.py imports."""
    
    def test_module_getattr_returns_setting_values(self):
        """Should allow importing settings like config constants."""
        from settings_manager import settings
        
        # Lowercase setting keys should work
        assert hasattr(settings, '_settings')
        assert 'locality_city' in settings._settings
    
    def test_falls_back_to_config_for_system_constants(self):
        """Should fall back to config.py for non-setting constants."""
        import settings_manager
        
        # System constants should still be accessible via config
        assert hasattr(config, 'ACCOUNT_TYPE_EXPENSE')
        assert config.ACCOUNT_TYPE_EXPENSE == "EXPENSE"

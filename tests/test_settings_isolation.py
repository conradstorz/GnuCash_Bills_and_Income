"""Regression tests: the test suite must never touch the real user_settings.json.

A prior bug let the installer test and web-app settings tests persist throwaway
values (a pytest temp DB path, placeholder account GUIDs) into the user's real
data/user_settings.json, because they drove the module-level SettingsManager
singleton, which was hard-bound to that real file.
"""
import os
from pathlib import Path

from bill_processor import config, settings_manager


def _real_settings_path() -> Path:
    return (config.PROJECT_ROOT / "data" / "user_settings.json").resolve()


def test_env_override_is_active_under_test():
    """conftest must point the settings layer at a throwaway file."""
    override = os.environ.get("BILL_PROCESSOR_SETTINGS_FILE")
    assert override, "conftest must set BILL_PROCESSOR_SETTINGS_FILE"
    assert Path(override).resolve() != _real_settings_path()


def test_default_settings_manager_does_not_bind_to_real_file():
    """A default-constructed SettingsManager must honor the env override, not the
    real data/user_settings.json. Asserts on the path BEFORE any write, so this
    test is safe to run even when the fix is absent (it fails without writing)."""
    sm = settings_manager.SettingsManager()  # no explicit settings_file
    assert sm.settings_file.resolve() != _real_settings_path()


def test_saving_settings_never_writes_real_file():
    """Persisting via the shared singleton must not create or modify the real
    file. The path check above guarantees the write below lands in a temp file."""
    real = _real_settings_path()
    before = real.read_bytes() if real.exists() else None

    # The singleton is what install.py / web.app mutate.
    sm = settings_manager.settings
    assert sm.settings_file.resolve() != real
    sm.set("terminal_width", 4321)  # triggers save()

    after = real.read_bytes() if real.exists() else None
    assert after == before, "settings save leaked into the real user_settings.json"

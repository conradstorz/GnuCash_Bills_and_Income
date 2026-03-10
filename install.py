#!/usr/bin/env python3
"""
GnuCash Bills Installer

Sets up the app after git clone: updates config.py with the real project
root and GnuCash database path, generates a platform-appropriate launcher
script, and optionally copies it to the desktop.

Run with:
    uv run python install.py
"""
import os
import re
import shutil
import sys
import subprocess
from datetime import datetime
from pathlib import Path


def update_config(config_path: Path, project_root: Path, db_path: Path) -> None:
    """Update PROJECT_ROOT and GNUCASH_DB_PATH in config.py.

    Raises ValueError if either pattern is not found (file is not written).
    """
    text = config_path.read_text(encoding="utf-8")

    new_text, count1 = re.subn(
        r'(PROJECT_ROOT\s*=\s*Path\(r?)["\'].*?["\'](\))',
        lambda m: f'{m.group(1)}r"{project_root}"{m.group(2)}',
        text,
    )
    if count1 == 0:
        raise ValueError("Could not find PROJECT_ROOT in config.py")

    new_text, count2 = re.subn(
        r'(GNUCASH_DB_PATH\s*=\s*Path\(r?)["\'].*?["\'](\))',
        lambda m: f'{m.group(1)}r"{db_path}"{m.group(2)}',
        new_text,
    )
    if count2 == 0:
        raise ValueError("Could not find GNUCASH_DB_PATH in config.py")

    config_path.write_text(new_text, encoding="utf-8")


if __name__ == "__main__":
    print("Installer not yet fully implemented.")

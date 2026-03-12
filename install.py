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

from loguru import logger
from bill_processor import logging_setup


def update_config(config_path: Path, project_root: Path, db_path: Path) -> None:
    """Update PROJECT_ROOT and GNUCASH_DB_PATH in config.py.

    Raises ValueError if either pattern is not found (file is not written).
    """
    logger.debug(f"Updating config file: {config_path}")
    logger.debug(f"  PROJECT_ROOT={project_root}")
    logger.debug(f"  GNUCASH_DB_PATH={db_path}")
    
    text = config_path.read_text(encoding="utf-8")

    new_text, count1 = re.subn(
        r'(PROJECT_ROOT\s*=\s*Path\()r?["\'].*?["\'](\))',
        lambda m: f'{m.group(1)}r"{project_root}"{m.group(2)}',
        text,
    )
    if count1 == 0:
        logger.error("PROJECT_ROOT pattern not found in config.py")
        raise ValueError("Could not find PROJECT_ROOT in config.py")

    new_text, count2 = re.subn(
        r'(GNUCASH_DB_PATH\s*=\s*Path\()r?["\'].*?["\'](\))',
        lambda m: f'{m.group(1)}r"{db_path}"{m.group(2)}',
        new_text,
    )
    if count2 == 0:
        logger.error("GNUCASH_DB_PATH pattern not found in config.py")
        raise ValueError("Could not find GNUCASH_DB_PATH in config.py")

    config_path.write_text(new_text, encoding="utf-8")
    logger.debug("Config file updated successfully")


def search_for_gnucash(search_root: Path) -> list:
    """Search search_root recursively for *.gnucash files.

    Returns list of Paths sorted newest-modified first.
    Returns empty list if search_root does not exist.
    """
    logger.debug(f"Searching for .gnucash files in: {search_root}")
    if not search_root.exists():
        logger.debug(f"Search root does not exist: {search_root}")
        return []
    files = list(search_root.rglob("*.gnucash"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    logger.debug(f"Found {len(files)} .gnucash file(s)")
    return files


def open_file_picker():
    """Open a native file picker dialog. Returns Path or None if cancelled."""
    logger.debug("Opening file picker dialog")
    try:
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import tkinter as tk; from tkinter import filedialog; "
                "root = tk.Tk(); root.withdraw(); "
                "root.wm_attributes('-topmost', 1); "
                "path = filedialog.askopenfilename("
                "    title='Select GnuCash database file',"
                "    filetypes=[('GnuCash files', '*.gnucash'), ('All files', '*.*')]"
                "); print(path)",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        path_str = result.stdout.strip()
        selected_path = Path(path_str) if path_str else None
        if selected_path:
            logger.debug(f"User selected file: {selected_path}")
        else:
            logger.debug("File picker cancelled by user")
        return selected_path
    except Exception as e:
        logger.error(f"File picker failed: {e}")
        return None


def pick_gnucash_file(candidates: list):
    """Present found files to user; return chosen Path or None.

    candidates: list of Path objects sorted newest-first.
    Shows numbered list. User picks a number, 'b' to browse, or 'q' to quit.
    If candidates is empty, goes straight to file picker (Enter or 'b' to open,
    'q' to quit).
    """
    if candidates:
        logger.info("\nFound .gnucash files:")
        for i, p in enumerate(candidates, 1):
            mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
            logger.info(f"  {i}. {p}  (modified {mtime})")
        logger.info("  b. Browse for a different file...")
        logger.info("")
    else:
        logger.info("\nNo .gnucash files found in Documents.")
        logger.info("  Press Enter or 'b' to browse, 'q' to quit.")
        logger.info("")

    while True:
        if candidates:
            choice = input("Enter number or 'b': ").strip().lower()
        else:
            choice = input("Choice [b/q]: ").strip().lower()

        if choice == "q":
            logger.debug("User chose to quit")
            return None

        if choice in ("", "b"):
            return open_file_picker()

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                logger.debug(f"User selected file #{choice}: {candidates[idx]}")
                return candidates[idx]
            logger.info(f"  Please enter a number between 1 and {len(candidates)}.")
        else:
            logger.info("  Invalid choice.")


def generate_launcher(project_root: Path) -> Path:
    """Write a platform-appropriate launcher script to project_root.

    Windows: GnuCash Bills.bat
    Linux/macOS: GnuCash Bills.sh  (chmod 755 applied)

    Returns the Path of the written launcher file.
    """
    logger.debug(f"Generating launcher for platform: {sys.platform}")
    if sys.platform == "win32":
        launcher_path = project_root / "GnuCash Bills.bat"
        content = (
            "@echo off\n"
            "title GnuCash Bills - Starting...\n"
            "echo Starting GnuCash Bills server on port 7432...\n"
            f'start /min "GnuCash Bills Server" cmd /k '
            f'"cd /d {project_root} && uv run uvicorn bill_processor.web.app:app --port 7432"\n'
            "echo Waiting for server to start...\n"
            "timeout /t 2 /nobreak >nul\n"
            "echo Opening browser...\n"
            "start http://localhost:7432\n"
            "echo Done. Server is running in the background (minimized in taskbar).\n"
            "echo Close the minimized console window to stop the server.\n"
            "timeout /t 3 /nobreak >nul\n"
        )
    else:
        launcher_path = project_root / "GnuCash Bills.sh"
        content = (
            "#!/bin/bash\n"
            f'cd "{project_root}"\n'
            "uv run uvicorn bill_processor.web.app:app --port 7432 &\n"
            "sleep 2\n"
            "xdg-open http://localhost:7432\n"
        )

    launcher_path.write_text(content, encoding="utf-8")
    logger.debug(f"Launcher written to: {launcher_path}")

    if sys.platform != "win32":
        os.chmod(launcher_path, 0o755)
        logger.debug("Set executable permissions on launcher")

    return launcher_path


def copy_to_desktop(launcher_path: Path) -> bool:
    """Copy launcher to Desktop if it exists. Returns True if successfully copied.

    Prompts before overwriting an existing file.
    Prints a message if the Desktop folder is not found.
    """
    desktop = Path.home() / "Desktop"
    logger.debug(f"Checking for Desktop folder: {desktop}")

    if not desktop.exists():
        logger.info(f"\nDesktop folder not found. Launcher is at:\n  {launcher_path}")
        return False

    dest = desktop / launcher_path.name
    logger.info(f"Attempting to place a launcher shortcut on your Desktop: {dest}")

    if dest.exists():
        print(f"\n'{launcher_path.name}' already exists on Desktop. Overwrite? [Y/n]: ", end="")
        answer = input("").strip().lower()
    else:
        answer = input(
            f"\nCopy '{launcher_path.name}' to Desktop? [Y/n]: "
        ).strip().lower()

    if answer not in ("", "y", "yes"):
        logger.info("Skipped desktop copy.")
        logger.debug(f"User declined desktop copy (answer: {answer})")
        return False

    try:
        shutil.copy2(launcher_path, dest)
        logger.debug(f"Successfully copied launcher to: {dest}")
        return True
    except Exception as e:
        logger.error(f"Could not copy to Desktop: {e}")
        return False


def main(config_path: Path = None, project_root: Path = None):
    """Run the installer.

    config_path and project_root are injectable for testing; in production
    they are auto-detected from __file__.
    """
    if project_root is None:
        project_root = Path(__file__).parent.resolve()
    if config_path is None:
        config_path = project_root / "config.py"

    # Setup logging with simple console output (just the message)
    logging_setup.setup_logging(module_name="install")
    # Reconfigure console handler for simple output
    logger.remove()  # Remove all handlers
    # Add simple console handler (just the message)
    logger.add(sys.stderr, format="{message}", level="INFO", colorize=False)
    # Add detailed file handler
    from bill_processor import config
    logger.add(
        config.LOG_FILE_PATH,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="30 days",
    )
    
    logger.debug("Starting GnuCash Bills Installer")
    logger.debug(f"Project root: {project_root}")
    logger.debug(f"Config path: {config_path}")

    logger.info("GnuCash Bills Installer")
    logger.info(f"Project root: {project_root}")
    logger.info("")

    # Find the GnuCash database
    logger.info("Searching for .gnucash files in Documents...")
    candidates = search_for_gnucash(Path.home() / "Documents")
    db_path = pick_gnucash_file(candidates)

    if db_path is None:
        logger.info("No database selected. Exiting.")
        logger.debug("Installation cancelled - no database selected")
        return

    # Update config.py
    try:
        update_config(config_path, project_root, db_path)
        logger.info(f"Updated config.py")
    except ValueError as e:
        logger.error(f"Error: {e}")
        return

    # Generate launcher
    try:
        launcher_path = generate_launcher(project_root)
        logger.info(f"Generated launcher: {launcher_path.name}")
    except Exception as e:
        logger.error(f"Error generating launcher: {e}")
        return

    # Desktop copy
    copied = copy_to_desktop(launcher_path)

    # Summary
    logger.info("")
    logger.info("Setup complete!")
    logger.info(f"  Project root:  {project_root}")
    logger.info(f"  Database:      {db_path}")
    suffix = " (also copied to Desktop)" if copied else ""
    logger.info(f"  Launcher:      {launcher_path.name}{suffix}")
    logger.debug("Installation completed successfully")


if __name__ == "__main__":
    main()

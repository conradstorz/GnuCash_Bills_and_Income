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


def pick_gnucash_file(candidates: list, current_db: Path = None):
    """Present found files to user; return chosen Path or None.

    candidates: list of Path objects sorted newest-first.
    current_db: currently configured database path (if any).
    Shows numbered list. User picks a number, 'k' to keep current, 'b' to browse, or 'q' to quit.
    If candidates is empty, goes straight to file picker (Enter or 'b' to open,
    'q' to quit).
    """
    # Show current database if it exists
    if current_db and current_db.exists():
        mtime = datetime.fromtimestamp(current_db.stat().st_mtime).strftime("%Y-%m-%d")
        logger.info(f"\nCurrently configured database:")
        logger.info(f"  {current_db}  (modified {mtime})")
        logger.info("")
    
    if candidates:
        logger.info("Found .gnucash files in Documents:")
        for i, p in enumerate(candidates, 1):
            mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
            is_current = " (current)" if current_db and p == current_db else ""
            logger.info(f"  {i}. {p}  (modified {mtime}){is_current}")
        if current_db and current_db.exists():
            logger.info("  k. Keep current database")
        logger.info("  b. Browse for a different file...")
        logger.info("")
    else:
        if not (current_db and current_db.exists()):
            logger.info("\nNo .gnucash files found in Documents.")
            logger.info("  Press Enter or 'b' to browse, 'q' to quit.")
            logger.info("")

    while True:
        if candidates or (current_db and current_db.exists()):
            prompt = "Enter number"
            if current_db and current_db.exists():
                prompt += ", 'k' (keep)"
            prompt += ", or 'b' (browse): "
            choice = input(prompt).strip().lower()
        else:
            choice = input("Choice [b/q]: ").strip().lower()

        if choice == "q":
            logger.debug("User chose to quit")
            return None

        if choice == "k" and current_db and current_db.exists():
            logger.debug(f"User chose to keep current database: {current_db}")
            return current_db

        if choice in ("", "b"):
            return open_file_picker()

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                selected = candidates[idx]
                logger.debug(f"User selected file #{choice}: {selected}")
                return selected
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
            'echo Checking if GnuCash Bills server is already running on port 7432...\n'
            "netstat -ano | findstr :7432 | findstr LISTENING >nul 2>&1\n"
            "if %errorlevel% equ 0 (\n"
            "    echo Server is already running. Opening browser...\n"
            "    start http://localhost:7432\n"
            "    echo Done.\n"
            "    timeout /t 2 /nobreak >nul\n"
            "    exit /b 0\n"
            ")\n"
            "\n"
            "echo Starting GnuCash Bills server on port 7432...\n"
            f'start "GnuCash Bills Server" cmd /c "cd /d {project_root} && uv run uvicorn bill_processor.web.app:app --port 7432 & echo. & echo Server stopped. Closing window in 3 seconds... & timeout /t 3 /nobreak >nul"\n'
            "echo Waiting for server to start...\n"
            "set /a attempts=0\n"
            ":wait_loop\n"
            "timeout /t 1 /nobreak >nul\n"
            "set /a attempts+=1\n"
            "netstat -ano | findstr :7432 | findstr LISTENING >nul 2>&1\n"
            "if %errorlevel% equ 0 goto server_ready\n"
            "if %attempts% lss 30 goto wait_loop\n"
            "\n"
            "echo ERROR: Server failed to start on port 7432 after 30 seconds.\n"
            "echo Check the server console window for errors.\n"
            "pause\n"
            "exit /b 1\n"
            "\n"
            ":server_ready\n"
            "\n"
            "echo Opening browser...\n"
            "start http://localhost:7432\n"
            "echo.\n"
            "echo SUCCESS: Server is running in a separate console window.\n"
            "echo Close the server console window to stop the application.\n"
            "echo.\n"
            "echo This window will close automatically in 20 seconds...\n"
            "timeout /t 20 >nul\n"
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

    # Check for existing database configuration
    current_db = None
    try:
        from bill_processor.settings_manager import settings
        if settings.gnucash_db_path and Path(settings.gnucash_db_path).exists():
            current_db = Path(settings.gnucash_db_path)
            logger.debug(f"Found existing database in settings: {current_db}")
        elif settings.gnucash_db_path:
            logger.debug(f"Settings has database path but file doesn't exist: {settings.gnucash_db_path}")
    except Exception as e:
        logger.debug(f"Could not load settings_manager: {e}")

    # Find the GnuCash database
    logger.info("Searching for .gnucash files in Documents...")
    candidates = search_for_gnucash(Path.home() / "Documents")
    db_path = pick_gnucash_file(candidates, current_db=current_db)

    if db_path is None:
        logger.info("No database selected. Exiting.")
        logger.debug("Installation cancelled - no database selected")
        return

    # Check if user kept the existing database
    if current_db and db_path == current_db:
        logger.info(f"Keeping current database: {db_path}")
        logger.debug("User kept existing database, skipping config update")
    else:
        # Update config.py (default/fallback)
        try:
            update_config(config_path, project_root, db_path)
            logger.info(f"Updated config.py")
        except ValueError as e:
            logger.error(f"Error: {e}")
            return
        
        # Update settings_manager (runtime configuration)
        try:
            from bill_processor.settings_manager import settings
            settings.gnucash_db_path = db_path
            logger.info(f"Updated user settings")
            logger.debug(f"Set gnucash_db_path in settings to: {db_path}")
        except Exception as e:
            logger.warning(f"Could not update settings_manager (config.py was updated): {e}")
            logger.debug(f"Settings update error: {e}")

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

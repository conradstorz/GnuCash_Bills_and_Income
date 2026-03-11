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


def search_for_gnucash(search_root: Path) -> list:
    """Search search_root recursively for *.gnucash files.

    Returns list of Paths sorted newest-modified first.
    Returns empty list if search_root does not exist.
    """
    if not search_root.exists():
        return []
    files = list(search_root.rglob("*.gnucash"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def open_file_picker():
    """Open a native file picker dialog. Returns Path or None if cancelled."""
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
        return Path(path_str) if path_str else None
    except Exception:
        return None


def pick_gnucash_file(candidates: list):
    """Present found files to user; return chosen Path or None.

    candidates: list of Path objects sorted newest-first.
    Shows numbered list. User picks a number, 'b' to browse, or 'q' to quit.
    If candidates is empty, goes straight to file picker (Enter or 'b' to open,
    'q' to quit).
    """
    if candidates:
        print("\nFound .gnucash files:")
        for i, p in enumerate(candidates, 1):
            mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
            print(f"  {i}. {p}  (modified {mtime})")
        print("  b. Browse for a different file...")
        print()
    else:
        print("\nNo .gnucash files found in Documents.")
        print("  Press Enter or 'b' to browse, 'q' to quit.")
        print()

    while True:
        if candidates:
            choice = input("Enter number or 'b': ").strip().lower()
        else:
            choice = input("Choice [b/q]: ").strip().lower()

        if choice == "q":
            return None

        if choice in ("", "b"):
            return open_file_picker()

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]
            print(f"  Please enter a number between 1 and {len(candidates)}.")
        else:
            print("  Invalid choice.")


def generate_launcher(project_root: Path) -> Path:
    """Write a platform-appropriate launcher script to project_root.

    Windows: GnuCash Bills.bat
    Linux/macOS: GnuCash Bills.sh  (chmod 755 applied)

    Returns the Path of the written launcher file.
    """
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

    if sys.platform != "win32":
        os.chmod(launcher_path, 0o755)

    return launcher_path


def copy_to_desktop(launcher_path: Path) -> bool:
    """Copy launcher to Desktop if it exists. Returns True if successfully copied.

    Prompts before overwriting an existing file.
    Prints a message if the Desktop folder is not found.
    """
    desktop = Path.home() / "Desktop"

    if not desktop.exists():
        print(f"\nDesktop folder not found. Launcher is at:\n  {launcher_path}")
        return False

    dest = desktop / launcher_path.name

    if dest.exists():
        print(f"\n'{launcher_path.name}' already exists on Desktop. Overwrite? [Y/n]: ", end="")
        answer = input("").strip().lower()
    else:
        answer = input(
            f"\nCopy '{launcher_path.name}' to Desktop? [Y/n]: "
        ).strip().lower()

    if answer not in ("", "y", "yes"):
        print("Skipped desktop copy.")
        return False

    try:
        shutil.copy2(launcher_path, dest)
        return True
    except Exception as e:
        print(f"Could not copy to Desktop: {e}")
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

    print("GnuCash Bills Installer")
    print(f"Project root: {project_root}")
    print()

    # Find the GnuCash database
    print("Searching for .gnucash files in Documents...")
    candidates = search_for_gnucash(Path.home() / "Documents")
    db_path = pick_gnucash_file(candidates)

    if db_path is None:
        print("No database selected. Exiting.")
        return

    # Update config.py
    try:
        update_config(config_path, project_root, db_path)
        print(f"Updated config.py")
    except ValueError as e:
        print(f"Error: {e}")
        return

    # Generate launcher
    launcher_path = generate_launcher(project_root)
    print(f"Generated launcher: {launcher_path.name}")

    # Desktop copy
    copied = copy_to_desktop(launcher_path)

    # Summary
    print()
    print("Setup complete!")
    print(f"  Project root:  {project_root}")
    print(f"  Database:      {db_path}")
    suffix = " (also copied to Desktop)" if copied else ""
    print(f"  Launcher:      {launcher_path.name}{suffix}")


if __name__ == "__main__":
    main()

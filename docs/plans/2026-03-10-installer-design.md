# Installer Script Design

**Date:** 2026-03-10
**Status:** Approved

## Overview

`install.py` in the project root sets up the app for any machine after `git clone`. It detects the actual project location, updates `config.py`, finds the GnuCash database, generates a platform-appropriate launcher script, and optionally copies it to the desktop.

---

## Run Command

```
uv run python install.py
```

No extra dependencies — stdlib only (`pathlib`, `re`, `shutil`, `sys`, `subprocess`).

---

## Step 1: Detect Project Root

```python
PROJECT_ROOT = Path(__file__).parent.resolve()
```

Always correct regardless of where the repo was cloned.

---

## Step 2: Update `config.py`

Two regex replacements using the same lambda pattern as `POST /db/set-path`:

**Replace `PROJECT_ROOT`:**
```python
re.sub(
    r'(PROJECT_ROOT\s*=\s*Path\(r?)["\'].*?["\'](\))',
    lambda m: f'{m.group(1)}r"{project_root}"{m.group(2)}',
    config_text,
)
```

**Replace `GNUCASH_DB_PATH`:**
```python
re.sub(
    r'(GNUCASH_DB_PATH\s*=\s*Path\(r?)["\'].*?["\'](\))',
    lambda m: f'{m.group(1)}r"{db_path}"{m.group(2)}',
    config_text,
)
```

If either regex matches zero times, print an error and exit without writing.

---

## Step 3: Find the GnuCash Database

1. Search `Path.home() / "Documents"` recursively for `*.gnucash` files
2. Sort results by modification time, newest first
3. If none found: go straight to file picker (step 3c)
4. If found: print numbered list, e.g.:
   ```
   Found .gnucash files:
     1. C:\Users\Conrad\Documents\GnuCash\file.gnucash  (modified 2026-03-09)
     2. C:\Users\Conrad\Documents\old\backup.gnucash    (modified 2025-01-01)
     b. Browse for a different file...

   Enter number or 'b':
   ```
5. User picks a number → use that path
6. User types `b` → open tkinter `filedialog.askopenfilename` subprocess (same pattern as `GET /db/browse`)
7. File picker cancelled and no number chosen → print message and exit

---

## Step 4: Generate Launcher

Detect OS with `sys.platform`:

**Windows (`sys.platform == "win32"`)** — write `GnuCash Bills.bat`:
```bat
@echo off
title GnuCash Bills - Starting...
echo Starting GnuCash Bills server on port 7432...
start /min "GnuCash Bills Server" cmd /k "cd /d {project_root} && uv run uvicorn bill_processor.web.app:app --port 7432"
echo Waiting for server to start...
timeout /t 2 /nobreak >nul
echo Opening browser...
start http://localhost:7432
echo Done. Server is running in the background (minimized in taskbar).
echo Close the minimized console window to stop the server.
timeout /t 3 /nobreak >nul
```

**Linux/macOS (`sys.platform != "win32"`)** — write `GnuCash Bills.sh`:
```bash
#!/bin/bash
cd "{project_root}"
uv run uvicorn bill_processor.web.app:app --port 7432 &
sleep 2
xdg-open http://localhost:7432
```
Then: `os.chmod(launcher_path, 0o755)`

Launcher is written to the project root.

---

## Step 5: Desktop Copy

- Desktop path: `Path.home() / "Desktop"`
- If desktop folder does not exist: skip, tell user where the launcher file is
- If exists: prompt `Copy launcher to Desktop? [Y/n]`
- If file already on desktop: prompt `Overwrite existing file? [Y/n]`
- Copy with `shutil.copy2`

---

## Step 6: Summary

Print a concise summary:
```
Setup complete!
  Project root:  D:\wherever\GnuCash_bills_and_collections
  Database:      D:\...\CFSIV_Sqlite3_database.gnucash
  Launcher:      GnuCash Bills.bat  (also copied to Desktop)
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| `Documents` folder not found | Skip search, go straight to file picker |
| Search finds 0 files | Print notice, go to file picker |
| File picker cancelled, no number chosen | Print message, exit |
| Regex matches 0 times in `config.py` | Print error, exit without writing |
| Desktop folder not found | Skip copy, print launcher location |
| Desktop copy fails (permissions) | Print error, continue — config already saved |
| `chmod` fails on `.sh` | Print warning, continue |

---

## Out of Scope

- Auto-detecting GnuCash on drives other than the home drive
- Updating the `.env` file or any settings beyond `PROJECT_ROOT` and `GNUCASH_DB_PATH`
- Uninstaller

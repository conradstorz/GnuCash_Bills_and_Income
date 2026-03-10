# Desktop Launcher & DB Health Check Design

**Date:** 2026-03-10
**Status:** Approved

## Overview

A Windows `.bat` launcher on the desktop starts the FastAPI web server and opens the browser automatically. On every page load the server checks whether the GnuCash database is accessible. If it is not — whether missing or locked — the user sees a clear error page with full details, options to recover (browse for the file, refresh, or shut down the server).

---

## Component 1: Desktop Launcher (`GnuCash Bills.bat`)

A batch file placed on the Windows desktop (or copied there by the user).

**Behavior:**
1. Starts `uv run uvicorn bill_processor.web.app:app --port 7432` in a minimized console window (visible in taskbar, not in the way)
2. Waits 2 seconds for the server to bind
3. Opens `http://localhost:7432` in the default browser

**Why minimized (not hidden):** If the server crashes, the console shows the Python traceback. Fully hiding it would make debugging impossible.

```bat
@echo off
start /min "GnuCash Bills" cmd /c "cd /d D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections && uv run uvicorn bill_processor.web.app:app --port 7432"
timeout /t 2 /nobreak >nul
start http://localhost:7432
```

---

## Component 2: `check_db_health()` in `gnucash_db.py`

A new function that checks database accessibility before any render. Returns a dict:

```python
{
    "status": "ok" | "missing" | "locked",
    "message": str,       # Human-readable summary
    "path": str,          # Configured GNUCASH_DB_PATH
    "hostname": str,      # Lock holder hostname (locked case only)
    "pid": int,           # Lock holder PID (locked case only)
}
```

**Logic:**
1. Check `GNUCASH_DB_PATH.exists()` → if False: `status="missing"`
2. Call `is_locked_by_others()` → if locked: `status="locked"` with hostname/pid details
3. Otherwise: `status="ok"`

---

## Component 3: `GET /` route updated

Before building the dashboard context, call `check_db_health()`:
- `status == "ok"` → render `dashboard.html` as normal (no change to existing behavior)
- `status != "ok"` → render `db_unavailable.html` with the health dict as context

---

## Component 4: `web/templates/db_unavailable.html`

Simple, focused error page — no dashboard chrome, just the problem and recovery options.

```
┌─────────────────────────────────────────────┐
│  ⚠ Database Unavailable                      │
│                                             │
│  [specific error message]                   │
│  Path: D:\...\CFSIV_Sqlite3_database.gnucash│
│                                             │
│  IF MISSING:                                │
│    [Browse for database file…]              │
│                                             │
│  [↺ Refresh]        [⏻ Shut Down Server]    │
└─────────────────────────────────────────────┘
```

**Missing case message:** `"Database file not found at the configured path."`

**Locked case message:** `"Database is locked by {hostname} (PID {pid}). Close GnuCash and click Refresh."`

The **Browse** button is only shown in the `missing` case — it makes no sense when the file exists but is locked.

---

## Component 5: New Routes in `web/app.py`

### `GET /db/browse`

Spawns a subprocess to show a native Windows file picker:

```python
subprocess.run([sys.executable, "-c",
    "import tkinter as tk; from tkinter import filedialog; "
    "root = tk.Tk(); root.withdraw(); "
    "path = filedialog.askopenfilename("
    "  title='Select GnuCash database', "
    "  filetypes=[('GnuCash files', '*.gnucash'), ('All files', '*.*')]"
    "); print(path)"
], capture_output=True, text=True)
```

Returns `{"path": "D:\\...\\file.gnucash"}` or `{"path": ""}` if cancelled.

The browser (via HTMX or a small JS fetch) receives the path and populates a hidden form field, then auto-submits to `POST /db/set-path`.

### `POST /db/set-path`

Receives `new_path` from form data. Validates:
- Path is non-empty
- Path ends with `.gnucash`
- File exists at that path

If valid: edits `config.py` in place using regex to replace the `GNUCASH_DB_PATH` line, then redirects to `/`.

If invalid: re-renders `db_unavailable.html` with an additional `path_error` message.

**Regex used:**
```python
re.sub(
    r'(GNUCASH_DB_PATH\s*=\s*Path\(r?)["\'].*?["\'](\))',
    rf'\g<1>"{new_path_escaped}"\2',
    config_text
)
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| DB missing, user browses and picks valid file | Path written to config.py, redirect to `/`, dashboard loads |
| DB missing, user browses and cancels | No change, stays on error page |
| DB missing, picked file doesn't exist | Error shown below Browse button, stays on error page |
| DB locked, user clicks Refresh after closing GnuCash | Dashboard loads normally |
| Subprocess (tkinter) fails to launch | Returns `{"path": ""}`, treated as cancel |
| config.py write fails | Error shown on error page |

---

## Out of Scope

- Auto-detecting GnuCash database location (searching drives)
- Watching the DB file for changes while the server is running
- Multiple database profiles

# Desktop Launcher & DB Health Check Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Windows `.bat` desktop launcher and a DB health check that shows a detailed error page (with native file-picker recovery) when the GnuCash database is missing or locked.

**Architecture:** New `check_db_health()` in `gnucash_db.py` runs on every `GET /` — unhealthy state renders `db_unavailable.html` instead of the dashboard. Two new routes handle browse (subprocess tkinter dialog) and path persistence (regex-edit `config.py` + module reload). The launcher is a `.bat` file that starts the server minimized and opens the browser.

**Tech Stack:** Python 3.11, FastAPI, Jinja2, HTMX, tkinter (stdlib), subprocess, importlib, re, pytest

**Design doc:** `docs/plans/2026-03-10-desktop-launcher-design.md`

---

## CONTEXT — Read Before Every Task

- Package: `bill_processor`. All imports use `from bill_processor import ...`
- `config.GNUCASH_DB_PATH` is a `Path` object. Used as `Path(config.GNUCASH_DB_PATH)` in gnucash_db.py
- `is_locked_by_others()` returns `(bool, hostname_or_None, pid_or_None)`
- `get_connection()` raises `FileNotFoundError` if DB file missing
- Shutdown route already exists at `POST /shutdown` — returns `{"message": "..."}` and calls `os._exit(0)` after 1s
- `GET /` route is in `web/app.py`. It currently calls `gnucash_db.get_unpaid_bills()` and builds a template context
- Test pattern: `TestClient(app)` with `patch("bill_processor.gnucash_db.function_name")`
- `web/app.py` uses `templates.TemplateResponse(request, "template.html", context_dict)` (three-arg form)

---

## Task 1: Add `check_db_health()` to gnucash_db.py (TDD)

**Files:**
- Modify: `gnucash_db.py` (add function in CASH-ON-HAND OPERATIONS section or a new DB HEALTH section)
- Test: `tests/test_db_health.py`

**Step 1: Write failing tests**

Create `tests/test_db_health.py`:

```python
"""Tests for check_db_health() in gnucash_db.py."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from bill_processor import gnucash_db


class TestCheckDbHealth:
    def test_returns_ok_when_file_exists_and_not_locked(self, tmp_path):
        fake_db = tmp_path / "test.gnucash"
        fake_db.touch()
        with patch("bill_processor.config.GNUCASH_DB_PATH", fake_db), \
             patch("bill_processor.gnucash_db.is_locked_by_others", return_value=(False, None, None)):
            result = gnucash_db.check_db_health()
        assert result["status"] == "ok"
        assert result["path"] == str(fake_db)
        assert result["hostname"] is None
        assert result["pid"] is None

    def test_returns_missing_when_file_not_found(self, tmp_path):
        missing = tmp_path / "nonexistent.gnucash"
        with patch("bill_processor.config.GNUCASH_DB_PATH", missing):
            result = gnucash_db.check_db_health()
        assert result["status"] == "missing"
        assert result["path"] == str(missing)
        assert "not found" in result["message"].lower() or "missing" in result["message"].lower()

    def test_returns_locked_when_locked_by_others(self, tmp_path):
        fake_db = tmp_path / "test.gnucash"
        fake_db.touch()
        with patch("bill_processor.config.GNUCASH_DB_PATH", fake_db), \
             patch("bill_processor.gnucash_db.is_locked_by_others",
                   return_value=(True, "GnuCash@DESKTOP-XYZ", 4821)):
            result = gnucash_db.check_db_health()
        assert result["status"] == "locked"
        assert result["hostname"] == "GnuCash@DESKTOP-XYZ"
        assert result["pid"] == 4821
        assert "4821" in result["message"] or "DESKTOP-XYZ" in result["message"]

    def test_missing_check_does_not_call_lock_check(self, tmp_path):
        """Lock check should be skipped entirely when file is missing."""
        missing = tmp_path / "nonexistent.gnucash"
        with patch("bill_processor.config.GNUCASH_DB_PATH", missing), \
             patch("bill_processor.gnucash_db.is_locked_by_others") as mock_lock:
            gnucash_db.check_db_health()
        mock_lock.assert_not_called()

    def test_ok_result_contains_path(self, tmp_path):
        fake_db = tmp_path / "test.gnucash"
        fake_db.touch()
        with patch("bill_processor.config.GNUCASH_DB_PATH", fake_db), \
             patch("bill_processor.gnucash_db.is_locked_by_others", return_value=(False, None, None)):
            result = gnucash_db.check_db_health()
        assert "path" in result
        assert result["path"] == str(fake_db)
```

**Step 2: Run tests to confirm they fail**

```
pytest tests/test_db_health.py -v
```
Expected: `AttributeError: module 'bill_processor.gnucash_db' has no attribute 'check_db_health'`

**Step 3: Implement `check_db_health()` in gnucash_db.py**

Read `gnucash_db.py` first to find the right insertion point (after the existing CASH-ON-HAND section, before BILL/INVOICE OPERATIONS). Add:

```python
def check_db_health() -> dict:
    """Check whether the GnuCash database is accessible.

    Returns:
        dict with keys:
            status   : 'ok' | 'missing' | 'locked'
            message  : human-readable description
            path     : str — the configured GNUCASH_DB_PATH
            hostname : str | None — lock holder hostname (locked only)
            pid      : int | None — lock holder PID (locked only)
    """
    path = config.GNUCASH_DB_PATH

    if not Path(path).exists():
        return {
            "status": "missing",
            "message": "Database file not found at the configured path.",
            "path": str(path),
            "hostname": None,
            "pid": None,
        }

    locked, hostname, pid = is_locked_by_others()
    if locked:
        return {
            "status": "locked",
            "message": (
                f"Database is locked by {hostname} (PID {pid}). "
                "Close GnuCash and click Refresh."
            ),
            "path": str(path),
            "hostname": hostname,
            "pid": pid,
        }

    return {
        "status": "ok",
        "message": "Database is accessible.",
        "path": str(path),
        "hostname": None,
        "pid": None,
    }
```

**Step 4: Run tests**

```
pytest tests/test_db_health.py -v
```
Expected: 5/5 pass.

**Step 5: Run full suite to check regressions**

```
pytest tests/ -v
```
All previously passing tests must still pass.

**Step 6: Commit**

```bash
git add gnucash_db.py tests/test_db_health.py
git commit -m "feat: add check_db_health() to gnucash_db"
```

---

## Task 2: Create `db_unavailable.html` Template

**Files:**
- Create: `web/templates/db_unavailable.html`
- Read first: `web/templates/base.html` (understand block structure and CSS classes)

**Step 1: Read base.html**

Understand the `{% block content %}` block, CSS class names (`.card`, `.btn-primary`, `.btn-danger`, `.error-msg`), and how HTMX is available.

**Step 2: Create the template**

Create `web/templates/db_unavailable.html`:

```html
{% extends "base.html" %}
{% block content %}
<div class="card" style="max-width: 640px; margin: 2rem auto;">
  <h2 style="color: #c0392b;">&#9888; Database Unavailable</h2>

  <div class="error-msg" style="margin-top: 1rem;">
    <strong>{{ health.message }}</strong>
  </div>

  <table style="margin-top: 1rem; font-size: 0.9rem; width: 100%;">
    <tr>
      <td style="color: #555; padding: 0.2rem 0.5rem 0.2rem 0;">Status</td>
      <td><strong>{{ health.status | upper }}</strong></td>
    </tr>
    <tr>
      <td style="color: #555; padding: 0.2rem 0.5rem 0.2rem 0;">Configured path</td>
      <td style="word-break: break-all;"><code>{{ health.path }}</code></td>
    </tr>
    {% if health.hostname %}
    <tr>
      <td style="color: #555; padding: 0.2rem 0.5rem 0.2rem 0;">Locked by</td>
      <td><code>{{ health.hostname }}</code></td>
    </tr>
    <tr>
      <td style="color: #555; padding: 0.2rem 0.5rem 0.2rem 0;">Lock PID</td>
      <td><code>{{ health.pid }}</code></td>
    </tr>
    {% endif %}
  </table>

  {% if path_error %}
  <div class="error-msg" style="margin-top: 0.75rem;">{{ path_error }}</div>
  {% endif %}

  {% if health.status == "missing" %}
  <div style="margin-top: 1.5rem;">
    <p style="font-size: 0.9rem; color: #555; margin-bottom: 0.5rem;">
      Browse for the database file to update the configured path:
    </p>
    <button class="btn-primary"
            onclick="browseForDb(this)">
      Browse for database file&hellip;
    </button>
    <form id="set-path-form" method="post" action="/db/set-path" style="display:none">
      <input type="hidden" name="new_path" id="new-path-input">
    </form>
    <span id="browse-status" style="font-size:0.85rem; color:#555; margin-left:0.5rem;"></span>
  </div>

  <script>
  function browseForDb(btn) {
    btn.disabled = true;
    document.getElementById('browse-status').textContent = 'Opening file dialog\u2026';
    fetch('/db/browse')
      .then(r => r.json())
      .then(data => {
        if (data.path) {
          document.getElementById('new-path-input').value = data.path;
          document.getElementById('browse-status').textContent = 'Selected: ' + data.path;
          document.getElementById('set-path-form').submit();
        } else {
          document.getElementById('browse-status').textContent = 'No file selected.';
          btn.disabled = false;
        }
      })
      .catch(() => {
        document.getElementById('browse-status').textContent = 'Error opening dialog.';
        btn.disabled = false;
      });
  }
  </script>
  {% endif %}

  <div style="margin-top: 2rem; display: flex; gap: 1rem;">
    <a href="/" class="btn btn-primary">&#8635; Refresh</a>
    <form method="post" action="/shutdown" style="display:inline"
          onsubmit="this.querySelector('button').textContent='Shutting down\u2026'">
      <button type="submit" class="btn btn-danger">&#9211; Shut Down Server</button>
    </form>
  </div>
</div>
{% endblock %}
```

**Step 3: Verify Jinja2 parses the template**

```python
python -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('web/templates'))
env.get_template('db_unavailable.html')
print('OK')
"
```
Expected: `OK`

**Step 4: Commit**

```bash
git add web/templates/db_unavailable.html
git commit -m "feat: add db_unavailable error page template"
```

---

## Task 3: Update `GET /` to Use Health Check

**Files:**
- Modify: `web/app.py` (GET / route only)
- Test: `tests/test_db_health_web.py`

**Step 1: Write failing tests**

Create `tests/test_db_health_web.py`:

```python
"""Tests for DB health check integration in GET /."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from bill_processor.web.app import app

client = TestClient(app)

HEALTHY = {"status": "ok", "message": "OK", "path": "/fake/db.gnucash",
           "hostname": None, "pid": None}
MISSING = {"status": "missing",
           "message": "Database file not found at the configured path.",
           "path": "D:\\fake\\db.gnucash", "hostname": None, "pid": None}
LOCKED  = {"status": "locked",
           "message": "Database is locked by GnuCash@HOST (PID 999).",
           "path": "D:\\fake\\db.gnucash", "hostname": "GnuCash@HOST", "pid": 999}


class TestGetDashboardHealthCheck:
    def test_healthy_db_renders_dashboard(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=HEALTHY), \
             patch("bill_processor.gnucash_db.get_unpaid_bills", return_value=[]), \
             patch("bill_processor.gnucash_db.get_cash_accounts", return_value=[]), \
             patch("bill_processor.gnucash_db.get_checking_accounts", return_value=[]), \
             patch("bill_processor.gnucash_db.get_vendor_sync_status",
                   return_value={"status": "ok", "message": ""}):
            response = client.get("/")
        assert response.status_code == 200
        # Dashboard has the sync status card or cash entry panel — not the error page
        assert "Database Unavailable" not in response.text

    def test_missing_db_renders_error_page(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.get("/")
        assert response.status_code == 200
        assert "Database Unavailable" in response.text
        assert MISSING["path"] in response.text

    def test_locked_db_renders_error_page(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=LOCKED):
            response = client.get("/")
        assert response.status_code == 200
        assert "Database Unavailable" in response.text
        assert "GnuCash@HOST" in response.text
        assert "999" in response.text

    def test_missing_db_shows_browse_button(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.get("/")
        assert "Browse for database file" in response.text

    def test_locked_db_does_not_show_browse_button(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=LOCKED):
            response = client.get("/")
        assert "Browse for database file" not in response.text

    def test_error_page_has_refresh_link(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.get("/")
        assert "Refresh" in response.text

    def test_error_page_has_shutdown_button(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.get("/")
        assert "Shut Down" in response.text
```

**Step 2: Run tests to confirm they fail**

```
pytest tests/test_db_health_web.py -v
```
Expected: Most fail because `GET /` doesn't call `check_db_health()` yet.

**Step 3: Update `GET /` in web/app.py**

Read the current `GET /` handler. Add `check_db_health()` as the **first** thing in the handler, before any other DB calls:

```python
@app.get("/")
async def dashboard(request: Request):
    # --- DB health check (must be first) ---
    health = gnucash_db.check_db_health()
    if health["status"] != "ok":
        return templates.TemplateResponse(
            request, "db_unavailable.html", {"health": health}
        )

    # ... rest of existing handler unchanged ...
```

**Step 4: Run tests**

```
pytest tests/test_db_health_web.py -v
```
Expected: 7/7 pass.

**Step 5: Run full suite**

```
pytest tests/ -v
```
All previously passing tests must still pass. If the existing `GET /` tests in `test_web_app.py` or elsewhere now fail because they don't mock `check_db_health`, add the mock to those tests:
```python
patch("bill_processor.gnucash_db.check_db_health", return_value=HEALTHY)
```

**Step 6: Commit**

```bash
git add web/app.py tests/test_db_health_web.py
git commit -m "feat: check DB health on every GET / before rendering dashboard"
```

---

## Task 4: Add `GET /db/browse` Route

**Files:**
- Modify: `web/app.py`
- Test: `tests/test_db_health_web.py` (add to existing file)

**Step 1: Write failing test**

Add to `tests/test_db_health_web.py`:

```python
class TestDbBrowse:
    def test_returns_path_when_file_selected(self):
        mock_result = MagicMock()
        mock_result.stdout = "D:\\fake\\test.gnucash\n"
        mock_result.returncode = 0
        with patch("bill_processor.web.app.subprocess.run", return_value=mock_result):
            response = client.get("/db/browse")
        assert response.status_code == 200
        data = response.json()
        assert data["path"] == "D:\\fake\\test.gnucash"

    def test_returns_empty_path_when_cancelled(self):
        mock_result = MagicMock()
        mock_result.stdout = "\n"
        mock_result.returncode = 0
        with patch("bill_processor.web.app.subprocess.run", return_value=mock_result):
            response = client.get("/db/browse")
        assert response.status_code == 200
        assert response.json()["path"] == ""

    def test_returns_empty_path_on_subprocess_error(self):
        with patch("bill_processor.web.app.subprocess.run",
                   side_effect=Exception("subprocess failed")):
            response = client.get("/db/browse")
        assert response.status_code == 200
        assert response.json()["path"] == ""
```

Also add at the top of the test file: `from unittest.mock import patch, MagicMock` (check it's already there).

**Step 2: Run new tests to confirm they fail**

```
pytest tests/test_db_health_web.py::TestDbBrowse -v
```
Expected: `404` or `AttributeError` — route doesn't exist yet.

**Step 3: Add imports to web/app.py**

At the top of `web/app.py`, add these imports if not present:
```python
import sys
import subprocess
```

**Step 4: Add the route to web/app.py**

Add after the existing cash routes:

```python
# ---------------------------------------------------------------------------
# DB configuration routes
# ---------------------------------------------------------------------------

@app.get("/db/browse")
async def db_browse():
    """Open a native Windows file picker and return the selected path."""
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
                "); print(path)"
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        path = result.stdout.strip()
    except Exception:
        path = ""
    return {"path": path}
```

**Step 5: Run tests**

```
pytest tests/test_db_health_web.py::TestDbBrowse -v
```
Expected: 3/3 pass.

**Step 6: Commit**

```bash
git add web/app.py tests/test_db_health_web.py
git commit -m "feat: add GET /db/browse route for native file picker"
```

---

## Task 5: Add `POST /db/set-path` Route

**Files:**
- Modify: `web/app.py`
- Test: `tests/test_db_health_web.py` (add to existing file)

**Step 1: Write failing tests**

Add to `tests/test_db_health_web.py`:

```python
class TestDbSetPath:
    def test_valid_path_updates_config_and_redirects(self, tmp_path):
        # Create a fake .gnucash file
        fake_db = tmp_path / "real.gnucash"
        fake_db.touch()

        # Create a fake config.py with the GNUCASH_DB_PATH line
        fake_config = tmp_path / "config.py"
        fake_config.write_text(
            'GNUCASH_DB_PATH = Path(r"D:\\old\\path.gnucash")\n'
        )

        with patch("bill_processor.web.app.CONFIG_FILE_PATH", fake_config):
            response = client.post(
                "/db/set-path",
                data={"new_path": str(fake_db)},
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        # Config file was updated
        new_text = fake_config.read_text()
        assert str(fake_db) in new_text

    def test_empty_path_shows_error(self):
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.post("/db/set-path", data={"new_path": ""})
        assert response.status_code == 200
        assert "path_error" in response.text or "No path" in response.text

    def test_nonexistent_file_shows_error(self, tmp_path):
        missing = tmp_path / "nonexistent.gnucash"
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.post(
                "/db/set-path", data={"new_path": str(missing)}
            )
        assert response.status_code == 200
        assert "not found" in response.text.lower() or "does not exist" in response.text.lower()

    def test_wrong_extension_shows_error(self, tmp_path):
        wrong = tmp_path / "file.sqlite"
        wrong.touch()
        with patch("bill_processor.gnucash_db.check_db_health", return_value=MISSING):
            response = client.post(
                "/db/set-path", data={"new_path": str(wrong)}
            )
        assert response.status_code == 200
        assert "gnucash" in response.text.lower()
```

**Step 2: Run new tests to confirm they fail**

```
pytest tests/test_db_health_web.py::TestDbSetPath -v
```
Expected: 404 or AttributeError — route doesn't exist yet.

**Step 3: Add `CONFIG_FILE_PATH` constant to web/app.py**

Near the top of `web/app.py`, after imports, add:

```python
# Path to config.py — used by POST /db/set-path to update GNUCASH_DB_PATH
CONFIG_FILE_PATH = Path(__file__).parent.parent / "config.py"
```

Add `from pathlib import Path` if not already imported.

**Step 4: Add the route to web/app.py**

Add after `GET /db/browse`:

```python
@app.post("/db/set-path")
async def db_set_path(request: Request):
    """Write a new GNUCASH_DB_PATH to config.py and reload config."""
    import re
    import importlib
    from fastapi.responses import RedirectResponse
    from bill_processor import config as cfg

    form = await request.form()
    new_path = (form.get("new_path") or "").strip()

    def _error(msg: str):
        health = gnucash_db.check_db_health()
        return templates.TemplateResponse(
            request, "db_unavailable.html",
            {"health": health, "path_error": msg}
        )

    if not new_path:
        return _error("No path provided.")

    if not new_path.lower().endswith(".gnucash"):
        return _error("File must have a .gnucash extension.")

    if not Path(new_path).exists():
        return _error(f"File not found: {new_path}")

    # Update config.py in place
    config_text = CONFIG_FILE_PATH.read_text(encoding="utf-8")
    # Escape backslashes for the replacement string (Windows paths)
    safe_path = new_path.replace("\\", "\\\\")
    new_text, count = re.subn(
        r'(GNUCASH_DB_PATH\s*=\s*Path\(r?)["\'].*?["\'](\))',
        rf'\g<1>r"{new_path}"\g<2>',
        config_text,
    )
    if count == 0:
        return _error("Could not update config.py — GNUCASH_DB_PATH line not found.")

    CONFIG_FILE_PATH.write_text(new_text, encoding="utf-8")

    # Reload config so the running server picks up the change immediately
    importlib.reload(cfg)

    return RedirectResponse(url="/", status_code=303)
```

**Step 5: Run tests**

```
pytest tests/test_db_health_web.py::TestDbSetPath -v
```
Expected: 4/4 pass.

**Step 6: Run full test suite**

```
pytest tests/ -v
```
All tests must pass.

**Step 7: Commit**

```bash
git add web/app.py tests/test_db_health_web.py
git commit -m "feat: add POST /db/set-path to update GNUCASH_DB_PATH in config.py"
```

---

## Task 6: Create the Desktop `.bat` Launcher

**Files:**
- Create: `GnuCash Bills.bat` (in the repo root — user copies to desktop)

**Step 1: Read config.py to confirm the project root path**

The batch file needs the absolute path to the project. Confirm it is:
`D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections`

**Step 2: Create `GnuCash Bills.bat`**

```bat
@echo off
title GnuCash Bills - Starting...
echo Starting GnuCash Bills server on port 7432...
start /min "GnuCash Bills Server" cmd /k "cd /d D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections && uv run uvicorn bill_processor.web.app:app --port 7432"
echo Waiting for server to start...
timeout /t 2 /nobreak >nul
echo Opening browser...
start http://localhost:7432
echo Done. Server is running in the background (minimized in taskbar).
echo Close the minimized console window to stop the server.
timeout /t 3 /nobreak >nul
```

Note: `cmd /k` (not `cmd /c`) keeps the console open so errors are visible. `/min` starts it minimized.

**Step 3: Manually test the launcher**

Double-click `GnuCash Bills.bat`. Verify:
1. A minimized window appears in the taskbar labeled "GnuCash Bills Server"
2. Browser opens to `http://localhost:7432`
3. Dashboard loads (or DB unavailable page if DB not accessible)
4. Closing the minimized window stops the server

**Step 4: Add .bat to .gitignore? No — commit it.**

The `.bat` file contains the project path which is already in `config.py` and `CLAUDE.md`. It's useful to have in the repo.

**Step 5: Commit**

```bash
git add "GnuCash Bills.bat"
git commit -m "feat: add desktop launcher batch file"
```

---

## Task 7: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Read current CLAUDE.md**

**Step 2: Add launcher info and new routes**

In the Commands section, update the web dashboard entry:
```markdown
# Web dashboard
uv run uvicorn bill_processor.web.app:app --reload --port 7432
# Or double-click GnuCash Bills.bat (desktop launcher)
# Access at http://localhost:7432
```

In the Architecture section, add to the new web routes table:
```
| GET /db/browse    | Opens native Windows file picker, returns selected path |
| POST /db/set-path | Writes new GNUCASH_DB_PATH to config.py, reloads config  |
```

Note the health check behavior:
```markdown
**DB health check:** `GET /` calls `check_db_health()` before rendering. If the database is missing or locked, renders `db_unavailable.html` with full details and recovery options (browse for file, refresh, shut down).
```

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with launcher and DB health check info"
```

---

## Task 8: Push to GitHub

```bash
git push origin master
```

Verify at `https://github.com/conradstorz/GnuCash_Bills_and_Income` that all commits are present.

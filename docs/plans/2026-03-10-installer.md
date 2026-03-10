# Installer Script Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `install.py` — a cross-platform setup script that updates `config.py` with the real project root and GnuCash DB path, generates a platform-appropriate launcher, and optionally copies it to the desktop.

**Architecture:** Single standalone script at the project root with six pure/testable helper functions and a `main()` that wires them together. All interactive I/O is isolated in `pick_gnucash_file()`, `copy_to_desktop()`, and `main()` — making all logic functions unit-testable by mocking `input()` and `subprocess.run`. Uses same regex-lambda pattern as `POST /db/set-path` for config edits.

**Tech Stack:** Python 3.11 stdlib only — `pathlib`, `re`, `shutil`, `os`, `sys`, `subprocess`, `datetime`. pytest for tests.

---

## CONTEXT — Read Before Every Task

- Package root: `D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections`
- `install.py` goes in the **project root** (not inside `bill_processor/`)
- Tests go in `tests/test_installer.py`
- Run tests: `uv run pytest tests/test_installer.py -v`
- Run full suite: `uv run pytest tests/ -v`
- `config.py` is in the project root — it has `PROJECT_ROOT = Path(r"...")` and `GNUCASH_DB_PATH = Path(r"...")`
- The regex-lambda pattern for config edits (from `web/app.py`):
  ```python
  re.subn(
      r'(GNUCASH_DB_PATH\s*=\s*Path\(r?)["\'].*?["\'](\))',
      lambda m: f'{m.group(1)}r"{new_path}"{m.group(2)}',
      config_text,
  )
  ```
  Use the same approach for `PROJECT_ROOT`.
- `sys.platform == "win32"` for Windows detection
- tkinter file picker subprocess (same as `GET /db/browse` in `web/app.py`):
  ```python
  subprocess.run(
      [sys.executable, "-c",
       "import tkinter as tk; from tkinter import filedialog; "
       "root = tk.Tk(); root.withdraw(); "
       "root.wm_attributes('-topmost', 1); "
       "path = filedialog.askopenfilename("
       "    title='Select GnuCash database file',"
       "    filetypes=[('GnuCash files', '*.gnucash'), ('All files', '*.*')]"
       "); print(path)"],
      capture_output=True, text=True, timeout=120,
  )
  ```

---

## Task 1: `update_config()` Function (TDD)

**Files:**
- Create: `install.py`
- Create: `tests/test_installer.py`

**Step 1: Write failing tests**

Create `tests/test_installer.py`:

```python
"""Tests for install.py installer functions."""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# install.py is at the project root, not inside a package
import importlib.util, os
_spec = importlib.util.spec_from_file_location(
    "install",
    Path(__file__).parent.parent / "install.py",
)
install = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(install)


class TestUpdateConfig:
    def _make_config(self, tmp_path: Path) -> Path:
        cfg = tmp_path / "config.py"
        cfg.write_text(
            'PROJECT_ROOT = Path(r"D:\\old\\project")\n'
            'GNUCASH_DB_PATH = Path(r"D:\\old\\db.gnucash")\n',
            encoding="utf-8",
        )
        return cfg

    def test_updates_project_root(self, tmp_path):
        cfg = self._make_config(tmp_path)
        new_root = Path(r"C:\new\project")
        install.update_config(cfg, new_root, Path(r"D:\old\db.gnucash"))
        text = cfg.read_text(encoding="utf-8")
        assert str(new_root) in text

    def test_updates_db_path(self, tmp_path):
        cfg = self._make_config(tmp_path)
        new_db = Path(r"C:\data\my.gnucash")
        install.update_config(cfg, Path(r"D:\old\project"), new_db)
        text = cfg.read_text(encoding="utf-8")
        assert str(new_db) in text

    def test_updates_both_in_one_call(self, tmp_path):
        cfg = self._make_config(tmp_path)
        new_root = Path(r"C:\new\project")
        new_db = Path(r"C:\data\my.gnucash")
        install.update_config(cfg, new_root, new_db)
        text = cfg.read_text(encoding="utf-8")
        assert str(new_root) in text
        assert str(new_db) in text

    def test_raises_if_project_root_pattern_missing(self, tmp_path):
        cfg = tmp_path / "config.py"
        cfg.write_text("# no paths here\n", encoding="utf-8")
        with pytest.raises(ValueError, match="PROJECT_ROOT"):
            install.update_config(cfg, Path(r"C:\x"), Path(r"C:\x\db.gnucash"))

    def test_raises_if_db_path_pattern_missing(self, tmp_path):
        cfg = tmp_path / "config.py"
        cfg.write_text('PROJECT_ROOT = Path(r"D:\\old")\n', encoding="utf-8")
        with pytest.raises(ValueError, match="GNUCASH_DB_PATH"):
            install.update_config(cfg, Path(r"C:\x"), Path(r"C:\x\db.gnucash"))

    def test_does_not_write_on_error(self, tmp_path):
        cfg = tmp_path / "config.py"
        original = "# no paths here\n"
        cfg.write_text(original, encoding="utf-8")
        with pytest.raises(ValueError):
            install.update_config(cfg, Path(r"C:\x"), Path(r"C:\x\db.gnucash"))
        assert cfg.read_text(encoding="utf-8") == original
```

**Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_installer.py::TestUpdateConfig -v
```
Expected: `ModuleNotFoundError` or `AttributeError` — `install.py` doesn't exist yet.

**Step 3: Create `install.py` with `update_config()`**

Create `install.py` in the project root:

```python
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
```

**Step 4: Run tests**

```
uv run pytest tests/test_installer.py::TestUpdateConfig -v
```
Expected: 6/6 pass.

**Step 5: Commit**

```bash
git add install.py tests/test_installer.py
git commit -m "feat: add install.py with update_config()"
```

---

## Task 2: `search_for_gnucash()` Function (TDD)

**Files:**
- Modify: `install.py`
- Modify: `tests/test_installer.py`

**Step 1: Write failing tests**

Add to `tests/test_installer.py`:

```python
class TestSearchForGnucash:
    def test_finds_gnucash_files(self, tmp_path):
        (tmp_path / "a.gnucash").touch()
        (tmp_path / "b.gnucash").touch()
        results = install.search_for_gnucash(tmp_path)
        assert len(results) == 2

    def test_ignores_non_gnucash_files(self, tmp_path):
        (tmp_path / "a.gnucash").touch()
        (tmp_path / "b.sqlite").touch()
        results = install.search_for_gnucash(tmp_path)
        assert len(results) == 1

    def test_searches_subdirectories(self, tmp_path):
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)
        (sub / "nested.gnucash").touch()
        results = install.search_for_gnucash(tmp_path)
        assert len(results) == 1
        assert results[0].name == "nested.gnucash"

    def test_returns_empty_for_missing_directory(self, tmp_path):
        results = install.search_for_gnucash(tmp_path / "nonexistent")
        assert results == []

    def test_sorts_newest_first(self, tmp_path):
        import time
        old = tmp_path / "old.gnucash"
        old.touch()
        time.sleep(0.05)
        new = tmp_path / "new.gnucash"
        new.touch()
        results = install.search_for_gnucash(tmp_path)
        assert results[0].name == "new.gnucash"
        assert results[1].name == "old.gnucash"
```

**Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_installer.py::TestSearchForGnucash -v
```
Expected: `AttributeError: module 'install' has no attribute 'search_for_gnucash'`

**Step 3: Add `search_for_gnucash()` to `install.py`**

Add after `update_config()`:

```python
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
```

**Step 4: Run tests**

```
uv run pytest tests/test_installer.py::TestSearchForGnucash -v
```
Expected: 5/5 pass.

**Step 5: Commit**

```bash
git add install.py tests/test_installer.py
git commit -m "feat: add search_for_gnucash() to install.py"
```

---

## Task 3: `open_file_picker()` and `pick_gnucash_file()` (TDD)

**Files:**
- Modify: `install.py`
- Modify: `tests/test_installer.py`

**Step 1: Write failing tests**

Add to `tests/test_installer.py`:

```python
class TestOpenFilePicker:
    def test_returns_path_when_file_selected(self):
        mock_result = MagicMock()
        mock_result.stdout = "C:\\fake\\test.gnucash\n"
        with patch("subprocess.run", return_value=mock_result):
            result = install.open_file_picker()
        assert result == Path("C:\\fake\\test.gnucash")

    def test_returns_none_when_cancelled(self):
        mock_result = MagicMock()
        mock_result.stdout = "\n"
        with patch("subprocess.run", return_value=mock_result):
            result = install.open_file_picker()
        assert result is None

    def test_returns_none_on_subprocess_error(self):
        with patch("subprocess.run", side_effect=Exception("fail")):
            result = install.open_file_picker()
        assert result is None


class TestPickGnucashFile:
    def _make_files(self, tmp_path):
        f1 = tmp_path / "a.gnucash"
        f2 = tmp_path / "b.gnucash"
        f1.touch()
        f2.touch()
        return [f1, f2]

    def test_numeric_choice_returns_candidate(self, tmp_path):
        files = self._make_files(tmp_path)
        with patch("builtins.input", return_value="1"):
            result = install.pick_gnucash_file(files)
        assert result == files[0]

    def test_b_choice_opens_file_picker(self, tmp_path):
        files = self._make_files(tmp_path)
        picked = tmp_path / "chosen.gnucash"
        picked.touch()
        with patch("builtins.input", return_value="b"), \
             patch.object(install, "open_file_picker", return_value=picked):
            result = install.pick_gnucash_file(files)
        assert result == picked

    def test_invalid_then_valid_choice(self, tmp_path):
        files = self._make_files(tmp_path)
        with patch("builtins.input", side_effect=["99", "abc", "2"]):
            result = install.pick_gnucash_file(files)
        assert result == files[1]

    def test_empty_candidates_goes_to_picker(self, tmp_path):
        picked = tmp_path / "found.gnucash"
        picked.touch()
        with patch("builtins.input", return_value=""), \
             patch.object(install, "open_file_picker", return_value=picked):
            result = install.pick_gnucash_file([])
        assert result == picked

    def test_quit_returns_none_when_no_candidates(self):
        with patch("builtins.input", return_value="q"):
            result = install.pick_gnucash_file([])
        assert result is None
```

**Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_installer.py::TestOpenFilePicker tests/test_installer.py::TestPickGnucashFile -v
```
Expected: `AttributeError` — functions don't exist yet.

**Step 3: Add both functions to `install.py`**

Add after `search_for_gnucash()`:

```python
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
```

**Step 4: Run tests**

```
uv run pytest tests/test_installer.py::TestOpenFilePicker tests/test_installer.py::TestPickGnucashFile -v
```
Expected: 8/8 pass.

**Step 5: Commit**

```bash
git add install.py tests/test_installer.py
git commit -m "feat: add open_file_picker() and pick_gnucash_file() to install.py"
```

---

## Task 4: `generate_launcher()` Function (TDD)

**Files:**
- Modify: `install.py`
- Modify: `tests/test_installer.py`

**Step 1: Write failing tests**

Add to `tests/test_installer.py`:

```python
class TestGenerateLauncher:
    def test_windows_generates_bat_file(self, tmp_path):
        with patch("sys.platform", "win32"):
            launcher = install.generate_launcher(tmp_path)
        assert launcher.name == "GnuCash Bills.bat"
        assert launcher.exists()
        content = launcher.read_text(encoding="utf-8")
        assert str(tmp_path) in content
        assert "uvicorn" in content
        assert "7432" in content

    def test_linux_generates_sh_file(self, tmp_path):
        with patch("sys.platform", "linux"):
            with patch("os.chmod"):
                launcher = install.generate_launcher(tmp_path)
        assert launcher.name == "GnuCash Bills.sh"
        assert launcher.exists()
        content = launcher.read_text(encoding="utf-8")
        assert "#!/bin/bash" in content
        assert str(tmp_path) in content
        assert "uvicorn" in content

    def test_linux_sets_executable_bit(self, tmp_path):
        with patch("sys.platform", "linux"):
            with patch("os.chmod") as mock_chmod:
                launcher = install.generate_launcher(tmp_path)
        mock_chmod.assert_called_once_with(launcher, 0o755)

    def test_windows_does_not_chmod(self, tmp_path):
        with patch("sys.platform", "win32"):
            with patch("os.chmod") as mock_chmod:
                install.generate_launcher(tmp_path)
        mock_chmod.assert_not_called()

    def test_project_root_embedded_in_bat(self, tmp_path):
        project = tmp_path / "my_project"
        project.mkdir()
        with patch("sys.platform", "win32"):
            launcher = install.generate_launcher(project)
        content = launcher.read_text(encoding="utf-8")
        assert str(project) in content
```

**Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_installer.py::TestGenerateLauncher -v
```
Expected: `AttributeError` — function doesn't exist yet.

**Step 3: Add `generate_launcher()` to `install.py`**

Add after `pick_gnucash_file()`:

```python
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
```

**Step 4: Run tests**

```
uv run pytest tests/test_installer.py::TestGenerateLauncher -v
```
Expected: 5/5 pass.

**Step 5: Commit**

```bash
git add install.py tests/test_installer.py
git commit -m "feat: add generate_launcher() to install.py"
```

---

## Task 5: `copy_to_desktop()` Function (TDD)

**Files:**
- Modify: `install.py`
- Modify: `tests/test_installer.py`

**Step 1: Write failing tests**

Add to `tests/test_installer.py`:

```python
class TestCopyToDesktop:
    def test_copies_when_user_confirms(self, tmp_path):
        launcher = tmp_path / "GnuCash Bills.bat"
        launcher.write_text("@echo off\n", encoding="utf-8")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        with patch("builtins.input", return_value="y"), \
             patch.object(install.Path, "home", return_value=tmp_path):
            result = install.copy_to_desktop(launcher)
        assert result is True
        assert (desktop / "GnuCash Bills.bat").exists()

    def test_skips_when_user_declines(self, tmp_path):
        launcher = tmp_path / "GnuCash Bills.bat"
        launcher.write_text("@echo off\n", encoding="utf-8")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        with patch("builtins.input", return_value="n"), \
             patch.object(install.Path, "home", return_value=tmp_path):
            result = install.copy_to_desktop(launcher)
        assert result is False
        assert not (desktop / "GnuCash Bills.bat").exists()

    def test_returns_false_when_desktop_missing(self, tmp_path):
        launcher = tmp_path / "GnuCash Bills.bat"
        launcher.write_text("@echo off\n", encoding="utf-8")
        # No Desktop subfolder created
        with patch.object(install.Path, "home", return_value=tmp_path):
            result = install.copy_to_desktop(launcher)
        assert result is False

    def test_prompts_before_overwrite(self, tmp_path):
        launcher = tmp_path / "GnuCash Bills.bat"
        launcher.write_text("new content\n", encoding="utf-8")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        existing = desktop / "GnuCash Bills.bat"
        existing.write_text("old content\n", encoding="utf-8")
        with patch("builtins.input", return_value="y"), \
             patch.object(install.Path, "home", return_value=tmp_path):
            result = install.copy_to_desktop(launcher)
        assert result is True
        assert existing.read_text(encoding="utf-8") == "new content\n"
```

**Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_installer.py::TestCopyToDesktop -v
```
Expected: `AttributeError` — function doesn't exist yet.

**Step 3: Add `copy_to_desktop()` to `install.py`**

Add after `generate_launcher()`:

```python
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
        answer = input(
            f"\n'{launcher_path.name}' already exists on Desktop. Overwrite? [Y/n]: "
        ).strip().lower()
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
```

**Step 4: Run tests**

```
uv run pytest tests/test_installer.py::TestCopyToDesktop -v
```
Expected: 4/4 pass.

**Step 5: Commit**

```bash
git add install.py tests/test_installer.py
git commit -m "feat: add copy_to_desktop() to install.py"
```

---

## Task 6: `main()` + Wire Everything Together (TDD)

**Files:**
- Modify: `install.py`
- Modify: `tests/test_installer.py`

**Step 1: Write failing tests**

Add to `tests/test_installer.py`:

```python
class TestMain:
    def _make_config(self, tmp_path: Path) -> Path:
        cfg = tmp_path / "config.py"
        cfg.write_text(
            'PROJECT_ROOT = Path(r"D:\\old\\project")\n'
            'GNUCASH_DB_PATH = Path(r"D:\\old\\db.gnucash")\n',
            encoding="utf-8",
        )
        return cfg

    def test_full_flow_updates_config_and_generates_launcher(self, tmp_path):
        cfg = self._make_config(tmp_path)
        fake_db = tmp_path / "real.gnucash"
        fake_db.touch()
        desktop = tmp_path / "Desktop"
        desktop.mkdir()

        with patch.object(install, "search_for_gnucash", return_value=[fake_db]), \
             patch.object(install, "pick_gnucash_file", return_value=fake_db), \
             patch.object(install, "copy_to_desktop", return_value=True), \
             patch("sys.platform", "win32"), \
             patch.object(install.Path, "resolve", return_value=tmp_path), \
             patch.object(install.Path, "home", return_value=tmp_path):
            install.main(config_path=cfg, project_root=tmp_path)

        text = cfg.read_text(encoding="utf-8")
        assert str(tmp_path) in text
        assert str(fake_db) in text

    def test_exits_gracefully_when_no_db_selected(self, tmp_path, capsys):
        cfg = self._make_config(tmp_path)
        with patch.object(install, "search_for_gnucash", return_value=[]), \
             patch.object(install, "pick_gnucash_file", return_value=None), \
             patch.object(install.Path, "resolve", return_value=tmp_path):
            install.main(config_path=cfg, project_root=tmp_path)
        captured = capsys.readouterr()
        assert "No database selected" in captured.out or "Exiting" in captured.out
```

**Step 2: Run tests to confirm they fail**

```
uv run pytest tests/test_installer.py::TestMain -v
```
Expected: `AttributeError` — `main()` doesn't accept parameters yet.

**Step 3: Replace the stub `if __name__ == "__main__"` block with full `main()`**

Replace the existing `if __name__ == "__main__": print(...)` at the bottom of `install.py` with:

```python
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
```

**Step 4: Run tests**

```
uv run pytest tests/test_installer.py::TestMain -v
```
Expected: 2/2 pass.

**Step 5: Run full installer test suite**

```
uv run pytest tests/test_installer.py -v
```
Expected: all pass (should be 25+ tests across all classes).

**Step 6: Run full project test suite**

```
uv run pytest tests/ -v
```
All previously passing tests must still pass.

**Step 7: Commit**

```bash
git add install.py tests/test_installer.py
git commit -m "feat: complete install.py with main() and full test suite"
```

---

## Task 7: Update CLAUDE.md and Push

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Read current CLAUDE.md**

Find the Commands section. Add after the existing web dashboard lines:

```markdown
# First-time setup (after git clone)
uv run python install.py
# Searches Documents for .gnucash files, updates config.py, generates launcher
```

**Step 2: Commit and push**

```bash
git add CLAUDE.md
git commit -m "docs: add install.py usage to CLAUDE.md"
git push origin master
```

Verify push succeeds. Report the SHA and push output.

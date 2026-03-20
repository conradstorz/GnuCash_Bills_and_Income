"""Tests for install.py installer functions."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# install.py is at the project root, not inside a package — load it directly
import importlib.util
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

    def test_copies_when_user_confirms_yes(self, tmp_path):
        launcher = tmp_path / "GnuCash Bills.bat"
        launcher.write_text("@echo off\n", encoding="utf-8")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        with patch("builtins.input", return_value="yes"), \
             patch.object(install.Path, "home", return_value=tmp_path):
            result = install.copy_to_desktop(launcher)
        assert result is True
        assert (desktop / "GnuCash Bills.bat").exists()

    def test_copies_when_user_confirms_empty_string(self, tmp_path):
        launcher = tmp_path / "GnuCash Bills.bat"
        launcher.write_text("@echo off\n", encoding="utf-8")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        with patch("builtins.input", return_value=""), \
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

    def test_returns_false_when_desktop_missing(self, tmp_path, caplog):
        launcher = tmp_path / "GnuCash Bills.bat"
        launcher.write_text("@echo off\n", encoding="utf-8")
        # No Desktop subfolder created
        with patch.object(install.Path, "home", return_value=tmp_path):
            result = install.copy_to_desktop(launcher)
        assert result is False
        assert str(launcher) in caplog.text

    def test_returns_false_on_copy_error(self, tmp_path, caplog):
        launcher = tmp_path / "GnuCash Bills.bat"
        launcher.write_text("@echo off\n", encoding="utf-8")
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        with patch("builtins.input", return_value="y"), \
             patch.object(install.Path, "home", return_value=tmp_path), \
             patch("shutil.copy2", side_effect=OSError("Permission denied")):
            result = install.copy_to_desktop(launcher)
        assert result is False
        assert "Permission denied" in caplog.text

    def test_prompts_before_overwrite(self, tmp_path, capsys):
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
        captured = capsys.readouterr()
        assert "already exists" in captured.out or "Overwrite" in captured.out


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

    def test_exits_gracefully_when_no_db_selected(self, tmp_path, capfd):
        # Uses capfd (not caplog): install.main() calls logger.remove() internally,
        # which strips the pytest-loguru caplog handler before the log is emitted.
        # capfd captures stderr at the fd level, bypassing loguru handler management.
        cfg = self._make_config(tmp_path)
        with patch.object(install, "search_for_gnucash", return_value=[]), \
             patch.object(install, "pick_gnucash_file", return_value=None), \
             patch.object(install.Path, "resolve", return_value=tmp_path):
            install.main(config_path=cfg, project_root=tmp_path)
        captured = capfd.readouterr()
        assert "No database selected" in captured.err or "Exiting" in captured.err

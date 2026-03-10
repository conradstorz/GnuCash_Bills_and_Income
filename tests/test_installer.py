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

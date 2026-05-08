"""Tests for web/queue_io.py — bill queue file I/O."""
import pytest
from datetime import date
from pathlib import Path

from bill_processor import config
from bill_processor.web import queue_io


@pytest.fixture
def queue_path(tmp_path, monkeypatch):
    path = tmp_path / "bills_to_process.txt"
    monkeypatch.setattr(config, "BILLS_INPUT_PATH", path)
    return path


class TestReadQueue:
    def test_missing_file_returns_empty_list(self, queue_path):
        assert queue_io.read_queue() == []

    def test_empty_file_returns_empty_list(self, queue_path):
        queue_path.write_text("")
        assert queue_io.read_queue() == []

    def test_single_bill_parsed(self, queue_path):
        queue_path.write_text("Acme Corp, 100.00, supplies, 2026-01-15\n")
        result = queue_io.read_queue()
        assert len(result) == 1
        assert result[0]["vendor_name"] == "Acme Corp"
        assert result[0]["amount"] == 100.00
        assert result[0]["memo"] == "supplies"
        assert result[0]["date"] == date(2026, 1, 15)
        assert result[0]["_index"] == 0

    def test_bill_with_check_number_parsed(self, queue_path):
        queue_path.write_text("Acme Corp, 100.00, supplies, 2026-01-15, 1234\n")
        result = queue_io.read_queue()
        assert result[0]["check_number"] == "1234"

    def test_bill_without_check_number_has_empty_string(self, queue_path):
        queue_path.write_text("Acme Corp, 100.00, supplies, 2026-01-15\n")
        result = queue_io.read_queue()
        assert result[0]["check_number"] == ""

    def test_malformed_lines_skipped(self, queue_path):
        queue_path.write_text("bad line\nAcme Corp, 100.00, supplies, 2026-01-15\n")
        result = queue_io.read_queue()
        assert len(result) == 1

    def test_index_reflects_file_line_position(self, queue_path):
        queue_path.write_text(
            "bad line\n"
            "Acme Corp, 100.00, supplies, 2026-01-15\n"
        )
        result = queue_io.read_queue()
        assert result[0]["_index"] == 1

    def test_multiple_bills_all_parsed(self, queue_path):
        queue_path.write_text(
            "Acme Corp, 100.00, supplies, 2026-01-15\n"
            "Bob Plumbing, 200.00, repair, 2026-02-01\n"
        )
        result = queue_io.read_queue()
        assert len(result) == 2
        assert result[0]["vendor_name"] == "Acme Corp"
        assert result[1]["vendor_name"] == "Bob Plumbing"
        assert result[0]["_index"] == 0
        assert result[1]["_index"] == 1


class TestAddBill:
    def test_appends_bill_line(self, queue_path):
        queue_io.add_bill("Acme Corp", 100.0, "supplies", date(2026, 1, 15))
        line = queue_path.read_text().strip()
        assert line == "Acme Corp, 100.00, supplies, 2026-01-15"

    def test_check_number_included_when_provided(self, queue_path):
        queue_io.add_bill("Acme Corp", 100.0, "supplies", date(2026, 1, 15), "1234")
        line = queue_path.read_text().strip()
        assert line == "Acme Corp, 100.00, supplies, 2026-01-15, 1234"

    def test_check_number_omitted_when_empty(self, queue_path):
        queue_io.add_bill("Acme Corp", 100.0, "supplies", date(2026, 1, 15), "")
        line = queue_path.read_text().strip()
        assert line == "Acme Corp, 100.00, supplies, 2026-01-15"

    def test_creates_file_if_missing(self, queue_path):
        assert not queue_path.exists()
        queue_io.add_bill("Acme Corp", 100.0, "supplies", date(2026, 1, 15))
        assert queue_path.exists()

    def test_appends_to_existing_file(self, queue_path):
        queue_path.write_text("Acme Corp, 100.00, supplies, 2026-01-15\n")
        queue_io.add_bill("Bob Plumbing", 200.0, "repair", date(2026, 2, 1))
        lines = [line for line in queue_path.read_text().splitlines() if line.strip()]
        assert len(lines) == 2


class TestRemoveBill:
    def test_removes_correct_line(self, queue_path):
        queue_path.write_text(
            "Acme Corp, 100.00, supplies, 2026-01-15\n"
            "Bob Plumbing, 200.00, repair, 2026-02-01\n"
        )
        result = queue_io.remove_bill(0)
        assert result is True
        assert "Acme Corp" not in queue_path.read_text()
        assert "Bob Plumbing" in queue_path.read_text()

    def test_preserves_other_lines(self, queue_path):
        queue_path.write_text(
            "A, 10.00, m, 2026-01-01\n"
            "B, 20.00, m, 2026-01-02\n"
            "C, 30.00, m, 2026-01-03\n"
        )
        queue_io.remove_bill(1)
        remaining = [line for line in queue_path.read_text().splitlines() if line.strip()]
        assert len(remaining) == 2
        assert any("A" in line for line in remaining)
        assert any("C" in line for line in remaining)

    def test_returns_false_on_out_of_range_index(self, queue_path):
        queue_path.write_text("A, 10.00, m, 2026-01-01\n")
        assert queue_io.remove_bill(5) is False

    def test_returns_false_on_negative_index(self, queue_path):
        queue_path.write_text("A, 10.00, m, 2026-01-01\n")
        assert queue_io.remove_bill(-1) is False


class TestUpdateBill:
    def test_replaces_correct_line(self, queue_path):
        queue_path.write_text("Old Corp, 50.00, old memo, 2026-01-01\n")
        result = queue_io.update_bill(0, "New Corp", 99.99, "new memo", date(2026, 6, 15))
        assert result is True
        assert queue_path.read_text().strip() == "New Corp, 99.99, new memo, 2026-06-15"

    def test_preserves_other_lines(self, queue_path):
        queue_path.write_text(
            "A, 10.00, m, 2026-01-01\n"
            "B, 20.00, m, 2026-01-02\n"
        )
        queue_io.update_bill(0, "Updated", 15.00, "m", date(2026, 1, 1))
        lines = [line for line in queue_path.read_text().splitlines() if line.strip()]
        assert len(lines) == 2
        assert "B" in lines[1]

    def test_returns_false_on_out_of_range(self, queue_path):
        queue_path.write_text("A, 10.00, m, 2026-01-01\n")
        assert queue_io.update_bill(5, "B", 20.0, "m", date(2026, 1, 1)) is False

    def test_check_number_roundtrip(self, queue_path):
        queue_io.add_bill("Acme", 100.0, "test", date(2026, 1, 1), "5678")
        assert "5678" in queue_path.read_text()
        queue_io.update_bill(0, "Acme", 100.0, "test", date(2026, 1, 1))
        line = queue_path.read_text().strip()
        assert "5678" not in line
        assert line == "Acme, 100.00, test, 2026-01-01"

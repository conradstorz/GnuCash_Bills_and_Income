"""
Read/write/edit/delete operations on bills_to_process.txt queue.
"""
from pathlib import Path
from datetime import date
from typing import Optional
from loguru import logger

from bill_processor import config
from bill_processor.utils import parse_input_line


def read_queue() -> list[dict]:
    """Return parsed list of queued bills with their file-line indices."""
    path = config.BILLS_INPUT_PATH
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    bills = []
    for i, line in enumerate(lines):
        parsed = parse_input_line(line)
        if parsed:
            parsed["_index"] = i
            parsed["_raw"] = line.rstrip()
            bills.append(parsed)
    return bills


def _read_raw_lines() -> list[str]:
    path = config.BILLS_INPUT_PATH
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return f.readlines()


def _write_raw_lines(lines: list[str]) -> None:
    config.BILLS_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.BILLS_INPUT_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _format_bill_line(vendor_name: str, amount: float, memo: str, bill_date: date) -> str:
    memo = memo.strip() or "no memo"
    return f"{vendor_name}, {amount:.2f}, {memo}, {bill_date.isoformat()}\n"


def add_bill(vendor_name: str, amount: float, memo: str, bill_date: date) -> None:
    """Append a bill to the queue file."""
    line = _format_bill_line(vendor_name, amount, memo, bill_date)
    config.BILLS_INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(config.BILLS_INPUT_PATH, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info(f"Queued bill: {vendor_name} ${amount:.2f}")


def remove_bill(file_line_index: int) -> bool:
    """Remove the bill at the given file line index."""
    lines = _read_raw_lines()
    if file_line_index < 0 or file_line_index >= len(lines):
        logger.warning(f"remove_bill: line index {file_line_index} out of range (file has {len(lines)} lines)")
        return False
    lines.pop(file_line_index)
    _write_raw_lines(lines)
    return True


def update_bill(file_line_index: int, vendor_name: str, amount: float, memo: str, bill_date: date) -> bool:
    """Replace the bill at the given file line index with updated values."""
    lines = _read_raw_lines()
    if file_line_index < 0 or file_line_index >= len(lines):
        logger.warning(f"update_bill: line index {file_line_index} out of range (file has {len(lines)} lines)")
        return False
    lines[file_line_index] = _format_bill_line(vendor_name, amount, memo, bill_date)
    _write_raw_lines(lines)
    return True

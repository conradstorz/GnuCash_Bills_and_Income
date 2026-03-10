#!/usr/bin/env python3
"""
Columbo - The GnuCash Database Detective

A self-contained snapshot and diff tool for debugging GnuCash database changes.
Just one more thing... this script helps you find what changed in your database.

Usage:
    First run:  python columbo.py path/to/book.gnucash
                Creates snapshot_before.json
    
    Second run: python columbo.py path/to/book.gnucash
                Creates snapshot_after.json and shows what changed
    
    Reset:      Delete snapshot_before.json to start over
"""

import json
import logging
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class TransactionSnapshot:
    """Snapshot of a single transaction's state."""
    
    guid: str
    description: str
    post_date: Optional[str]
    enter_date: Optional[str]
    split_count: int
    splits: list[dict]
    error: Optional[str] = None
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class AccountSnapshot:
    """Snapshot of a single account's state."""
    
    guid: str
    full_name: str
    type: str
    commodity_symbol: str
    parent_guid: Optional[str]
    balance: Optional[float] = None
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class DatabaseSnapshot:
    """Complete snapshot of GnuCash database state."""
    
    def __init__(self):
        self.timestamp = datetime.now().isoformat()
        self.accounts: dict[str, AccountSnapshot] = {}
        self.transactions: dict[str, TransactionSnapshot] = {}
        self.metadata = {
            "account_count": 0,
            "transaction_count": 0,
            "error_count": 0
        }
    
    @classmethod
    def capture(cls, book_path: Path) -> "DatabaseSnapshot":
        """
        Capture a snapshot of the database.
        
        Args:
            book_path: Path to GnuCash book file.
            
        Returns:
            DatabaseSnapshot with all accounts and transactions.
        """
        try:
            import piecash
        except ImportError:
            logger.error("piecash library required. Install with: pip install piecash")
            sys.exit(1)
        
        logger.info(f"Opening GnuCash book: {book_path}")
        snapshot = cls()
        
        # Open book
        book = piecash.open_book(str(book_path), readonly=True, do_backup=False)
        
        try:
            # Capture accounts
            logger.info("Capturing accounts...")
            for account in book.accounts:
                full_name = account.fullname if hasattr(account, 'fullname') else str(account)
                parent_guid = None
                if account.parent and account.parent.guid:
                    parent_guid = str(account.parent.guid)
                
                snapshot.accounts[str(account.guid)] = AccountSnapshot(
                    guid=str(account.guid),
                    full_name=full_name,
                    type=account.type,
                    commodity_symbol=account.commodity.mnemonic,
                    parent_guid=parent_guid
                )
            
            snapshot.metadata["account_count"] = len(snapshot.accounts)
            logger.info(f"Captured {len(snapshot.accounts)} accounts")
            
            # Capture transactions
            logger.info("Capturing transactions...")
            error_count = 0
            success_count = 0
            
            for transaction in book.transactions:
                try:
                    trans_guid = str(transaction.guid)
                    trans_desc = transaction.description if transaction.description else ""
                    
                    # Try to get dates
                    post_date = None
                    enter_date = None
                    error = None
                    
                    try:
                        post_date = transaction.post_date.strftime("%Y-%m-%d %H:%M:%S") if transaction.post_date else None
                    except Exception as e:
                        error = f"post_date: {str(e)}"
                    
                    try:
                        enter_date = transaction.enter_date.strftime("%Y-%m-%d %H:%M:%S") if hasattr(transaction, 'enter_date') and transaction.enter_date else None
                    except Exception as e:
                        if error:
                            error += f"; enter_date: {str(e)}"
                        else:
                            error = f"enter_date: {str(e)}"
                    
                    # Try to get splits
                    splits = []
                    split_count = 0
                    try:
                        for split in transaction.splits:
                            split_count += 1
                            try:
                                splits.append({
                                    "account_guid": str(split.account.guid) if split.account else None,
                                    "account_name": split.account.name if split.account else None,
                                    "value": float(split.value) if split.value is not None else None,
                                    "quantity": float(split.quantity) if split.quantity is not None else None,
                                    "memo": split.memo if split.memo else None,
                                    "reconcile_state": split.reconcile_state if hasattr(split, 'reconcile_state') else None
                                })
                            except Exception as e:
                                splits.append({"error": f"Error reading split: {str(e)}"})
                    except Exception as e:
                        error = f"splits: {str(e)}" if not error else f"{error}; splits: {str(e)}"
                    
                    snapshot.transactions[trans_guid] = TransactionSnapshot(
                        guid=trans_guid,
                        description=trans_desc,
                        post_date=post_date,
                        enter_date=enter_date,
                        split_count=split_count,
                        splits=splits,
                        error=error
                    )
                    
                    if error:
                        error_count += 1
                    else:
                        success_count += 1
                        
                except Exception as e:
                    logger.error(f"Error capturing transaction: {e}")
                    error_count += 1
            
            snapshot.metadata["transaction_count"] = len(snapshot.transactions)
            snapshot.metadata["error_count"] = error_count
            logger.info(f"Captured {len(snapshot.transactions)} transactions ({success_count} valid, {error_count} with errors)")
            
        finally:
            book.close()
        
        return snapshot
    
    def save(self, filepath: Path) -> None:
        """Save snapshot to JSON file."""
        data = {
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "accounts": {guid: acc.to_dict() for guid, acc in self.accounts.items()},
            "transactions": {guid: trans.to_dict() for guid, trans in self.transactions.items()}
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"Snapshot saved to {filepath}")
    
    @classmethod
    def load(cls, filepath: Path) -> "DatabaseSnapshot":
        """Load snapshot from JSON file."""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        snapshot = cls()
        snapshot.timestamp = data["timestamp"]
        snapshot.metadata = data["metadata"]
        
        for guid, acc_data in data["accounts"].items():
            snapshot.accounts[guid] = AccountSnapshot(**acc_data)
        
        for guid, trans_data in data["transactions"].items():
            snapshot.transactions[guid] = TransactionSnapshot(**trans_data)
        
        logger.info(f"Snapshot loaded from {filepath}")
        return snapshot


def compare_snapshots(before: DatabaseSnapshot, after: DatabaseSnapshot) -> dict:
    """Compare two snapshots and identify changes."""
    logger.info("Comparing snapshots")
    
    changes = {
        "timestamp_before": before.timestamp,
        "timestamp_after": after.timestamp,
        "accounts": {
            "added": [],
            "removed": [],
            "modified": []
        },
        "transactions": {
            "added": [],
            "removed": [],
            "modified": [],
            "fixed": [],
            "broken": []
        },
        "summary": {}
    }
    
    # Compare accounts
    before_guids = set(before.accounts.keys())
    after_guids = set(after.accounts.keys())
    
    for guid in (after_guids - before_guids):
        changes["accounts"]["added"].append(after.accounts[guid].to_dict())
    
    for guid in (before_guids - after_guids):
        changes["accounts"]["removed"].append(before.accounts[guid].to_dict())
    
    for guid in (before_guids & after_guids):
        if before.accounts[guid].to_dict() != after.accounts[guid].to_dict():
            changes["accounts"]["modified"].append({
                "guid": guid,
                "before": before.accounts[guid].to_dict(),
                "after": after.accounts[guid].to_dict()
            })
    
    # Compare transactions
    before_trans = set(before.transactions.keys())
    after_trans = set(after.transactions.keys())
    
    for guid in (after_trans - before_trans):
        trans = after.transactions[guid]
        # Check if this is replacing a removed transaction (same description)
        is_replacement = False
        for removed_guid in (before_trans - after_trans):
            if before.transactions[removed_guid].description == trans.description:
                is_replacement = True
                break
        
        if is_replacement and trans.error is None:
            # This looks like a fix - new transaction replaced bad one
            pass  # Will be caught in fixed section
        
        changes["transactions"]["added"].append(trans.to_dict())
    
    for guid in (before_trans - after_trans):
        trans = before.transactions[guid]
        # Check if this was replaced by a new transaction
        was_replaced = False
        for added_guid in (after_trans - before_trans):
            if after.transactions[added_guid].description == trans.description:
                was_replaced = True
                # Check if it was a fix
                if trans.error and not after.transactions[added_guid].error:
                    changes["transactions"]["fixed"].append({
                        "old_guid": guid,
                        "new_guid": added_guid,
                        "description": trans.description,
                        "before": trans.to_dict(),
                        "after": after.transactions[added_guid].to_dict(),
                        "fix_type": "recreated"
                    })
                break
        
        changes["transactions"]["removed"].append(trans.to_dict())
    
    for guid in (before_trans & after_trans):
        before_t = before.transactions[guid]
        after_t = after.transactions[guid]
        
        before_had_error = before_t.error is not None
        after_has_error = after_t.error is not None
        
        if before_had_error and not after_has_error:
            changes["transactions"]["fixed"].append({
                "guid": guid,
                "description": after_t.description,
                "before": before_t.to_dict(),
                "after": after_t.to_dict(),
                "fix_type": "in-place"
            })
        elif not before_had_error and after_has_error:
            changes["transactions"]["broken"].append({
                "guid": guid,
                "description": after_t.description,
                "before": before_t.to_dict(),
                "after": after_t.to_dict()
            })
        elif before_t.to_dict() != after_t.to_dict():
            changes["transactions"]["modified"].append({
                "guid": guid,
                "description": after_t.description,
                "before": before_t.to_dict(),
                "after": after_t.to_dict()
            })
    
    changes["summary"] = {
        "accounts_added": len(changes["accounts"]["added"]),
        "accounts_removed": len(changes["accounts"]["removed"]),
        "accounts_modified": len(changes["accounts"]["modified"]),
        "transactions_added": len(changes["transactions"]["added"]),
        "transactions_removed": len(changes["transactions"]["removed"]),
        "transactions_modified": len(changes["transactions"]["modified"]),
        "transactions_fixed": len(changes["transactions"]["fixed"]),
        "transactions_broken": len(changes["transactions"]["broken"])
    }
    
    return changes


def format_comparison_text(changes: dict) -> str:
    """Format comparison as human-readable text."""
    lines = []
    lines.append("=" * 80)
    lines.append("COLUMBO'S INVESTIGATION REPORT")
    lines.append("Just one more thing... here's what changed in your database")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Before: {changes['timestamp_before']}")
    lines.append(f"After:  {changes['timestamp_after']}")
    lines.append("")
    
    summary = changes["summary"]
    lines.append("SUMMARY")
    lines.append("-" * 80)
    lines.append(f"Accounts:     +{summary['accounts_added']} / -{summary['accounts_removed']} / ~{summary['accounts_modified']}")
    lines.append(f"Transactions: +{summary['transactions_added']} / -{summary['transactions_removed']} / ~{summary['transactions_modified']}")
    lines.append(f"Fixed:        {summary['transactions_fixed']} transaction(s)")
    lines.append(f"Broken:       {summary['transactions_broken']} transaction(s)")
    lines.append("")
    
    # Fixed transactions
    if changes["transactions"]["fixed"]:
        lines.append("=" * 80)
        lines.append(f"TRANSACTIONS FIXED ({len(changes['transactions']['fixed'])})")
        lines.append("=" * 80)
        lines.append("")
        
        for i, fix in enumerate(changes["transactions"]["fixed"], 1):
            fix_type = fix.get("fix_type", "unknown")
            if fix_type == "recreated":
                lines.append(f"{i}. {fix['description']}")
                lines.append(f"   RECREATED (old GUID deleted, new GUID created)")
                lines.append(f"   Old GUID: {fix['old_guid']}")
                lines.append(f"   New GUID: {fix['new_guid']}")
            else:
                lines.append(f"{i}. {fix['description']} (GUID: {fix['guid']})")
            
            lines.append("")
            lines.append("   BEFORE (broken):")
            before = fix['before']
            lines.append(f"     Post Date:  {before['post_date']}")
            lines.append(f"     Enter Date: {before['enter_date']}")
            lines.append(f"     Splits:     {before['split_count']}")
            lines.append(f"     Error:      {before['error']}")
            lines.append("")
            lines.append("   AFTER (fixed):")
            after = fix['after']
            lines.append(f"     Post Date:  {after['post_date']}")
            lines.append(f"     Enter Date: {after['enter_date']}")
            lines.append(f"     Splits:     {after['split_count']}")
            lines.append(f"     Error:      {after['error']}")
            
            if after['splits']:
                lines.append(f"     Split details:")
                for split in after['splits']:
                    if 'error' not in split:
                        lines.append(f"       - {split['account_name']}: ${split['value']}")
            lines.append("")
    
    # Broken transactions
    if changes["transactions"]["broken"]:
        lines.append("=" * 80)
        lines.append(f"TRANSACTIONS BROKEN ({len(changes['transactions']['broken'])})")
        lines.append("=" * 80)
        lines.append("")
        
        for i, broken in enumerate(changes["transactions"]["broken"], 1):
            lines.append(f"{i}. {broken['description']} (GUID: {broken['guid']})")
            lines.append(f"   WAS WORKING, NOW HAS ERROR: {broken['after']['error']}")
            lines.append("")
    
    # Added transactions (not counted as fixes)
    new_good = [t for t in changes["transactions"]["added"] 
                if t['error'] is None and not any(
                    f['description'] == t['description'] 
                    for f in changes["transactions"]["fixed"] 
                    if f.get('fix_type') == 'recreated'
                )]
    
    if new_good:
        lines.append("=" * 80)
        lines.append(f"NEW TRANSACTIONS ADDED ({len(new_good)})")
        lines.append("=" * 80)
        lines.append("")
        for i, trans in enumerate(new_good, 1):
            lines.append(f"{i}. {trans['description']} - {trans['post_date']} (${sum(s.get('value', 0) for s in trans['splits'] if 'error' not in s and s.get('value', 0) > 0)})")
        lines.append("")
    
    # Removed transactions (not part of fixes)
    removed_bad = [t for t in changes["transactions"]["removed"]
                   if not any(
                       f['description'] == t['description']
                       for f in changes["transactions"]["fixed"]
                       if f.get('fix_type') == 'recreated'
                   )]
    
    if removed_bad:
        lines.append("=" * 80)
        lines.append(f"TRANSACTIONS DELETED ({len(removed_bad)})")
        lines.append("=" * 80)
        lines.append("")
        for i, trans in enumerate(removed_bad, 1):
            error_flag = " [HAD ERRORS]" if trans['error'] else ""
            lines.append(f"{i}. {trans['description']} - {trans['post_date']}{error_flag}")
        lines.append("")
    
    # Modified transactions
    if changes["transactions"]["modified"]:
        lines.append("=" * 80)
        lines.append(f"TRANSACTIONS MODIFIED ({len(changes['transactions']['modified'])})")
        lines.append("=" * 80)
        lines.append("")
        
        for i, mod in enumerate(changes["transactions"]["modified"], 1):
            lines.append(f"{i}. {mod['description']} (GUID: {mod['guid']})")
            before = mod['before']
            after = mod['after']
            
            if before['post_date'] != after['post_date']:
                lines.append(f"   Post Date: {before['post_date']} → {after['post_date']}")
            if before['description'] != after['description']:
                lines.append(f"   Description: {before['description']} → {after['description']}")
            if before['split_count'] != after['split_count']:
                lines.append(f"   Splits: {before['split_count']} → {after['split_count']}")
            lines.append("")
    
    lines.append("=" * 80)
    
    if summary['transactions_fixed'] > 0:
        lines.append("")
        lines.append("✓ Great work! The database is looking better.")
    
    if summary['transactions_broken'] > 0:
        lines.append("")
        lines.append("⚠️  WARNING: Some transactions were damaged by recent changes.")
        lines.append("   Check your external utilities for bugs!")
    
    return "\n".join(lines)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nError: Please provide path to GnuCash book file")
        print("Example: python columbo.py path/to/book.gnucash")
        sys.exit(1)
    
    book_path = Path(sys.argv[1])
    if not book_path.exists():
        logger.error(f"Book file not found: {book_path}")
        sys.exit(1)
    
    before_file = Path("snapshot_before.json")
    after_file = Path("snapshot_after.json")
    
    print("=" * 80)
    print("COLUMBO - The GnuCash Database Detective")
    print("Just one more thing...")
    print("=" * 80)
    print()
    
    if not before_file.exists():
        # First run - create before snapshot
        print("No existing snapshot found. Creating BEFORE snapshot...")
        print()
        
        snapshot = DatabaseSnapshot.capture(book_path)
        snapshot.save(before_file)
        
        print()
        print("=" * 80)
        print("BEFORE SNAPSHOT CAPTURED")
        print("=" * 80)
        print(f"Timestamp:    {snapshot.timestamp}")
        print(f"Accounts:     {snapshot.metadata['account_count']}")
        print(f"Transactions: {snapshot.metadata['transaction_count']}")
        print(f"Errors:       {snapshot.metadata['error_count']}")
        print()
        print(f"✓ Saved to: {before_file}")
        print()
        print("Next steps:")
        print("  1. Make your changes (fix transactions, run utilities, etc.)")
        print("  2. Run this script again to see what changed")
        print(f"  3. To start over, delete {before_file}")
        print()
        
    else:
        # Second run - create after snapshot and compare
        print(f"Found existing snapshot. Creating AFTER snapshot...")
        print()
        
        before = DatabaseSnapshot.load(before_file)
        after = DatabaseSnapshot.capture(book_path)
        after.save(after_file)
        
        print()
        print("Comparing snapshots...")
        print()
        
        changes = compare_snapshots(before, after)
        report = format_comparison_text(changes)
        
        print(report)
        
        # Save report to file
        report_file = Path("columbo_report.txt")
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print()
        print(f"Full report saved to: {report_file}")
        print()
        print("Next steps:")
        print(f"  - Review the changes above")
        print(f"  - To investigate more changes, delete {before_file}")
        print(f"  - The after snapshot becomes your new baseline")
        print()


if __name__ == "__main__":
    main()

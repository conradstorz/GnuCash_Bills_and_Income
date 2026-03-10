"""
Check for bills with missing or invalid date fields in the database.

This tool scans the GnuCash database for bills/invoices that are missing
required date fields or have invalid date values.

Usage:
    uv run python -m bill_processor.check_bill_dates [--fix]
"""

import sqlite3
from pathlib import Path
from typing import List, Dict
from datetime import date
from loguru import logger

from bill_processor import config
from bill_processor.gnucash_db import get_connection, format_gnucash_date


def find_missing_dates() -> List[Dict]:
    """
    Find all bills with missing or invalid date fields.
    
    Checks:
    - date_opened (required for all bills)
    - date_posted (required for posted bills)
    
    Returns:
        List of dicts with bill info and missing date details
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT 
                i.guid,
                i.id as bill_id,
                i.date_opened,
                i.date_posted,
                i.notes,
                i.post_lot,
                i.post_txn,
                v.name as vendor_name
            FROM invoices i
            LEFT JOIN vendors v ON i.owner_guid = v.guid
            WHERE i.owner_type = 4
            ORDER BY i.id
        """)
        
        results = []
        for row in cursor:
            issues = []
            
            # Check date_opened (always required)
            if not row['date_opened'] or row['date_opened'].strip() == '':
                issues.append('date_opened is NULL or empty')
            
            # Check date_posted for posted bills
            is_posted = row['post_lot'] and row['post_lot'].strip() != ''
            if is_posted:
                if not row['date_posted'] or row['date_posted'].strip() == '':
                    issues.append('date_posted is NULL or empty (bill is posted)')
            
            if issues:
                results.append({
                    'guid': row['guid'],
                    'bill_id': row['bill_id'],
                    'vendor_name': row['vendor_name'],
                    'date_opened': row['date_opened'],
                    'date_posted': row['date_posted'],
                    'is_posted': is_posted,
                    'notes': row['notes'],
                    'issues': issues
                })
        
        return results


def fix_missing_dates(entries: List[Dict], default_date: date = None, use_opened_date: bool = True) -> int:
    """
    Fix bills with missing dates.
    
    For missing date_posted on posted bills: uses date_opened by default for accuracy.
    For missing date_opened: uses provided default_date or today.
    
    Args:
        entries: List of bill dicts from find_missing_dates()
        default_date: Date to use for missing dates (defaults to today)
        use_opened_date: If True, use date_opened for missing date_posted (default True)
    
    Returns:
        Number of bills fixed
    """
    if not entries:
        return 0
    
    if default_date is None:
        default_date = date.today()
    
    default_date_str = format_gnucash_date(default_date)
    
    db_path = Path(config.GNUCASH_DB_PATH)
    conn = sqlite3.connect(str(db_path))
    
    fixed_count = 0
    
    try:
        for entry in entries:
            updates = []
            params = []
            
            # Fix date_opened if missing
            if 'date_opened is NULL or empty' in entry['issues']:
                updates.append('date_opened = ?')
                params.append(default_date_str)
                logger.info(f"Setting date_opened for bill {entry['bill_id']} to {default_date_str}")
            
            # Fix date_posted if missing and bill is posted
            if 'date_posted is NULL or empty (bill is posted)' in entry['issues']:
                # Use the bill's own date_opened if available and use_opened_date is True
                if use_opened_date and entry['date_opened'] and entry['date_opened'].strip() != '':
                    date_to_use = entry['date_opened']
                    logger.info(f"Setting date_posted for bill {entry['bill_id']} to its date_opened: {date_to_use}")
                else:
                    date_to_use = default_date_str
                    logger.info(f"Setting date_posted for bill {entry['bill_id']} to default: {date_to_use}")
                
                updates.append('date_posted = ?')
                params.append(date_to_use)
            
            if updates:
                params.append(entry['guid'])
                sql = f"UPDATE invoices SET {', '.join(updates)} WHERE guid = ?"
                conn.execute(sql, params)
                fixed_count += 1
        
        conn.commit()
        logger.info(f"Successfully fixed {fixed_count} bills")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error fixing bills: {e}")
        raise
    finally:
        conn.close()
    
    return fixed_count


def main():
    """Main entry point."""
    import sys
    from datetime import datetime
    
    print("=" * 70)
    print("BILL DATE CHECKER")
    print("=" * 70)
    print()
    print("Scanning for bills with missing or invalid date fields...")
    print()
    
    # Check for --fix flag and optional date
    fix_mode = '--fix' in sys.argv
    default_date = None
    
    # Look for --date argument
    for i, arg in enumerate(sys.argv):
        if arg == '--date' and i + 1 < len(sys.argv):
            try:
                default_date = datetime.strptime(sys.argv[i + 1], '%Y-%m-%d').date()
                print(f"Using default date: {default_date}")
                print()
            except ValueError:
                print(f"Error: Invalid date format '{sys.argv[i + 1]}'. Use YYYY-MM-DD")
                return 1
    
    # Find problems
    results = find_missing_dates()
    
    if not results:
        print("✓ No issues found! All bills have required date fields")
        return 0
    
    # Report findings
    print(f"⚠️  Found {len(results)} bills with missing date fields:")
    print()
    print(f"{'Bill ID':<12} {'Vendor':<25} {'Posted':<8} {'Issues'}")
    print("-" * 90)
    
    for entry in results:
        posted_status = "Yes" if entry['is_posted'] else "No"
        issues_str = '; '.join(entry['issues'])
        print(
            f"{entry['bill_id']:<12} "
            f"{(entry['vendor_name'] or 'Unknown')[:24]:<25} "
            f"{posted_status:<8} "
            f"{issues_str}"
        )
    
    print()
    print("ISSUE EXPLANATION:")
    print("-" * 70)
    print("Bill records require specific date fields:")
    print("  - date_opened: Required for ALL bills (creation date)")
    print("  - date_posted: Required for POSTED bills (posting date)")
    print()
    print("Missing these dates can cause GnuCash to display errors or")
    print("behave unexpectedly when viewing/editing bills.")
    print()
    
    if fix_mode:
        print("--fix flag detected. Fixing bills...")
        print()
        print("Strategy:")
        print("  - For posted bills missing date_posted: using each bill's date_opened")
        print("  - For bills missing date_opened: using default date")
        print()
        if default_date is None:
            default_date = date.today()
            print(f"Default date: {default_date}")
        print()
        fixed = fix_missing_dates(results, default_date)
        print()
        print(f"✓ Successfully fixed {fixed} bills!")
        print()
        print("You should verify the changes in GnuCash.")
        return 0
    else:
        print("To fix these bills automatically, run:")
        print("  uv run python -m bill_processor.check_bill_dates --fix")
        print()
        print("This will set date_posted to each bill's date_opened value.")
        print()
        print("To specify a custom date for missing fields:")
        print("  uv run python -m bill_processor.check_bill_dates --fix --date 2026-01-28")
        print()
        print("⚠️  WARNING: This will modify your GnuCash database.")
        print("   Make a backup before using --fix!")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())

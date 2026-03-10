"""
Check for bills with incorrect quantities in the database.

This tool scans the GnuCash database for bill entries where the quantity
is not 1, which indicates a data error. Bills should always have quantity=1
with the amount stored in the price field.

Usage:
    uv run python -m bill_processor.check_bill_quantities [--fix]
"""

import sqlite3
from pathlib import Path
from typing import List, Dict
from loguru import logger

from bill_processor import config
from bill_processor.gnucash_db import get_connection


def find_incorrect_quantities() -> List[Dict]:
    """
    Find all bill entries where quantity is not 1.
    
    Returns:
        List of dicts with bill info including invoice id, vendor, amount, and quantity
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT 
                e.guid as entry_guid,
                e.bill as bill_guid,
                e.description,
                e.quantity_num,
                e.quantity_denom,
                e.b_price_num,
                e.b_price_denom,
                i.id as bill_id,
                i.date_opened,
                v.name as vendor_name
            FROM entries e
            LEFT JOIN invoices i ON e.bill = i.guid
            LEFT JOIN vendors v ON i.owner_guid = v.guid
            WHERE e.bill IS NOT NULL
              AND e.bill != ''
              AND (e.quantity_num != 1 OR e.quantity_denom != 1)
            ORDER BY i.date_opened DESC, i.id
        """)
        
        results = []
        for row in cursor:
            # Calculate actual values
            quantity = row['quantity_num'] / row['quantity_denom'] if row['quantity_denom'] != 0 else 0
            price = row['b_price_num'] / row['b_price_denom'] if row['b_price_denom'] != 0 else 0
            total = quantity * price
            
            results.append({
                'entry_guid': row['entry_guid'],
                'bill_guid': row['bill_guid'],
                'bill_id': row['bill_id'],
                'vendor_name': row['vendor_name'],
                'date_opened': row['date_opened'],
                'description': row['description'],
                'quantity_num': row['quantity_num'],
                'quantity_denom': row['quantity_denom'],
                'quantity': quantity,
                'price_num': row['b_price_num'],
                'price_denom': row['b_price_denom'],
                'price': price,
                'total': total
            })
        
        return results


def fix_incorrect_quantities(entries: List[Dict]) -> int:
    """
    Fix entries with incorrect quantities by setting quantity to 1
    and moving the total amount to the price field.
    
    Args:
        entries: List of entry dicts from find_incorrect_quantities()
    
    Returns:
        Number of entries fixed
    """
    if not entries:
        return 0
    
    db_path = Path(config.GNUCASH_DB_PATH)
    conn = sqlite3.connect(str(db_path))
    
    fixed_count = 0
    
    try:
        for entry in entries:
            # Calculate the correct price (total amount)
            correct_price_num = int(entry['total'] * 100)
            correct_price_denom = 100
            
            # Update the entry to have quantity=1 and price=total_amount
            conn.execute("""
                UPDATE entries
                SET quantity_num = 1,
                    quantity_denom = 1,
                    b_price_num = ?,
                    b_price_denom = ?
                WHERE guid = ?
            """, (correct_price_num, correct_price_denom, entry['entry_guid']))
            
            logger.info(
                f"Fixed entry for bill {entry['bill_id']}: "
                f"qty {entry['quantity']} -> 1, "
                f"price ${entry['price']:.2f} -> ${entry['total']:.2f}"
            )
            fixed_count += 1
        
        conn.commit()
        logger.info(f"Successfully fixed {fixed_count} entries")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error fixing entries: {e}")
        raise
    finally:
        conn.close()
    
    return fixed_count


def main():
    """Main entry point."""
    import sys
    
    print("=" * 70)
    print("BILL QUANTITY CHECKER")
    print("=" * 70)
    print()
    print("Scanning for bill entries with incorrect quantities...")
    print()
    
    # Check for --fix flag
    fix_mode = '--fix' in sys.argv
    
    # Find problems
    results = find_incorrect_quantities()
    
    if not results:
        print("✓ No issues found! All bill entries have quantity = 1")
        return 0
    
    # Report findings
    print(f"⚠️  Found {len(results)} bill entries with incorrect quantities:")
    print()
    print(f"{'Bill ID':<12} {'Vendor':<25} {'Date':<12} {'Qty':<8} {'Price':<12} {'Total':<12}")
    print("-" * 90)
    
    for entry in results:
        print(
            f"{entry['bill_id']:<12} "
            f"{entry['vendor_name'][:24]:<25} "
            f"{entry['date_opened'][:10]:<12} "
            f"{entry['quantity']:<8.2f} "
            f"${entry['price']:<11.2f} "
            f"${entry['total']:<11.2f}"
        )
    
    print()
    print("ISSUE EXPLANATION:")
    print("-" * 70)
    print("Bill entries should ALWAYS have quantity = 1, with the dollar amount")
    print("stored in the price field. When quantity > 1, it means the quantity")
    print("and price fields were swapped during bill creation.")
    print()
    print("These entries need to be corrected so that:")
    print("  - quantity = 1")
    print("  - price = (old quantity × old price)")
    print()
    
    if fix_mode:
        print("--fix flag detected. Fixing entries...")
        print()
        fixed = fix_incorrect_quantities(results)
        print()
        print(f"✓ Successfully fixed {fixed} entries!")
        print()
        print("You should verify the changes in GnuCash.")
        return 0
    else:
        print("To fix these entries automatically, run:")
        print("  uv run python -m bill_processor.check_bill_quantities --fix")
        print()
        print("⚠️  WARNING: This will modify your GnuCash database.")
        print("   Make a backup before using --fix!")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())

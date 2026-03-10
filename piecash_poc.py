"""
Proof of Concept: Using piecash for GnuCash bill operations

This demonstrates how piecash could simplify our current raw SQL approach.
"""

import piecash
from datetime import datetime
from pathlib import Path
from bill_processor import config


def open_book(readonly=True):
    """Open GnuCash book with piecash."""
    db_path = Path(config.GNUCASH_DB_PATH)
    
    if readonly:
        return piecash.open_book(str(db_path), readonly=True, do_backup=False)
    else:
        return piecash.open_book(str(db_path), readonly=False, do_backup=True)


def list_vendors_piecash():
    """List all vendors using piecash - compare to our SQL approach."""
    with open_book(readonly=True) as book:
        vendors = book.query(piecash.Vendor).all()
        
        print(f"Found {len(vendors)} vendors using piecash:\n")
        for vendor in vendors:
            print(f"  {vendor.name}")
            if vendor.addr:
                print(f"    Address: {vendor.addr.addr1}")
                if vendor.addr.addr2:
                    print(f"             {vendor.addr.addr2}")
                if vendor.addr.addr3:
                    print(f"             {vendor.addr.addr3}")
                if vendor.addr.addr4:
                    print(f"             {vendor.addr.addr4}")
            print()


def create_vendor_piecash(name, addr1=None, addr2=None, city_state=None, postal=None, phone=None):
    """
    Create vendor using piecash - much simpler than our SQL approach!
    
    Compare this to our create_vendor() in gnucash_db.py which has:
    - Manual GUID generation
    - Manual ID calculation
    - Currency lookup
    - Long INSERT statement with 18 fields
    """
    with open_book(readonly=False) as book:
        # Get USD currency
        usd = book.default_currency
        
        # Create vendor - piecash handles GUID, ID, etc. automatically!
        vendor = piecash.Vendor(
            name=name,
            currency=usd,
            active=1,
        )
        
        # Add address if provided
        if any([addr1, addr2, city_state, postal]):
            vendor.addr = piecash.Address(
                addr1=addr1 or '',
                addr2=addr2 or '',
                addr3=city_state or '',
                addr4=postal or '',
                phone=phone or ''
            )
        
        book.save()
        print(f"✓ Created vendor: {name} (GUID: {vendor.guid})")
        return vendor.guid


def update_vendor_address_piecash(vendor_guid, **address_fields):
    """
    Update vendor address using piecash - cleaner than raw SQL!
    
    Compare to our update_vendor_address() which builds dynamic SQL strings.
    """
    with open_book(readonly=False) as book:
        # Find vendor by GUID - piecash handles the query
        vendor = book.query(piecash.Vendor).filter_by(guid=vendor_guid).first()
        
        if not vendor:
            print(f"✗ Vendor not found: {vendor_guid}")
            return False
        
        # Create or update address
        if not vendor.addr:
            vendor.addr = piecash.Address()
        
        # Update fields
        if 'addr1' in address_fields:
            vendor.addr.addr1 = address_fields['addr1']
        if 'addr2' in address_fields:
            vendor.addr.addr2 = address_fields['addr2']
        if 'addr3' in address_fields:
            vendor.addr.addr3 = address_fields['addr3']
        if 'addr4' in address_fields:
            vendor.addr.addr4 = address_fields['addr4']
        if 'phone' in address_fields:
            vendor.addr.phone = address_fields['phone']
        if 'email' in address_fields:
            vendor.addr.email = address_fields['email']
        
        book.save()
        print(f"✓ Updated vendor address: {vendor.name}")
        return True


def create_bill_piecash(vendor_guid, date_opened, description, entries):
    """
    Create a bill with entries using piecash.
    
    This is where piecash really shines - it handles:
    - Bill creation with proper relationships
    - Entry creation with splits
    - Transaction creation and linking
    - GUID generation
    - Date formatting
    - All the complex relationships between tables
    
    Compare to our create_posted_bill_DEPRECATED() which has 200+ lines of SQL!
    """
    with open_book(readonly=False) as book:
        # Find vendor
        vendor = book.query(piecash.Vendor).filter_by(guid=vendor_guid).first()
        if not vendor:
            raise ValueError(f"Vendor not found: {vendor_guid}")
        
        # Create bill
        bill = piecash.Bill(
            vendor=vendor,
            date_opened=date_opened,
            notes=description or '',
            currency=book.default_currency
        )
        
        # Add entries
        for entry in entries:
            # Find expense account
            expense_account = book.accounts.get(name=entry['account_name'])
            if not expense_account:
                raise ValueError(f"Account not found: {entry['account_name']}")
            
            # Create entry - piecash handles the complex split creation!
            bill.add_entry(
                account=expense_account,
                quantity=entry['quantity'],
                price=entry['price'],
                description=entry.get('description', '')
            )
        
        # Post the bill if requested
        if entries:
            bill.post()
        
        book.save()
        print(f"✓ Created bill: {bill.id} for {vendor.name}")
        return bill.guid


def compare_approaches():
    """
    Print a comparison of raw SQL vs piecash approaches.
    """
    print("=" * 70)
    print("COMPARISON: Raw SQL vs piecash")
    print("=" * 70)
    print()
    
    print("CREATING A VENDOR:")
    print("-" * 70)
    print("Raw SQL (our current approach):")
    print("  - Generate GUID manually")
    print("  - Calculate next vendor ID with MAX query")
    print("  - Look up USD currency GUID")
    print("  - Build INSERT statement with 18 fields")
    print("  - Handle NULL vs empty string")
    print("  - Execute SQL, commit, handle errors")
    print("  - ~80 lines of code")
    print()
    print("piecash:")
    print("  - vendor = piecash.Vendor(name=..., currency=usd)")
    print("  - vendor.addr = piecash.Address(addr1=..., ...)")
    print("  - book.save()")
    print("  - ~10 lines of code")
    print()
    
    print("CREATING A BILL WITH ENTRIES:")
    print("-" * 70)
    print("Raw SQL (our current approach):")
    print("  - Create invoice record (complex INSERT)")
    print("  - Create transaction record with splits")
    print("  - Create entry records")
    print("  - Link everything with GUIDs")
    print("  - Handle denominators for amounts")
    print("  - Post transaction (update lots of fields)")
    print("  - ~200+ lines of code")
    print()
    print("piecash:")
    print("  - bill = piecash.Bill(vendor=..., date=...)")
    print("  - bill.add_entry(account=..., quantity=..., price=...)")
    print("  - bill.post()")
    print("  - book.save()")
    print("  - ~15 lines of code")
    print()
    
    print("PROS OF piecash:")
    print("-" * 70)
    print("  ✓ Much less code (10x reduction)")
    print("  ✓ Higher-level abstractions (work with objects, not SQL)")
    print("  ✓ Type safety (Python objects vs dict rows)")
    print("  ✓ Handles GnuCash internals (GUIDs, denominators, relationships)")
    print("  ✓ Less error-prone (no manual SQL construction)")
    print("  ✓ Automatic backups before writes")
    print("  ✓ Built-in validation")
    print("  ✓ Easier to read and maintain")
    print()
    
    print("CONS OF piecash:")
    print("-" * 70)
    print("  ✗ Additional dependency (but already in pyproject.toml)")
    print("  ✗ Learning curve (need to understand piecash API)")
    print("  ✗ Less control (abstraction layer)")
    print("  ✗ Possible performance overhead (ORM layer)")
    print("  ✗ May not support all GnuCash edge cases")
    print()
    
    print("RECOMMENDATION:")
    print("-" * 70)
    print("Consider migrating to piecash for:")
    print("  1. New features")
    print("  2. Complex operations (bill creation, posting)")
    print("  3. Vendor management")
    print()
    print("Keep raw SQL for:")
    print("  1. Simple queries (performance critical)")
    print("  2. Schema discovery")
    print("  3. Diagnostic tools (Columbo)")
    print()


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("PIECASH PROOF OF CONCEPT")
    print("=" * 70 + "\n")
    
    try:
        # Test basic vendor listing
        print("1. Listing vendors with piecash:")
        print("-" * 70)
        list_vendors_piecash()
        
        print("\n2. Comparison of approaches:")
        print("-" * 70)
        compare_approaches()
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

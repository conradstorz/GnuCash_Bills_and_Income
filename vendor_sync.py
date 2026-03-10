"""
Standalone Vendor Sync Utility
Syncs vendors from vendor_database.json to GnuCash database.
Provides API for vendor validation and JSON manipulation.

Key Features:
- Bidirectional sync between JSON and GnuCash
- Automatic duplicate detection and cleanup
- Stale reference validation
- Address data preservation

The utility automatically validates the JSON database on load and:
1. Detects duplicate vendor entries (multiple entries with same GUID)
2. Removes duplicates, keeping the first entry
3. Saves the cleaned database automatically
4. Validates vendor GUIDs against GnuCash database
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from loguru import logger
import sys
import os

from bill_processor import config
from bill_processor.gnucash_db import get_connection, generate_guid, get_usd_guid
from bill_processor.logging_setup import setup_logging_for_script


# Circular import prevention - import SchemaDiscovery only when needed
def get_schema_discovery():
    """Lazy import of SchemaDiscovery to prevent circular dependencies."""
    from bill_processor.schema_discovery import SchemaDiscovery
    return SchemaDiscovery


class VendorSyncUtility:
    """Utility to sync vendors from JSON database to GnuCash."""
    
    def __init__(self):
        # Fix: Use the correct path structure from your project
        project_root = Path(__file__).parent.parent  # Go up from src/ to project root
        data_dir = project_root / "data"
        self.vendor_db_path = data_dir / "vendor_database.json"
        
        self.vendors_data = {}
        self.schema = None
        self.stats = {
            'total': 0,
            'created': 0,
            'updated': 0,
            'skipped': 0,
            'errors': 0,
            'synced_from_gnucash': 0,
            'synced_to_gnucash': 0
        }
        
        # Ensure data directory exists
        data_dir.mkdir(exist_ok=True)
    
    def validate_and_cleanup_duplicates(self, auto_fix: bool = True) -> Dict[str, any]:
        """Detect and optionally remove duplicate vendor entries sharing the same GUID.
        
        Args:
            auto_fix: If True, automatically remove duplicate entries keeping only the first
            
        Returns:
            Dict with 'duplicates_found', 'duplicates_removed', and 'duplicate_groups' info
        """
        result = {
            'duplicates_found': 0,
            'duplicates_removed': 0,
            'duplicate_groups': []
        }
        
        # Build GUID to vendor keys mapping
        guid_map = {}
        for vendor_key, vendor_data in self.vendors_data.items():
            guid = vendor_data.get('gnucash_guid')
            if guid:  # Only check vendors that have been synced
                if guid not in guid_map:
                    guid_map[guid] = []
                guid_map[guid].append(vendor_key)
        
        # Find duplicates (GUIDs with multiple vendor keys)
        duplicate_guids = {guid: keys for guid, keys in guid_map.items() if len(keys) > 1}
        
        if duplicate_guids:
            result['duplicates_found'] = sum(len(keys) - 1 for keys in duplicate_guids.values())
            
            for guid, vendor_keys in duplicate_guids.items():
                vendor_names = [self.vendors_data[k].get('display_name', k) for k in vendor_keys]
                result['duplicate_groups'].append({
                    'guid': guid,
                    'vendor_keys': vendor_keys,
                    'vendor_names': vendor_names
                })
                
                logger.warning(
                    f"Found {len(vendor_keys)} vendors sharing GUID {guid}: {', '.join(vendor_names)}"
                )
                print(f"⚠️  Duplicate vendors found (same GUID {guid[:8]}...):")
                for i, (key, name) in enumerate(zip(vendor_keys, vendor_names)):
                    status = "(keeping)" if i == 0 else "(removing)" if auto_fix else "(duplicate)"
                    print(f"   {i+1}. {name} [{key}] {status}")
                
                if auto_fix:
                    # Keep the first entry, remove the rest
                    keys_to_remove = vendor_keys[1:]
                    for key in keys_to_remove:
                        logger.info(f"Removing duplicate vendor: {key} ({self.vendors_data[key].get('display_name')})")
                        del self.vendors_data[key]
                        result['duplicates_removed'] += 1
                    
                    print(f"   ✅ Removed {len(keys_to_remove)} duplicate(s), kept {vendor_keys[0]}")
        
        return result
    
    def load_vendor_database(self) -> bool:
        """Load vendor database from JSON file."""
        try:
            if not self.vendor_db_path.exists():
                print(f"❌ Vendor database not found: {self.vendor_db_path}")
                print(f"Expected location: {self.vendor_db_path.absolute()}")
                return False
            
            with open(self.vendor_db_path, 'r') as f:
                data = json.load(f)
                self.vendors_data = data.get('vendors', {})
            
            self.stats['total'] = len(self.vendors_data)
            print(f"✅ Loaded {self.stats['total']} vendors from database")
            
            if self.stats['total'] == 0:
                print("⚠️  No vendors found in database")
                return False
            
            # Validate and cleanup duplicates
            dup_result = self.validate_and_cleanup_duplicates(auto_fix=True)
            if dup_result['duplicates_removed'] > 0:
                print(f"🧹 Cleaned up {dup_result['duplicates_removed']} duplicate vendor entries")
                self.stats['total'] = len(self.vendors_data)
                # Save cleaned database immediately
                self.save_vendor_database()
                print(f"💾 Saved cleaned database: {self.stats['total']} unique vendors")
                
            return True
            
        except Exception as e:
            print(f"❌ Failed to load vendor database: {e}")
            return False
    
    def discover_schema(self) -> bool:
        """Discover GnuCash database schema."""
        try:
            print("🔍 Discovering GnuCash database schema...")
            
            # Check if GnuCash database path is configured
            if not hasattr(config, 'GNUCASH_DB_PATH'):
                print("❌ GNUCASH_DB_PATH not configured in config.py")
                return False
            
            gnucash_path = Path(config.GNUCASH_DB_PATH)
            if not gnucash_path.exists():
                print(f"❌ GnuCash database not found: {gnucash_path}")
                return False
            
            print(f"📍 Using GnuCash database: {gnucash_path}")
            
            # Create fresh schema discovery instance
            SchemaDiscovery = get_schema_discovery()
            self.schema = SchemaDiscovery()
            
            # Ensure schema is discovered/loaded
            if not hasattr(self.schema, 'schema') or not self.schema.schema:
                print("🔄 Running schema discovery...")
                result = self.schema.discover()
                if not result.passed:
                    print(f"❌ Schema discovery failed: {result.summary}")
                    return False
            
            # Check if vendors table exists and get structure
            if not self.schema.has_table('vendors'):
                print("❌ Vendors table not found in GnuCash database")
                return False
                
            vendor_columns = self.schema.get_columns('vendors')
            print(f"✅ Found vendors table with {len(vendor_columns)} columns")
            
            # Log available address columns
            addr_columns = [col for col in vendor_columns if col.startswith('addr_')]
            print(f"📍 Address columns available: {addr_columns}")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to discover schema: {e}")
            logger.error(f"Schema discovery failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def build_vendor_insert(self) -> Tuple[str, List[str]]:
        """Build INSERT statement based on discovered schema."""
        try:
            sql, columns = self.schema.build_vendor_insert_statement()
            print(f"✅ Built INSERT statement with {len(columns)} columns")
            
            # Show which address columns will be populated
            addr_columns = [col for col in columns if col.startswith('addr_')]
            for col in addr_columns:
                print(f"  📍 Will populate address field: {col}")
            
            return sql, columns
        except Exception as e:
            print(f"❌ Failed to build INSERT statement: {e}")
            raise
    
    def vendor_exists_in_gnucash(self, display_name: str) -> Optional[Dict]:
        """Check if vendor already exists in GnuCash."""
        try:
            with get_connection() as conn:
                cursor = conn.execute(
                    "SELECT guid, id, name FROM vendors WHERE name = ?",
                    (display_name,)
                )
                row = cursor.fetchone()
                if row:
                    return {
                        'guid': row['guid'],
                        'id': row['id'],
                        'name': row['name']
                    }
                return None
        except Exception as e:
            logger.error(f"Error checking vendor existence: {e}")
            return None
    
    def get_next_vendor_id(self) -> str:
        """Get next available vendor ID."""
        with get_connection() as conn:
            cursor = conn.execute("SELECT MAX(CAST(id AS INTEGER)) FROM vendors")
            max_id = cursor.fetchone()[0] or 0
            return f"{max_id + 1:06d}"
    
    def create_vendor_in_gnucash(self, vendor_key: str, vendor_data: Dict) -> bool:
        """Create a single vendor in GnuCash."""
        display_name = vendor_data.get('display_name', vendor_key)
        
        try:
            # Build INSERT statement
            insert_sql, column_names = self.build_vendor_insert()
            
            # Prepare values
            vendor_guid = generate_guid()
            vendor_id = self.get_next_vendor_id()
            usd_guid = get_usd_guid()
            
            # Map JSON data to database columns with detailed logging
            values_map = {
                'guid': vendor_guid,
                'id': vendor_id,
                'name': display_name,
                'currency': usd_guid,
                'active': 1,
                'notes': '',
                'addr_name': vendor_data.get('addr_name', ''),
                'addr_addr1': vendor_data.get('addr_line1', ''),
                'addr_addr2': vendor_data.get('addr_line2', ''),
                'addr_phone': vendor_data.get('phone', ''),
                'addr_email': vendor_data.get('addr_email', ''),
                'tax_override': 0,
                'tax_inc': '',
                'tax_table': ''
            }
            
            # Log address data being inserted
            print(f"    📍 Address data:")
            print(f"      addr_name: '{values_map.get('addr_name', '')}'")
            print(f"      addr_addr1: '{values_map.get('addr_addr1', '')}'")
            print(f"      addr_addr2: '{values_map.get('addr_addr2', '')}'")
            print(f"      addr_phone: '{values_map.get('addr_phone', '')}'")
            
            # Build ordered values list
            insert_values = [values_map.get(col, '') for col in column_names]
            
            # Execute INSERT
            with get_connection(readonly=False) as conn:
                conn.execute(insert_sql, insert_values)
                conn.commit()
                
                # Verify the insert worked
                cursor = conn.execute(
                    "SELECT addr_name, addr_addr1, addr_addr2, addr_phone FROM vendors WHERE guid = ?",
                    (vendor_guid,)
                )
                row = cursor.fetchone()
                if row:
                    print(f"    ✅ Verified address saved:")
                    print(f"      addr_name: '{row['addr_name'] or '(empty)'}'")
                    print(f"      addr_addr1: '{row['addr_addr1'] or '(empty)'}'")
                    print(f"      addr_addr2: '{row['addr_addr2'] or '(empty)'}'")
                    print(f"      addr_phone: '{row['addr_phone'] or '(empty)'}'")
            
            # Update JSON database with GnuCash IDs
            vendor_data['gnucash_guid'] = vendor_guid
            vendor_data['gnucash_id'] = vendor_id
            
            print(f"  ✅ Created: {display_name} (ID: {vendor_id})")
            self.stats['created'] += 1
            return True
            
        except Exception as e:
            print(f"  ❌ Failed to create {display_name}: {e}")
            logger.error(f"Failed to create vendor {display_name}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.stats['errors'] += 1
            return False
    
    def update_vendor_ids(self, vendor_key: str, gnucash_data: Dict) -> bool:
        """Update JSON database with existing GnuCash IDs."""
        try:
            self.vendors_data[vendor_key]['gnucash_guid'] = gnucash_data['guid']
            self.vendors_data[vendor_key]['gnucash_id'] = gnucash_data['id']
            self.stats['updated'] += 1
            return True
        except Exception as e:
            logger.error(f"Failed to update vendor IDs: {e}")
            return False
    
    def save_vendor_database(self) -> bool:
        """Save updated vendor database to JSON file."""
        try:
            # Preserve existing aliases
            existing_data = {}
            if self.vendor_db_path.exists():
                with open(self.vendor_db_path, 'r') as f:
                    existing_data = json.load(f)
            
            data = {
                'vendors': self.vendors_data, 
                'aliases': existing_data.get('aliases', {})
            }
            
            with open(self.vendor_db_path, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"💾 Updated vendor database saved to: {self.vendor_db_path}")
            return True
        except Exception as e:
            print(f"❌ Failed to save vendor database: {e}")
            return False
    
    def reset_vendor_to_unsynced(self, vendor_key: str) -> bool:
        """
        Reset a vendor record to unsynced state, removing stale GnuCash references.
        
        Args:
            vendor_key: The key of the vendor in the JSON database
            
        Returns:
            True if reset was successful, False otherwise
        """
        try:
            if vendor_key not in self.vendors_data:
                logger.warning(f"Vendor key '{vendor_key}' not found in database")
                return False
            
            vendor_data = self.vendors_data[vendor_key]
            
            # Remove GnuCash sync fields
            fields_to_remove = [
                'gnucash_guid', 
                'gnucash_id',
                'expense_account_guid',  # Stale account reference
            ]
            
            removed_fields = []
            for field in fields_to_remove:
                if field in vendor_data:
                    removed_fields.append(f"{field}={vendor_data[field]}")
                    del vendor_data[field]
            
            if removed_fields:
                logger.info(f"Reset vendor '{vendor_data.get('display_name', vendor_key)}' to unsynced state")
                logger.debug(f"Removed fields: {', '.join(removed_fields)}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error resetting vendor {vendor_key}: {e}")
            return False
    
    def validate_vendor_references(self, auto_fix: bool = True) -> Dict[str, List[str]]:
        """
        Validate all vendor GnuCash references and optionally fix stale data.
        
        Args:
            auto_fix: If True, automatically reset vendors with invalid references
            
        Returns:
            Dict with 'valid', 'invalid', and 'fixed' lists of vendor keys
        """
        result = {
            'valid': [],
            'invalid': [],
            'fixed': []
        }
        
        if not self.load_vendor_database():
            logger.error("Failed to load vendor database for validation")
            return result
        
        try:
            with get_connection() as conn:
                for vendor_key, vendor_data in self.vendors_data.items():
                    gnucash_guid = vendor_data.get('gnucash_guid')
                    display_name = vendor_data.get('display_name', vendor_key)
                    
                    # Skip vendors that aren't synced yet
                    if not gnucash_guid:
                        continue
                    
                    # Check if vendor still exists in GnuCash
                    cursor = conn.execute(
                        "SELECT guid, id, name FROM vendors WHERE guid = ?",
                        (gnucash_guid,)
                    )
                    row = cursor.fetchone()
                    
                    if row:
                        # Vendor exists in GnuCash
                        result['valid'].append(vendor_key)
                        
                        # Also validate expense account if present
                        expense_guid = vendor_data.get('expense_account_guid')
                        if expense_guid:
                            cursor = conn.execute(
                                "SELECT guid FROM accounts WHERE guid = ?",
                                (expense_guid,)
                            )
                            acct_row = cursor.fetchone()
                            if not acct_row:
                                logger.warning(f"Vendor '{display_name}' has invalid expense_account_guid: {expense_guid}")
                                if auto_fix:
                                    if 'expense_account_guid' in vendor_data:
                                        del vendor_data['expense_account_guid']
                                    logger.info(f"Removed invalid expense_account_guid from '{display_name}'")
                                    result['fixed'].append(vendor_key)
                    else:
                        # Vendor deleted from GnuCash but still in JSON
                        logger.warning(f"Vendor '{display_name}' (GUID: {gnucash_guid}) not found in GnuCash database")
                        result['invalid'].append(vendor_key)
                        
                        if auto_fix:
                            if self.reset_vendor_to_unsynced(vendor_key):
                                logger.info(f"Reset vendor '{display_name}' to unsynced state")
                                result['fixed'].append(vendor_key)
            
            # Save changes if any fixes were made
            if auto_fix and result['fixed']:
                self.save_vendor_database()
                logger.info(f"Vendor database updated: {len(result['fixed'])} vendors fixed")
            
        except Exception as e:
            logger.error(f"Error validating vendor references: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return result
    
    def sync_all_vendors(self, force_recreate: bool = False, dry_run: bool = False) -> bool:
        """Sync all vendors from JSON to GnuCash."""
        print(f"\n{'='*60}")
        print(f"VENDOR SYNC UTILITY")
        print(f"{'='*60}")
        print(f"Source: {self.vendor_db_path}")
        print(f"Target: {getattr(config, 'GNUCASH_DB_PATH', 'Not configured')}")
        print(f"Force recreate: {force_recreate}")
        print(f"Dry run: {dry_run}")
        print(f"{'='*60}\n")
        
        if not self.load_vendor_database():
            return False
        
        if not self.discover_schema():
            return False
        
        if dry_run:
            print(f"🔍 DRY RUN - Would sync {self.stats['total']} vendors")
            for vendor_key, vendor_data in self.vendors_data.items():
                display_name = vendor_data.get('display_name', vendor_key)
                existing = self.vendor_exists_in_gnucash(display_name)
                status = "EXISTS" if existing else "CREATE"
                print(f"  {display_name} -> {status}")
            return True
        
        print(f"🚀 Starting sync of {self.stats['total']} vendors...\n")
        
        for vendor_key, vendor_data in self.vendors_data.items():
            display_name = vendor_data.get('display_name', vendor_key)
            print(f"Processing: {display_name}")
            
            # Check if vendor already exists
            existing = self.vendor_exists_in_gnucash(display_name)
            
            if existing and not force_recreate:
                print(f"  📍 Already exists (ID: {existing['id']})")
                # Update JSON with GnuCash IDs if missing
                if not vendor_data.get('gnucash_guid'):
                    self.update_vendor_ids(vendor_key, existing)
                    print(f"  📝 Updated JSON with GnuCash IDs")
                else:
                    self.stats['skipped'] += 1
            elif existing and force_recreate:
                print(f"  🔄 Force recreate not implemented (would delete existing)")
                self.stats['skipped'] += 1
            else:
                # Create new vendor
                self.create_vendor_in_gnucash(vendor_key, vendor_data)
        
        print(f"\n{'='*60}")
        print(f"SYNC COMPLETE")
        print(f"{'='*60}")
        print(f"Total vendors: {self.stats['total']}")
        print(f"Created: {self.stats['created']}")
        print(f"Updated: {self.stats['updated']}")
        print(f"Skipped: {self.stats['skipped']}")
        print(f"Errors: {self.stats['errors']}")
        print(f"{'='*60}\n")
        
        # Save updated JSON database
        if self.stats['created'] > 0 or self.stats['updated'] > 0:
            self.save_vendor_database()
        
        return self.stats['errors'] == 0


def get_all_gnucash_vendors() -> List[Dict]:
    """Get all vendors from GnuCash database."""
    try:
        with get_connection() as conn:
            cursor = conn.execute("""
                SELECT guid, id, name, currency, active, notes,
                       addr_name, addr_addr1, addr_addr2, addr_addr3, addr_addr4,
                       addr_phone, addr_fax, addr_email
                FROM vendors
                ORDER BY name
            """)
            
            vendors = []
            for row in cursor.fetchall():
                vendors.append({
                    'guid': row['guid'],
                    'id': row['id'],
                    'name': row['name'],
                    'currency': row['currency'],
                    'active': row['active'],
                    'notes': row['notes'] or '',
                    'addr_name': row['addr_name'] or '',
                    'addr_addr1': row['addr_addr1'] or '',
                    'addr_addr2': row['addr_addr2'] or '',
                    'addr_addr3': row['addr_addr3'] or '',
                    'addr_addr4': row['addr_addr4'] or '',
                    'addr_phone': row['addr_phone'] or '',
                    'addr_fax': row['addr_fax'] or '',
                    'addr_email': row['addr_email'] or ''
                })
            
            return vendors
            
    except Exception as e:
        logger.error(f"Error getting GnuCash vendors: {e}")
        return []


def sync_gnucash_to_json(self) -> bool:
    """Sync vendors from GnuCash to JSON database."""
    print(f"\n{'='*60}")
    print(f"SYNC: GnuCash → JSON")
    print(f"{'='*60}\n")
    
    try:
        # Get all vendors from GnuCash
        gnucash_vendors = get_all_gnucash_vendors()
        print(f"📥 Found {len(gnucash_vendors)} vendors in GnuCash database")
        
        if not gnucash_vendors:
            print("⚠️  No vendors found in GnuCash")
            return True
        
        # Load current JSON database
        if not self.load_vendor_database():
            # If JSON doesn't exist, start with empty dict
            self.vendors_data = {}
        
        updated_count = 0
        new_count = 0
        
        for gc_vendor in gnucash_vendors:
            vendor_name = gc_vendor['name']
            vendor_guid = gc_vendor['guid']
            
            # Generate vendor key (normalized name)
            from bill_processor.utils import strip_vendor_name
            vendor_key = strip_vendor_name(vendor_name)
            
            # Check if vendor already exists in JSON
            existing_vendor = None
            for key, data in self.vendors_data.items():
                if data.get('gnucash_guid') == vendor_guid:
                    existing_vendor = key
                    break
            
            if not existing_vendor:
                # Check by name
                for key, data in self.vendors_data.items():
                    if data.get('display_name', '').lower() == vendor_name.lower():
                        existing_vendor = key
                        break
            
            # Build vendor data
            vendor_data = {
                'display_name': vendor_name,
                'search_name': vendor_name,
                'gnucash_guid': vendor_guid,
                'gnucash_id': gc_vendor['id'],
                'addr_name': gc_vendor['addr_name'],
                'addr_line1': gc_vendor['addr_addr1'],
                'addr_line2': f"{gc_vendor['addr_addr2']} {gc_vendor['addr_addr3']}".strip(),
                'phone': gc_vendor['addr_phone'],
                'email': gc_vendor['addr_email'],
                'notes': gc_vendor['notes'],
                'active': gc_vendor['active'],
                'address_source': 'gnucash'
            }
            
            if existing_vendor:
                # Update existing vendor
                # Preserve expense account info if it exists
                old_data = self.vendors_data[existing_vendor]
                if old_data.get('expense_account'):
                    vendor_data['expense_account'] = old_data['expense_account']
                if old_data.get('expense_account_guid'):
                    vendor_data['expense_account_guid'] = old_data['expense_account_guid']
                
                self.vendors_data[existing_vendor] = vendor_data
                print(f"  ✏️  Updated: {vendor_name}")
                updated_count += 1
            else:
                # Add new vendor
                self.vendors_data[vendor_key] = vendor_data
                print(f"  ✨ New: {vendor_name}")
                new_count += 1
        
        self.stats['synced_from_gnucash'] = new_count + updated_count
        
        print(f"\n📊 Summary:")
        print(f"  New vendors added: {new_count}")
        print(f"  Existing vendors updated: {updated_count}")
        print(f"  Total: {new_count + updated_count}")
        
        # Save updated JSON database
        if new_count > 0 or updated_count > 0:
            self.save_vendor_database()
            print(f"✅ JSON database updated successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ Error syncing GnuCash to JSON: {e}")
        logger.error(f"Error in sync_gnucash_to_json: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def sync_bidirectional(self, dry_run: bool = False) -> bool:
    """Perform bidirectional sync between JSON and GnuCash."""
    print(f"\n{'='*60}")
    print(f"BIDIRECTIONAL VENDOR SYNC")
    print(f"{'='*60}")
    print(f"JSON Database: {self.vendor_db_path}")
    print(f"GnuCash Database: {getattr(config, 'GNUCASH_DB_PATH', 'Not configured')}")
    print(f"Dry run: {dry_run}")
    print(f"{'='*60}\n")
    
    if not self.discover_schema():
        return False
    
    if dry_run:
        print("🔍 DRY RUN - No changes will be made\n")
    
    # Step 1: Sync from GnuCash to JSON (get latest from database)
    print("Step 1: GnuCash → JSON (import from database)")
    print("-" * 60)
    if not dry_run:
        if not self.sync_gnucash_to_json():
            print("❌ Failed to sync from GnuCash to JSON")
            return False
    else:
        gnucash_vendors = get_all_gnucash_vendors()
        print(f"Would import {len(gnucash_vendors)} vendors from GnuCash")
    
    # Step 2: Sync from JSON to GnuCash (create missing vendors)
    print("\nStep 2: JSON → GnuCash (create missing vendors)")
    print("-" * 60)
    if not dry_run:
        if not self.sync_all_vendors(force_recreate=False, dry_run=False):
            print("❌ Failed to sync from JSON to GnuCash")
            return False
    else:
        if self.load_vendor_database():
            missing_count = 0
            for vendor_key, vendor_data in self.vendors_data.items():
                display_name = vendor_data.get('display_name', vendor_key)
                if not self.vendor_exists_in_gnucash(display_name):
                    missing_count += 1
            print(f"Would create {missing_count} new vendors in GnuCash")
    
    # Summary
    print(f"\n{'='*60}")
    print(f"BIDIRECTIONAL SYNC COMPLETE")
    print(f"{'='*60}")
    
    if not dry_run:
        print(f"Synced from GnuCash: {self.stats['synced_from_gnucash']}")
        print(f"Synced to GnuCash: {self.stats['created']}")
        print(f"Updated in JSON: {self.stats['updated']}")
        print(f"Skipped: {self.stats['skipped']}")
        print(f"Errors: {self.stats['errors']}")
    
    print(f"{'='*60}\n")
    
    return self.stats['errors'] == 0


# Add sync_gnucash_to_json and sync_bidirectional as methods to VendorSyncUtility class
VendorSyncUtility.sync_gnucash_to_json = sync_gnucash_to_json
VendorSyncUtility.sync_bidirectional = sync_bidirectional


def main():
    """Command-line interface for vendor sync."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync vendors between JSON and GnuCash')
    parser.add_argument('--force', action='store_true', 
                       help='Force recreate existing vendors')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be done without making changes')
    parser.add_argument('--list', action='store_true',
                       help='List vendors in JSON database')
    parser.add_argument('--from-gnucash', action='store_true',
                       help='Sync FROM GnuCash TO JSON (import from database)')
    parser.add_argument('--to-gnucash', action='store_true',
                       help='Sync FROM JSON TO GnuCash (create missing vendors)')
    parser.add_argument('--bidirectional', action='store_true',
                       help='Bidirectional sync (both directions)')
    
    args = parser.parse_args()
    
    # Setup centralized logging
    setup_logging_for_script("vendor_sync")
    
    sync_util = VendorSyncUtility()
    
    if args.list:
        if sync_util.load_vendor_database():
            print(f"\nVendors in database ({len(sync_util.vendors_data)}):")
            print("="*50)
            for key, data in sync_util.vendors_data.items():
                name = data.get('display_name', key)
                has_addr = bool(data.get('addr_line1'))
                gnucash_id = data.get('gnucash_id') or 'Not synced'
                print(f"{name:<30} | {gnucash_id:<10} | {'📍' if has_addr else '❌'}")
        return
    
    try:
        success = False
        
        if args.bidirectional:
            # Bidirectional sync
            success = sync_util.sync_bidirectional(dry_run=args.dry_run)
        elif args.from_gnucash:
            # Sync from GnuCash to JSON only
            if not sync_util.discover_schema():
                sys.exit(1)
            success = sync_util.sync_gnucash_to_json()
        elif args.to_gnucash:
            # Sync from JSON to GnuCash only (original behavior)
            success = sync_util.sync_all_vendors(
                force_recreate=args.force, 
                dry_run=args.dry_run
            )
        else:
            # Default: bidirectional sync
            success = sync_util.sync_bidirectional(dry_run=args.dry_run)
        
        if success:
            print("🎉 Vendor sync completed successfully!")
            sys.exit(0)
        else:
            print("💥 Vendor sync completed with errors")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⏹️  Vendor sync cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"💥 Fatal error during sync: {e}")
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()


# ============================================================================
# PUBLIC API FOR OTHER SCRIPTS
# ============================================================================

def validate_and_fix_vendor_references(auto_fix: bool = True, verbose: bool = False):
    """
    Public API: Validate vendor references and optionally fix stale data.
    
    This function can be called from other scripts (like schema_discovery.py)
    to detect and fix vendors that have been deleted from GnuCash but still
    have sync data in the JSON file.
    
    Args:
        auto_fix: If True, automatically reset vendors with invalid references
        verbose: If True, print detailed information
        
    Returns:
        Dict with 'valid', 'invalid', and 'fixed' lists of vendor keys
    """
    sync_util = VendorSyncUtility()
    result = sync_util.validate_vendor_references(auto_fix=auto_fix)
    
    if verbose:
        print(f"\n{'='*60}")
        print("VENDOR VALIDATION REPORT")
        print(f"{'='*60}")
        print(f"Valid vendors: {len(result['valid'])}")
        print(f"Invalid vendors: {len(result['invalid'])}")
        if auto_fix:
            print(f"Fixed vendors: {len(result['fixed'])}")
        
        if result['invalid']:
            print(f"\n⚠️  Invalid vendors found:")
            for vendor_key in result['invalid']:
                print(f"  - {vendor_key}")
            if not auto_fix:
                print("\nRun with auto_fix=True to reset these vendors")
        
        print(f"{'='*60}\n")
    
    return result

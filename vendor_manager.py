"""
Vendor management - matching, JSON database, GnuCash integration.
"""

import json
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from loguru import logger

from bill_processor import config
from bill_processor import gnucash_db
from bill_processor import address_lookup
from bill_processor.utils import (
    fuzzy_match_vendor, 
    strip_vendor_name,
    format_address_for_display,
    confirm_proceed
)


class VendorManager:
    """
    Manages vendor lookups and creation.
    
    Workflow:
    1. Check local JSON database for vendor (by name or alias)
    2. Check GnuCash database
    3. If not found, offer to create new vendor with address lookup
    """
    
    def __init__(self):
        self.json_path = Path(config.VENDOR_DATABASE_PATH)
        self.vendors = self._load_json_database()
        self._gnucash_vendors = None  # Lazy load
    
    def _load_json_database(self) -> Dict:
        """Load the local vendor JSON database."""
        if not self.json_path.exists():
            logger.info(f"Creating new vendor database: {self.json_path}")
            self._save_json_database({'vendors': {}, 'aliases': {}})
            return {'vendors': {}, 'aliases': {}}
        
        try:
            with open(self.json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Ensure structure
                if 'vendors' not in data:
                    data['vendors'] = {}
                if 'aliases' not in data:
                    data['aliases'] = {}
                return data
        except json.JSONDecodeError as e:
            logger.error(f"Error reading vendor database: {e}")
            return {'vendors': {}, 'aliases': {}}
    
    def _save_json_database(self, data: Dict = None):
        """Save the vendor JSON database."""
        if data is None:
            data = self.vendors
        
        # Ensure directory exists
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def save(self):
        """Save current state to JSON."""
        self._save_json_database()
    
    @property
    def gnucash_vendors(self) -> List[Dict]:
        """Lazy-load GnuCash vendors."""
        if self._gnucash_vendors is None:
            self._gnucash_vendors = gnucash_db.get_all_vendors()
        return self._gnucash_vendors
    
    def refresh_gnucash_vendors(self):
        """Force refresh of GnuCash vendor cache."""
        self._gnucash_vendors = None
    
    def find_vendor(self, search_name: str) -> Tuple[Optional[Dict], str]:
        """
        Find a vendor by name.
        
        Returns:
            Tuple of (vendor_data, match_type)
            - vendor_data: Dict with vendor info or None
            - match_type: 'exact', 'alias', 'fuzzy', 'gnucash', or 'not_found'
        """
        search_lower = search_name.lower().strip()
        
        # 1. Check aliases first (exact match)
        for alias, vendor_key in self.vendors.get('aliases', {}).items():
            if alias.lower() == search_lower:
                vendor_data = self.vendors['vendors'].get(vendor_key)
                if vendor_data:
                    return vendor_data, 'alias'
        
        # 2. Check vendor names (exact match)
        for key, data in self.vendors.get('vendors', {}).items():
            if data.get('display_name', '').lower() == search_lower:
                return data, 'exact'
            if data.get('search_name', '').lower() == search_lower:
                return data, 'exact'
        
        # 3. Fuzzy match against JSON vendors
        best_key, best_score, matches = fuzzy_match_vendor(
            search_name, 
            self.vendors.get('vendors', {})
        )
        
        if best_key and best_score >= config.FUZZY_MATCH_THRESHOLD:
            # Check for ambiguity
            close_matches = [m for m in matches if m[1] >= config.FUZZY_AMBIGUOUS_THRESHOLD]
            
            if len(close_matches) > 1:
                # Multiple close matches - need user disambiguation
                print(f"\nAmbiguous match for '{search_name}':")
                for i, (key, score) in enumerate(close_matches, 1):
                    vdata = self.vendors['vendors'][key]
                    print(f"  {i}. {vdata.get('display_name', key)} ({score}% match)")
                
                while True:
                    choice = input("Select vendor number (or 0 for new): ").strip()
                    if choice == '0':
                        return None, 'not_found'
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < len(close_matches):
                            chosen_key = close_matches[idx][0]
                            return self.vendors['vendors'][chosen_key], 'fuzzy'
                    except ValueError:
                        pass
                    print("Invalid choice")
            
            return self.vendors['vendors'][best_key], 'fuzzy'
        
        # 4. Check GnuCash vendors directly
        for gv in self.gnucash_vendors:
            if gv['name'].lower() == search_lower:
                return self._gnucash_vendor_to_dict(gv), 'gnucash'
        
        return None, 'not_found'
    
    def _gnucash_vendor_to_dict(self, gv: Dict) -> Dict:
        """Convert GnuCash vendor record to our format."""
        return {
            'gnucash_guid': gv['guid'],
            'gnucash_id': gv['id'],
            'display_name': gv['name'],
            'search_name': gv['name'],
            'addr_name': gv.get('addr_name', ''),
            'addr_line1': gv.get('addr_addr1', ''),
            'addr_line2': f"{gv.get('addr_addr2', '')} {gv.get('addr_addr3', '')}".strip(),
            'phone': gv.get('addr_phone', ''),
            'email': gv.get('addr_email', ''),
            'notes': gv.get('notes', ''),
            'expense_account': None  # Will need to be set
        }
    
def create_new_vendor(self, search_name: str, display_name: str = None) -> str:
    """Enhanced vendor creation with comprehensive address logging.
    
    NOTE: For interactive address entry with full features, use the
    address_lookup_gui.py tool instead. This function provides basic
    Google Places lookup for command-line usage.
    """
    
    logger.info(f"Creating new vendor: search='{search_name}', display='{display_name}'")

    if search_name is None:
        search_name = display_name
    
    print(f"\n{'='*60}")
    print(f"Creating new vendor: {display_name}")
    print('='*60)
    
    # Try Google Places lookup
    logger.debug(f"Starting address lookup for: '{search_name}'")
    address = None
    
    try:
        result = address_lookup.lookup_google_places(search_name)
        if result:
            address = result
            logger.info(f"✅ Address lookup successful for '{search_name}'")
            logger.debug(f"Complete address data found:")
            for key, value in address.items():
                logger.debug(f"  {key}: '{value}'" if value else f"  {key}: <EMPTY>")
    except Exception as e:
        logger.error(f"Address lookup failed: {e}")
    
    if not address:
        logger.warning(f"❌ Address lookup FAILED for '{search_name}' - using empty address")
        address = {}
        
    if address:
        print(f"\nFound address:")
        print(f"  {address.get('name', display_name)}")
        print(f"  {address.get('addr_line1', '')}")
        print(f"  {address.get('addr_line2', '')}")
        if address.get('phone'):
            print(f"  Phone: {address['phone']}")
        
        if not confirm_proceed("Use this address?"):
            logger.info("User rejected found address")
            address = None
    
    if not address:
        print("\nNo address found or rejected.")
        print("For interactive address entry, use: uv run python src/address_lookup_gui.py")
        logger.debug("No address available - offering manual entry")
        if confirm_proceed("Enter address manually (basic entry)?"):
            logger.info("User chose manual address entry")
            print("\nEnter address details (press Enter to skip a field):")
            addr_name = input("Business Name for Address: ").strip()
            addr_line1 = input("Address Line 1 (street): ").strip()
            addr_line2 = input("Address Line 2 (city, state zip): ").strip()
            phone = input("Phone (optional): ").strip()
            
            address = {
                'name': addr_name or display_name,
                'addr_line1': addr_line1,
                'addr_line2': addr_line2,
                'phone': phone,
                'source': 'manual'
            }
            logger.debug(f"Manual address entered: {address}")
        else:
            logger.info("User skipped address entry - using empty address")
            address = {
                'name': display_name,
                'addr_line1': '',
                'addr_line2': '',
                'phone': '',
                'source': 'skipped'
            }
    
    # Log final address data before vendor creation
    logger.info("Final address data prepared for vendor creation:")
    logger.debug(f"  name: '{address.get('name', '')}'")
    logger.debug(f"  addr_line1: '{address.get('addr_line1', '')}'")
    logger.debug(f"  addr_line2: '{address.get('addr_line2', '')}'")
    logger.debug(f"  phone: '{address.get('phone', '')}'")
    logger.debug(f"  source: '{address.get('source', 'unknown')}'")
    
    # Extract and log address components that will be passed to GnuCash
    addr_name = address.get('name', display_name)
    addr_addr1 = address.get('addr_line1', '')
    addr_addr2 = address.get('addr_line2', '')
    addr_phone = address.get('phone', '')
    
    logger.info("Address components mapped for GnuCash create_vendor call:")
    logger.debug(f"  name parameter: '{display_name}'")
    logger.debug(f"  addr_name parameter: '{addr_name}'")
    logger.debug(f"  addr_addr1 parameter: '{addr_addr1}'")
    logger.debug(f"  addr_addr2 parameter: '{addr_addr2}'")
    logger.debug(f"  addr_phone parameter: '{addr_phone}'")
    
    # Check for empty address fields and log warnings
    empty_fields = []
    if not addr_name: empty_fields.append('addr_name')
    if not addr_addr1: empty_fields.append('addr_addr1')
    if not addr_addr2: empty_fields.append('addr_addr2')
    if not addr_phone: empty_fields.append('addr_phone')
    
    if empty_fields:
        logger.warning(f"Empty address fields being passed to GnuCash: {empty_fields}")
    else:
        logger.info("All address fields populated for GnuCash")
    
    # Create vendor in GnuCash with comprehensive logging
    print(f"\nCreating vendor in GnuCash...")
    logger.info(f"Calling gnucash_db.create_vendor for '{display_name}'...")
    logger.debug("create_vendor parameters:")
    logger.debug(f"  name='{display_name}'")
    logger.debug(f"  addr_name='{addr_name}'")
    logger.debug(f"  addr_addr1='{addr_addr1}'")
    logger.debug(f"  addr_addr2='{addr_addr2}'")
    logger.debug(f"  addr_phone='{addr_phone}'")
    
    try:
        vendor_guid = gnucash_db.create_vendor(
            name=display_name,
            addr_name=addr_name,
            addr_addr1=addr_addr1,
            addr_addr2=addr_addr2,
            addr_phone=addr_phone
        )
        logger.info(f"✅ GnuCash vendor created successfully: GUID={vendor_guid}")
    except Exception as e:
        logger.error(f"💥 GnuCash vendor creation FAILED: {e}")
        raise
    
    # Get the assigned vendor ID with verification
    logger.debug("Retrieving vendor record from GnuCash for verification...")
    vendor_record = gnucash_db.find_vendor_by_name(display_name)
    
    if vendor_record:
        vendor_id = vendor_record['id']
        logger.info(f"Vendor record verified in GnuCash: ID={vendor_id}")
        
        # Log what address data is actually stored in GnuCash
        logger.debug("Address data stored in GnuCash database:")
        logger.debug(f"  addr_name: '{vendor_record.get('addr_name', '')}'")
        logger.debug(f"  addr_addr1: '{vendor_record.get('addr_addr1', '')}'")
        logger.debug(f"  addr_addr2: '{vendor_record.get('addr_addr2', '')}'")
        logger.debug(f"  addr_phone: '{vendor_record.get('addr_phone', '')}'")
        
        # Check for address data loss
        stored_fields = {
            'addr_name': vendor_record.get('addr_name', ''),
            'addr_addr1': vendor_record.get('addr_addr1', ''),
            'addr_addr2': vendor_record.get('addr_addr2', ''),
            'addr_phone': vendor_record.get('addr_phone', '')
        }
        
        sent_fields = {
            'addr_name': addr_name,
            'addr_addr1': addr_addr1,
            'addr_addr2': addr_addr2,
            'addr_phone': addr_phone
        }
        
        for field_name, sent_value in sent_fields.items():
            stored_value = stored_fields.get(field_name, '')
            if sent_value and not stored_value:
                logger.error(f"❌ ADDRESS DATA LOST: {field_name} sent='{sent_value}' but stored='{stored_value}'")
            elif sent_value != stored_value:
                logger.warning(f"⚠️  ADDRESS MISMATCH: {field_name} sent='{sent_value}' but stored='{stored_value}'")
            elif sent_value:
                logger.debug(f"✅ ADDRESS MATCH: {field_name} = '{sent_value}'")
                
    else:
        vendor_id = None
        logger.error("❌ CRITICAL: Vendor record NOT FOUND after creation!")
    
    # Build vendor data for JSON with comprehensive logging
    vendor_key = strip_vendor_name(display_name)
    logger.debug(f"Generated vendor key for JSON: '{vendor_key}'")
    
    vendor_data = {
        'display_name': display_name,
        'search_name': search_name,
        'gnucash_guid': vendor_guid,
        'gnucash_id': vendor_id,
        'addr_name': address.get('name', display_name),
        'addr_line1': address.get('addr_line1', ''),
        'addr_line2': address.get('addr_line2', ''),
        'phone': address.get('phone', ''),
        'address_source': address.get('source', 'unknown'),
        'expense_account': expense_acct_name,
        'expense_account_guid': expense_acct_guid
    }
    
    logger.debug("Vendor data prepared for JSON storage:")
    for key, value in vendor_data.items():
        if value:
            logger.debug(f"  {key}: '{value}'")
        else:
            logger.debug(f"  {key}: <EMPTY>")
    
    # Save to JSON database
    logger.debug(f"Saving vendor data to JSON database...")
    self.vendors['vendors'][vendor_key] = vendor_data
    self.save()
    logger.info(f"✅ Vendor data saved to JSON database: key='{vendor_key}'")
    
    # Refresh GnuCash cache
    logger.debug("Refreshing GnuCash vendor cache...")
    self.refresh_gnucash_vendors()
    
    print(f"\n✓ Vendor created: {display_name} (ID: {vendor_id})")
    logger.info(f"🎉 Vendor creation completed successfully: '{display_name}' (ID: {vendor_id}, GUID: {vendor_guid})")
    
    return vendor_data
    
    def add_alias(self, alias: str, vendor_key: str):
        """Add an alias for a vendor."""
        if vendor_key not in self.vendors['vendors']:
            raise ValueError(f"Vendor key not found: {vendor_key}")
        
        self.vendors['aliases'][alias.lower()] = vendor_key
        self.save()
        logger.info(f"Added alias '{alias}' -> '{vendor_key}'")
    
    def list_vendors(self) -> List[Dict]:
        """List all vendors from JSON database."""
        return [
            {'key': k, **v} 
            for k, v in self.vendors.get('vendors', {}).items()
        ]
    
    def update_vendor_address(self, vendor_key: str, address_data: Dict):
        """Update address for a vendor in both JSON and GnuCash."""
        if vendor_key not in self.vendors['vendors']:
            raise ValueError(f"Vendor not found: {vendor_key}")
        
        vendor = self.vendors['vendors'][vendor_key]
        
        # Update JSON
        vendor['addr_name'] = address_data.get('addr_name', vendor.get('addr_name', ''))
        vendor['addr_line1'] = address_data.get('addr_line1', vendor.get('addr_line1', ''))
        vendor['addr_line2'] = address_data.get('addr_line2', vendor.get('addr_line2', ''))
        vendor['phone'] = address_data.get('phone', vendor.get('phone', ''))
        vendor['address_source'] = address_data.get('source', 'updated')
        
        self.save()
        
        # Update GnuCash if we have the GUID
        if vendor.get('gnucash_guid'):
            gnucash_db.update_vendor_address(
                vendor['gnucash_guid'],
                addr_name=vendor['addr_name'],
                addr_addr1=vendor['addr_line1'],
                addr_addr2=vendor['addr_line2'],
                addr_phone=vendor['phone']
            )
        
        logger.info(f"Updated address for vendor: {vendor_key}")

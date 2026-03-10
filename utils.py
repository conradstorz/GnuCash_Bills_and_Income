"""
Utility functions for bill processor.
Name stripping, fuzzy matching, date parsing, etc.
"""

import re
from datetime import datetime, date
from typing import Optional, Tuple, List
from thefuzz import fuzz, process
from loguru import logger

from bill_processor import config


def strip_vendor_name(name: str) -> str:
    """
    Convert a vendor display name to a stripped identifier.
    
    "Acme Electric Co." -> "acme_electric_co"
    "Bob's Plumbing & Heating" -> "bobs_plumbing_heating"
    """
    # Convert to lowercase
    stripped = name.lower()
    
    # Replace common business suffixes
    suffixes = [' inc', ' llc', ' ltd', ' corp', ' co', ' company', ' incorporated']
    for suffix in suffixes:
        if stripped.endswith(suffix):
            stripped = stripped[:-len(suffix)]
    
    # Replace & with 'and'
    stripped = stripped.replace('&', 'and')
    
    # Remove apostrophes
    stripped = stripped.replace("'", "")
    
    # Replace any non-alphanumeric with underscore
    stripped = re.sub(r'[^a-z0-9]+', '_', stripped)
    
    # Remove leading/trailing underscores
    stripped = stripped.strip('_')
    
    # Collapse multiple underscores
    stripped = re.sub(r'_+', '_', stripped)
    
    return stripped


def parse_input_line(line: str) -> Optional[dict]:
    """
    Parse a bill input line.
    
    Format: vendor_name, amount, memo, date
    - memo and date are optional
    - Returns None if line is empty or invalid
    
    Returns dict with keys: vendor_name, amount, memo, date
    """
    line = line.strip()
    
    # Skip empty lines and comments
    if not line or line.startswith('#'):
        return None
    
    # Split by comma
    parts = [p.strip() for p in line.split(',')]
    
    if len(parts) < 2:
        logger.warning(f"Invalid line (need at least name and amount): {line}")
        return None
    
    # Parse vendor name
    vendor_name = parts[0]
    if not vendor_name:
        logger.warning(f"Empty vendor name in line: {line}")
        return None
    
    # Parse amount
    try:
        amount_str = parts[1].replace('$', '').replace(',', '')
        amount = float(amount_str)
    except ValueError:
        logger.warning(f"Invalid amount '{parts[1]}' in line: {line}")
        return None
    
    # Parse memo (optional)
    memo = parts[2] if len(parts) > 2 and parts[2] else config.DEFAULT_MEMO
    
    # Parse date (optional)
    bill_date = date.today()
    if len(parts) > 3 and parts[3]:
        try:
            bill_date = datetime.strptime(parts[3], "%Y-%m-%d").date()
        except ValueError:
            # Try alternate formats
            for fmt in ["%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d"]:
                try:
                    bill_date = datetime.strptime(parts[3], fmt).date()
                    break
                except ValueError:
                    continue
            else:
                logger.warning(f"Invalid date '{parts[3]}', using today")
    
    return {
        'vendor_name': vendor_name,
        'amount': amount,
        'memo': memo,
        'date': bill_date
    }


def fuzzy_match_vendor(
    search_name: str, 
    known_vendors: dict,
    threshold: int = None
) -> Tuple[Optional[str], int, List[Tuple[str, int]]]:
    """
    Find best fuzzy match for a vendor name.
    
    Args:
        search_name: The name to search for
        known_vendors: Dict of {vendor_key: vendor_data} from JSON
        threshold: Minimum score to consider a match (default from config)
    
    Returns:
        Tuple of:
        - Best match vendor key (or None if no match above threshold)
        - Best match score
        - List of (vendor_key, score) for all close matches (for ambiguity detection)
    """
    if threshold is None:
        threshold = config.FUZZY_MATCH_THRESHOLD
    
    if not known_vendors:
        return None, 0, []
    
    # Build list of all names to search against
    # Include display_name, search_name, and any aliases
    name_to_key = {}
    
    for key, data in known_vendors.items():
        # Add the vendor key itself
        name_to_key[key] = key
        
        # Add display name
        if 'display_name' in data:
            name_to_key[data['display_name'].lower()] = key
        
        # Add search name if different
        if 'search_name' in data:
            name_to_key[data['search_name'].lower()] = key
    
    # Also check aliases section if it exists (handled separately in vendor_manager)
    
    search_lower = search_name.lower()
    
    # Find all matches above threshold
    matches = []
    for name, key in name_to_key.items():
        # Use token_set_ratio for better partial matching
        score = fuzz.token_set_ratio(search_lower, name)
        if score >= threshold:
            matches.append((key, score))
    
    # Remove duplicates (same key might match multiple names)
    seen_keys = {}
    for key, score in matches:
        if key not in seen_keys or score > seen_keys[key]:
            seen_keys[key] = score
    
    matches = [(k, s) for k, s in seen_keys.items()]
    matches.sort(key=lambda x: x[1], reverse=True)
    
    if not matches:
        return None, 0, []
    
    best_key, best_score = matches[0]
    
    return best_key, best_score, matches


def format_currency(amount: float) -> str:
    """Format amount as currency string."""
    return f"${amount:,.2f}"


def format_date(d: date) -> str:
    """Format date for display."""
    return d.strftime("%Y-%m-%d")


def print_separator(char: str = "=", width: int = None):
    """Print a separator line."""
    if width is None:
        width = config.TERMINAL_WIDTH
    print(char * width)


def print_header(text: str, char: str = "=", width: int = None):
    """Print a centered header."""
    if width is None:
        width = config.TERMINAL_WIDTH
    print(char * width)
    print(text.center(width))
    print(char * width)


def confirm_proceed(prompt: str = "Proceed?") -> bool:
    """Ask user for Y/N confirmation."""
    while True:
        response = input(f"{prompt} [Y/N]: ").strip().upper()
        if response in ('Y', 'YES'):
            return True
        if response in ('N', 'NO'):
            return False
        print("Please enter Y or N")


def format_address_for_display(vendor_data: dict) -> str:
    """
    Format vendor address for display.
    
    Args:
        vendor_data: Dict with addr_name, addr_line1, addr_line2, phone, email
        
    Returns:
        Multi-line formatted address string
    """
    lines = []
    
    if vendor_data.get('addr_name'):
        lines.append(vendor_data['addr_name'])
    if vendor_data.get('addr_line1'):
        lines.append(vendor_data['addr_line1'])
    if vendor_data.get('addr_line2'):
        lines.append(vendor_data['addr_line2'])
    if vendor_data.get('phone'):
        lines.append(f"Phone: {vendor_data['phone']}")
    if vendor_data.get('email'):
        lines.append(f"Email: {vendor_data['email']}")
    
    return '\n'.join(lines) if lines else "(No address)"


def calculate_distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points in miles.
    Uses Haversine formula.
    """
    import math
    
    R = 3959  # Earth's radius in miles
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

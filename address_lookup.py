"""
Address lookup via Google Places API and OpenStreetMap/Nominatim.
"""

import time
from typing import Optional, Dict, List, Tuple
import requests
from loguru import logger

from bill_processor import config
from bill_processor.utils import calculate_distance_miles
from bill_processor.logging_setup import log_function_entry, log_function_exit, log_api_call, log_error_with_context


class AddressLookupError(Exception):
    """Raised when address lookup fails."""
    pass


def _generate_fuzzy_search_terms(business_name: str) -> List[str]:
    """
    Generate fuzzy search variations from a business name.
    Removes suffixes, numbers, and tries shorter forms.
    
    Args:
        business_name: Original business name
        
    Returns:
        List of search term variations, ordered from most to least specific
    """
    import re
    
    variations = []
    
    # Remove common business suffixes
    suffixes = [
        r'\s+Inc\.?$', r'\s+LLC\.?$', r'\s+Ltd\.?$', r'\s+Corp\.?$',
        r'\s+Corporation$', r'\s+Company$', r'\s+Co\.?$',
        r'\s+Store\s*#?\d*$', r'\s+#\d+$', r'\s+\d+$',
        r'\s+Supercenter$', r'\s+Center$', r'\s+Market$'
    ]
    
    cleaned = business_name
    for suffix in suffixes:
        cleaned = re.sub(suffix, '', cleaned, flags=re.IGNORECASE)
    
    if cleaned != business_name:
        variations.append(cleaned.strip())
    
    # Try first two words for multi-word names
    words = cleaned.split()
    if len(words) > 2:
        variations.append(' '.join(words[:2]))
    
    # Try first word only (brand name)
    if len(words) > 1:
        variations.append(words[0])
    
    return variations


def _filter_results_by_name_match(results: list, original_search: str, min_word_matches: int = 1) -> list:
    """
    Filter search results to keep only those that match multiple words from original search.
    
    Args:
        results: List of search results
        original_search: The original business name searched for
        min_word_matches: Minimum number of words that must match
        
    Returns:
        Filtered list of results
    """
    import re
    
    # Extract meaningful words from original search (2+ chars, not common words)
    search_words = [w.lower() for w in re.findall(r'\b\w{2,}\b', original_search)]
    
    if len(search_words) <= 1:
        # If only one search word, return all results
        return results
    
    filtered = []
    for result in results:
        # Get the name from the result - handle both old and new API structures
        name = result.get('name', '').lower()
        display_name_obj = result.get('displayName', {})
        if isinstance(display_name_obj, dict):
            display_name = display_name_obj.get('text', '').lower()
        else:
            display_name = str(display_name_obj).lower()
        formatted_address = result.get('formatted_address', result.get('formattedAddress', '')).lower()
        
        # Combine all text to search
        combined_text = f"{name} {display_name} {formatted_address}"
        
        # Count how many search words appear in the result
        matches = sum(1 for word in search_words if word in combined_text)
        
        # Keep if at least min_word_matches words match
        if matches >= min_word_matches:
            result['_word_matches'] = matches
            filtered.append(result)
    
    # Sort by number of word matches (descending) and then by distance
    filtered.sort(key=lambda x: (-x.get('_word_matches', 0), x.get('_distance', 999)))
    
    return filtered


def lookup_google_places(business_name: str, locality: str = None, return_all: bool = False, 
                         progress_callback=None) -> Optional[Dict]:
    """
    Search for a business using Google Places API.
    
    Args:
        business_name: Business name to search for
        locality: Location/city to search in (defaults to config.DEFAULT_LOCALITY)
        return_all: If True, returns a list of all results instead of just the best match
        progress_callback: Optional callback function(message: str) to report progress
    
    Returns dict with:
        - name: Business name from Google
        - formatted_address: Full address string
        - addr_line1: Street address
        - addr_line2: City, State ZIP
        - phone: Phone number (if available)
        - lat, lng: Coordinates
        - place_id: Google place ID
        - distance: Distance in miles (if CENTER_LAT/LON configured)
    
    If return_all=True, returns a list of dicts instead.
    Returns None (or empty list) if not found or API error.
    """
    log_function_entry("lookup_google_places", business_name=business_name, locality=locality)
    
    if not config.GOOGLE_PLACES_API_KEY:
        logger.warning("Google Places API key not configured - skipping Google search")
        log_function_exit("lookup_google_places", None)
        return None
    
    if locality is None:
        locality = config.DEFAULT_LOCALITY
        logger.debug(f"Using default locality: {locality}")
    
    # Build search query
    query = f"{business_name} {locality}"
    logger.debug(f"Google Places search query: '{query}'")
    if progress_callback:
        progress_callback(f"Searching Google: {business_name}...")
    
    try:
        # Use new Places API (New) - Text Search endpoint
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': config.GOOGLE_PLACES_API_KEY,
            'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.location,places.id,places.nationalPhoneNumber,places.internationalPhoneNumber,places.addressComponents'
        }
        body = {
            'textQuery': query
        }
        
        # Add location bias if configured
        if config.CENTER_LAT and config.CENTER_LON:
            body['locationBias'] = {
                'circle': {
                    'center': {
                        'latitude': config.CENTER_LAT,
                        'longitude': config.CENTER_LON
                    },
                    'radius': config.SEARCH_RADIUS_MILES * 1609  # Convert to meters
                }
            }
            logger.debug(f"Adding location bias: center=({config.CENTER_LAT},{config.CENTER_LON}), radius={config.SEARCH_RADIUS_MILES} miles")
        
        log_api_call("Google Places (New)", "searchText", query=query[:50])
        response = requests.post(url, headers=headers, json=body, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # New API returns 'places' array instead of 'results'
        results = data.get('places', [])
        logger.debug(f"Google Places API (New) found {len(results)} results")
        
        if not results:
            logger.info("No results from Google Places, trying fuzzy matching")
            fuzzy_terms = _generate_fuzzy_search_terms(business_name)
            
            for fuzzy_term in fuzzy_terms:
                if progress_callback:
                    progress_callback(f"Trying: {fuzzy_term}...")
                logger.debug(f"Trying fuzzy search term: '{fuzzy_term}'")
                fuzzy_query = f"{fuzzy_term} {locality}"
                body['textQuery'] = fuzzy_query
                
                log_api_call("Google Places (New)", "searchText (fuzzy)", query=fuzzy_query[:50])
                response = requests.post(url, headers=headers, json=body, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                results = data.get('places', [])
                if results:
                    logger.info(f"Fuzzy search successful with term '{fuzzy_term}', found {len(results)} results")
                    # Filter to keep only results matching multiple words from original search
                    if len(business_name.split()) > 1:
                        results = _filter_results_by_name_match(results, business_name, min_word_matches=2)
                        if results:
                            logger.info(f"After name filtering: {len(results)} results match multiple words")
                        else:
                            logger.info("Name filtering removed all results, trying next fuzzy term")
                            results = []
                            continue
                    break
            
            if not results:
                logger.info("No results from Google Places even with fuzzy matching")
                log_function_exit("lookup_google_places", None)
                return [] if return_all else None
        
        # Filter by distance if we have center coordinates (use 3x radius)
        if config.CENTER_LAT and config.CENTER_LON:
            logger.debug("Filtering results by distance")
            max_distance = config.SEARCH_RADIUS_MILES * 3  # More permissive
            filtered = []
            for r in results:
                # New API structure: location is in r.location instead of r.geometry.location
                loc = r.get('location', {})
                if loc:
                    dist = calculate_distance_miles(
                        config.CENTER_LAT, config.CENTER_LON,
                        loc.get('latitude', 0), loc.get('longitude', 0)
                    )
                    if dist <= max_distance:
                        r['_distance'] = dist
                        filtered.append(r)
                        # New API: displayName.text instead of name
                        place_name = r.get('displayName', {}).get('text', 'Unknown')
                        logger.debug(f"Including result '{place_name}' at {dist:.1f} miles")
                    else:
                        place_name = r.get('displayName', {}).get('text', 'Unknown')
                        logger.debug(f"Excluding result '{place_name}' at {dist:.1f} miles (too far, max={max_distance})")
            results = sorted(filtered, key=lambda x: x.get('_distance', 999))
            logger.debug(f"After distance filtering: {len(results)} results")
            
            # Take top 20 closest results
            if len(results) > 20:
                logger.debug(f"Limiting to top 20 closest results")
                results = results[:20]
        
        if not results:
            logger.info("No results within search radius")
            log_function_exit("lookup_google_places", None)
            return [] if return_all else None
        
        # If return_all is True, process all results and return them
        if return_all:
            all_results = []
            for r in results:
                # New API structure
                formatted_addr = r.get('formattedAddress', '')
                addr_parts = _parse_formatted_address(formatted_addr)
                
                result = {
                    'name': r.get('displayName', {}).get('text'),
                    'formatted_address': formatted_addr,
                    'addr_line1': addr_parts.get('line1', ''),
                    'addr_line2': addr_parts.get('line2', ''),
                    'phone': r.get('nationalPhoneNumber') or r.get('internationalPhoneNumber'),  # Phone included in search response
                    'lat': r.get('location', {}).get('latitude'),
                    'lng': r.get('location', {}).get('longitude'),
                    'place_id': r.get('id'),
                    'distance': r.get('_distance'),
                    'source': 'google'
                }
                all_results.append(result)
            
            logger.info(f"Google Places lookup returned {len(all_results)} results for '{business_name}'")
            log_function_exit("lookup_google_places", f"{len(all_results)} results")
            return all_results
        
        # Original behavior: return only the best result
        best = results[0]
        place_name = best.get('displayName', {}).get('text')
        place_addr = best.get('formattedAddress')
        logger.debug(f"Selected best result: '{place_name}' at {place_addr}")
        
        # Phone number is now included in the search response
        phone = best.get('nationalPhoneNumber') or best.get('internationalPhoneNumber')
        if not phone and config.GOOGLE_PLACES_API_KEY:
            logger.debug(f"Phone not in search results, would need separate Place Details call")
            phone = _get_google_place_phone(best.get('id'))
            if phone:
                logger.debug(f"Found phone number: {phone}")
            else:
                logger.debug("No phone number found")
        
        # Parse address
        formatted_addr = best.get('formattedAddress', '')
        logger.debug(f"Parsing formatted address: {formatted_addr}")
        addr_parts = _parse_formatted_address(formatted_addr)
        
        result = {
            'name': place_name,
            'formatted_address': formatted_addr,
            'addr_line1': addr_parts.get('line1', ''),
            'addr_line2': addr_parts.get('line2', ''),
            'phone': phone,
            'lat': best.get('location', {}).get('latitude'),
            'lng': best.get('location', {}).get('longitude'),
            'place_id': best.get('id'),
            'source': 'google'
        }
        
        logger.info(f"Google Places lookup successful for '{business_name}': {result['name']}")
        log_function_exit("lookup_google_places", "success")
        return result
        
    except requests.RequestException as e:
        log_error_with_context(e, "Google Places API request failed", business_name=business_name, query=query)
        log_function_exit("lookup_google_places", None)
        return None


def _get_google_place_phone(place_id: str) -> Optional[str]:
    """Get phone number from Google Place Details API."""
    log_function_entry("_get_google_place_phone", place_id=str(place_id)[:20] if place_id else None)
    
    if not place_id or not config.GOOGLE_PLACES_API_KEY:
        logger.debug("Missing place_id or API key for phone lookup")
        log_function_exit("_get_google_place_phone", None)
        return None
    
    # OpenStreetMap returns integer place_id, Google expects string
    # Only Google place IDs work with the Google Places Details API
    if isinstance(place_id, int):
        logger.debug("place_id is from OpenStreetMap (integer), cannot query Google for phone")
        log_function_exit("_get_google_place_phone", None)
        return None
    
    try:
        url = "https://maps.googleapis.com/maps/api/place/details/json"
        params = {
            'place_id': place_id,
            'fields': 'formatted_phone_number',
            'key': config.GOOGLE_PLACES_API_KEY
        }
        
        log_api_call("Google Places", "details", place_id=place_id[:20])
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        phone = data.get('result', {}).get('formatted_phone_number')
        if phone:
            logger.debug(f"Retrieved phone number from Google Places")
            log_function_exit("_get_google_place_phone", "found")
        else:
            logger.debug("No phone number available from Google Places")
            log_function_exit("_get_google_place_phone", None)
        
        return phone
        
    except requests.RequestException as e:
        log_error_with_context(e, "Google Places Details API error", place_id=place_id)
        log_function_exit("_get_google_place_phone", None)
        return None


def lookup_openstreetmap(business_name: str, locality: str = None, return_all: bool = False,
                         progress_callback=None) -> Optional[Dict]:
    """
    Search for a business using OpenStreetMap Nominatim API.
    
    This is the free fallback option.
    
    Args:
        business_name: Business name to search for
        locality: Location/city to search in (defaults to config.DEFAULT_LOCALITY)
        return_all: If True, returns a list of all results instead of just the best match
        progress_callback: Optional callback function(message: str) to report progress
    
    Returns same structure as lookup_google_places.
    If return_all=True, returns a list of dicts instead.
    Returns None (or empty list) if not found or API error.
    """
    log_function_entry("lookup_openstreetmap", business_name=business_name, locality=locality, return_all=return_all)
    
    if locality is None:
        locality = config.DEFAULT_LOCALITY
        logger.debug(f"Using default locality: {locality}")
    
    query = f"{business_name} {locality}"
    logger.debug(f"OpenStreetMap search query: '{query}'")
    if progress_callback:
        progress_callback(f"Searching OpenStreetMap: {business_name}...")
    
    try:
        # Nominatim requires a User-Agent
        headers = {
            'User-Agent': config.OSM_USER_AGENT
        }
        
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': query,
            'format': 'json',
            'addressdetails': 1,
            'limit': 50  # Increased for better coverage
        }
        
        # Add viewbox for location bias (but don't bound to it strictly)
        if config.CENTER_LAT and config.CENTER_LON:
            logger.debug("Adding viewbox for location bias")
            # Create viewbox (rough approximation)
            # 1 degree lat ≈ 69 miles, 1 degree lon varies
            lat_delta = config.SEARCH_RADIUS_MILES / 69
            lon_delta = config.SEARCH_RADIUS_MILES / 54  # Approximate for ~38° latitude
            
            # Remove bounded=1 to allow results outside viewbox
            params['viewbox'] = (
                f"{config.CENTER_LON - lon_delta},{config.CENTER_LAT + lat_delta},"
                f"{config.CENTER_LON + lon_delta},{config.CENTER_LAT - lat_delta}"
            )
            logger.debug(f"Viewbox: {params['viewbox']}")
        
        # Rate limiting - Nominatim requires max 1 request/second
        logger.debug("Rate limiting: waiting 1.1 seconds for Nominatim")
        time.sleep(1.1)
        
        log_api_call("OpenStreetMap Nominatim", "search", query=query[:50])
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        results = response.json()
        
        logger.debug(f"OpenStreetMap found {len(results)} results")
        
        if not results:
            logger.info("No results from OpenStreetMap, trying fuzzy matching")
            fuzzy_terms = _generate_fuzzy_search_terms(business_name)
            
            # Try fuzzy terms with locality first
            for fuzzy_term in fuzzy_terms:
                if progress_callback:
                    progress_callback(f"Trying: {fuzzy_term} (with locality)...")
                logger.debug(f"Trying fuzzy search term: '{fuzzy_term}' with locality")
                fuzzy_query = f"{fuzzy_term} {locality}"
                params['q'] = fuzzy_query
                
                # Rate limiting - Nominatim requires max 1 request/second
                logger.debug("Rate limiting: waiting 1.1 seconds for Nominatim")
                time.sleep(1.1)
                
                log_api_call("OpenStreetMap Nominatim", "search (fuzzy)", query=fuzzy_query[:50])
                response = requests.get(url, params=params, headers=headers, timeout=10)
                response.raise_for_status()
                results = response.json()
                
                if results:
                    logger.info(f"Fuzzy search successful with term '{fuzzy_term}', found {len(results)} results")
                    # Filter to keep only results matching multiple words from original search
                    if len(business_name.split()) > 1:
                        results = _filter_results_by_name_match(results, business_name, min_word_matches=2)
                        if results:
                            logger.info(f"After name filtering: {len(results)} results match multiple words")
                        else:
                            logger.info("Name filtering removed all results, trying next fuzzy term")
                            results = []  # Clear to try next term
                            continue
                    break
            
            # If still no results, try without locality constraint
            if not results:
                if progress_callback:
                    progress_callback("Trying broader search (no locality)...")
                logger.info("Trying search without locality constraint")
                for search_term in [business_name] + fuzzy_terms:
                    if progress_callback:
                        progress_callback(f"Trying: {search_term} (broad)...")
                    logger.debug(f"Trying broad search: '{search_term}'")
                    params['q'] = search_term
                    
                    time.sleep(1.1)
                    log_api_call("OpenStreetMap Nominatim", "search (broad)", query=search_term[:50])
                    response = requests.get(url, params=params, headers=headers, timeout=10)
                    response.raise_for_status()
                    results = response.json()
                    
                    if results:
                        logger.info(f"Broad search successful with '{search_term}', found {len(results)} results")
                        # Filter to keep only results matching multiple words from original search
                        if len(business_name.split()) > 1:
                            results = _filter_results_by_name_match(results, business_name, min_word_matches=2)
                            if results:
                                logger.info(f"After name filtering: {len(results)} results match multiple words")
                            else:
                                logger.info("Name filtering removed all results, trying next search term")
                                results = []
                                continue
                        break
            
            if not results:
                logger.info("No results from OpenStreetMap even with fuzzy and broad matching")
                log_function_exit("lookup_openstreetmap", None)
                return [] if return_all else None
        
        # Filter by distance (use 3x radius for more permissive filtering)
        if config.CENTER_LAT and config.CENTER_LON:
            logger.debug("Filtering results by distance")
            max_distance = config.SEARCH_RADIUS_MILES * 3  # More permissive
            filtered = []
            for r in results:
                lat = float(r.get('lat', 0))
                lon = float(r.get('lon', 0))
                dist = calculate_distance_miles(
                    config.CENTER_LAT, config.CENTER_LON, lat, lon
                )
                if dist <= max_distance:
                    r['_distance'] = dist
                    filtered.append(r)
                    logger.debug(f"Including result at {dist:.1f} miles")
                else:
                    logger.debug(f"Excluding result at {dist:.1f} miles (too far, max={max_distance})")
            results = sorted(filtered, key=lambda x: x.get('_distance', 999))
            logger.debug(f"After distance filtering: {len(results)} results")
            
            # Take top 20 closest results
            if len(results) > 20:
                logger.debug(f"Limiting to top 20 closest results")
                results = results[:20]
        
        if not results:
            logger.info("No results within search radius")
            log_function_exit("lookup_openstreetmap", None)
            return [] if return_all else None
        
        # Helper function to parse a single OSM result
        def parse_osm_result(r):
            address = r.get('address', {})
            
            # Build address lines
            house_number = address.get('house_number', '')
            road = address.get('road', '')
            line1 = f"{house_number} {road}".strip()
            
            city = address.get('city') or address.get('town') or address.get('village', '')
            state = address.get('state', '')
            postcode = address.get('postcode', '')
            
            line2 = f"{city}, {state} {postcode}".strip()
            
            return {
                'name': r.get('display_name', '').split(',')[0],
                'formatted_address': r.get('display_name', ''),
                'addr_line1': line1,
                'addr_line2': line2,
                'phone': None,  # Nominatim doesn't provide phone
                'lat': float(r.get('lat', 0)),
                'lng': float(r.get('lon', 0)),
                'place_id': r.get('place_id'),
                'distance': r.get('_distance'),
                'source': 'openstreetmap'
            }
        
        # If return_all is True, process all results and return them
        if return_all:
            all_results = [parse_osm_result(r) for r in results]
            logger.info(f"OpenStreetMap lookup returned {len(all_results)} results for '{business_name}'")
            log_function_exit("lookup_openstreetmap", f"{len(all_results)} results")
            return all_results
        
        # Original behavior: return only the best result
        best = results[0]
        logger.debug(f"Selected best result: '{best.get('display_name', '')}'")
        result = parse_osm_result(best)
        logger.debug(f"Parsed address: line1='{result['addr_line1']}', line2='{result['addr_line2']}'")
        
        logger.info(f"OpenStreetMap lookup successful for '{business_name}': {result['name']}")
        log_function_exit("lookup_openstreetmap", "success")
        return result
        
    except requests.RequestException as e:
        log_error_with_context(e, "OpenStreetMap API request failed", business_name=business_name, query=query)
        log_function_exit("lookup_openstreetmap", None)
        return None


def parse_address_smart(address: str) -> Dict[str, str]:
    """
    Smart address parser using token scoring approach.
    
    Breaks the address string into tokens, scores each token based on
    what it most likely represents (zip, street, city, state, phone, name),
    then assembles the final address components.
    
    Returns:
        Dict with 'street', 'city', 'state', 'zip', 'phone', 'name', 'line1', 'line2' keys
    """
    import re
    from typing import List, Tuple
    
    log_function_entry("parse_address_smart", address=address[:100] if address else None)
    
    result = {
        'street': '', 'city': '', 'state': '', 'zip': '', 
        'phone': '', 'name': '', 'line1': '', 'line2': ''
    }
    
    if not address:
        log_function_exit("parse_address_smart", "empty")
        return result
    
    # Clean up the address
    address = ' '.join(address.split())
    
    # Remove common suffixes
    for suffix in [', USA', ', US', ', United States', ', usa', ', us']:
        if address.endswith(suffix):
            address = address[:-len(suffix)]
    
    # State definitions
    state_abbrevs = {
        'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
        'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
        'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
        'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
        'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC'
    }
    
    state_names = {
        'ALABAMA': 'AL', 'ALASKA': 'AK', 'ARIZONA': 'AZ', 'ARKANSAS': 'AR',
        'CALIFORNIA': 'CA', 'COLORADO': 'CO', 'CONNECTICUT': 'CT', 'DELAWARE': 'DE',
        'FLORIDA': 'FL', 'GEORGIA': 'GA', 'HAWAII': 'HI', 'IDAHO': 'ID',
        'ILLINOIS': 'IL', 'INDIANA': 'IN', 'IOWA': 'IA', 'KANSAS': 'KS',
        'KENTUCKY': 'KY', 'LOUISIANA': 'LA', 'MAINE': 'ME', 'MARYLAND': 'MD',
        'MASSACHUSETTS': 'MA', 'MICHIGAN': 'MI', 'MINNESOTA': 'MN', 'MISSISSIPPI': 'MS',
        'MISSOURI': 'MO', 'MONTANA': 'MT', 'NEBRASKA': 'NE', 'NEVADA': 'NV',
        'NEW HAMPSHIRE': 'NH', 'NEW JERSEY': 'NJ', 'NEW MEXICO': 'NM', 'NEW YORK': 'NY',
        'NORTH CAROLINA': 'NC', 'NORTH DAKOTA': 'ND', 'OHIO': 'OH', 'OKLAHOMA': 'OK',
        'OREGON': 'OR', 'PENNSYLVANIA': 'PA', 'RHODE ISLAND': 'RI', 'SOUTH CAROLINA': 'SC',
        'SOUTH DAKOTA': 'SD', 'TENNESSEE': 'TN', 'TEXAS': 'TX', 'UTAH': 'UT',
        'VERMONT': 'VT', 'VIRGINIA': 'VA', 'WASHINGTON': 'WA', 'WEST VIRGINIA': 'WV',
        'WISCONSIN': 'WI', 'WYOMING': 'WY'
    }
    
    street_suffixes = {
        'STREET', 'ST', 'AVENUE', 'AVE', 'ROAD', 'RD', 'BOULEVARD', 'BLVD',
        'DRIVE', 'DR', 'LANE', 'LN', 'COURT', 'CT', 'CIRCLE', 'CIR',
        'PARKWAY', 'PKWY', 'WAY', 'PLACE', 'PL', 'TRAIL', 'TRL',
        'HIGHWAY', 'HWY', 'PIKE', 'RUN', 'LOOP', 'PATH'
    }
    
    # Split by commas first to get major segments
    segments = [s.strip() for s in address.split(',') if s.strip()]
    
    # Score each segment
    segment_scores = []
    for seg_idx, segment in enumerate(segments):
        tokens = segment.split()
        score = {
            'segment': segment,
            'index': seg_idx,
            'is_zip': 0,
            'is_street': 0,
            'is_state': 0,
            'is_city': 0,
            'is_phone': 0,
            'is_name': 0,
            'tokens': tokens
        }
        
        # Check for ZIP code (5 digits or 5+4)
        if re.search(r'\b\d{5}(-\d{4})?\b', segment):
            score['is_zip'] = 100
            # Extract the ZIP
            zip_match = re.search(r'\b(\d{5}(-\d{4})?)\b', segment)
            if zip_match:
                score['zip_value'] = zip_match.group(1)
        
        # Check for phone number
        phone_patterns = [
            r'\(\d{3}\)\s*\d{3}-\d{4}',  # (123) 456-7890
            r'\d{3}-\d{3}-\d{4}',         # 123-456-7890
            r'\d{3}\.\d{3}\.\d{4}',       # 123.456.7890
            r'\d{10}'                      # 1234567890
        ]
        for pattern in phone_patterns:
            if re.search(pattern, segment):
                score['is_phone'] = 100
                break
        
        # Check for state (abbreviation or full name)
        segment_upper = segment.upper()
        tokens_upper = [t.upper() for t in tokens]
        
        for token in tokens_upper:
            if token in state_abbrevs:
                score['is_state'] = 90
                score['state_value'] = token
                break
            if token in state_names:
                score['is_state'] = 90
                score['state_value'] = state_names[token]
                break
        
        # Check for multi-word state names
        if score['is_state'] == 0:
            for i in range(len(tokens) - 1):
                two_word = f"{tokens_upper[i]} {tokens_upper[i + 1]}"
                if two_word in state_names:
                    score['is_state'] = 90
                    score['state_value'] = state_names[two_word]
                    break
        
        # Check for street address (contains number + street suffix)
        has_number = any(re.search(r'\d+', token) for token in tokens)
        has_street_suffix = any(token.upper() in street_suffixes for token in tokens)
        
        if has_number:
            score['is_street'] += 40
            if has_street_suffix:
                score['is_street'] += 40
            elif len(tokens) >= 2:  # Number + street name without suffix
                score['is_street'] += 20
        
        # Check for city (proper noun, not a state, no numbers)
        if not has_number and score['is_state'] == 0 and score['is_zip'] == 0:
            # Likely a city if it's a proper noun
            if tokens and tokens[0][0].isupper():
                score['is_city'] = 30 + (len(tokens) * 10)  # Multi-word cities get higher score
        
        # Check for business name (at the beginning, proper nouns)
        if seg_idx == 0:
            if tokens and tokens[0][0].isupper() and not has_number:
                score['is_name'] = 50 + (len(tokens) * 5)
        
        segment_scores.append(score)
        logger.debug(f"Segment {seg_idx} '{segment}': zip={score['is_zip']}, street={score['is_street']}, "
                    f"state={score['is_state']}, city={score['is_city']}, phone={score['is_phone']}, name={score['is_name']}")
    
    # Extract components based on highest scores
    # ZIP code - prefer segments that ONLY contain ZIP (not mixed with street number)
    zip_segments = [s for s in segment_scores if s['is_zip'] > 50]
    if zip_segments:
        # Prefer pure ZIP segments (high zip score, low street score)
        pure_zip = [s for s in zip_segments if s['is_street'] < 50]
        if pure_zip:
            result['zip'] = pure_zip[-1].get('zip_value', '')  # Take last (most likely to be actual ZIP)
        else:
            result['zip'] = zip_segments[-1].get('zip_value', '')
    
    # Phone
    phone_segments = [s for s in segment_scores if s['is_phone'] > 50]
    if phone_segments:
        result['phone'] = phone_segments[0]['segment']
    
    # State
    state_segments = [s for s in segment_scores if s['is_state'] > 50]
    if state_segments:
        result['state'] = state_segments[0].get('state_value', '')
    
    # Street address - combine consecutive segments that together form an address
    # Look for: number segment + street name segment, or complete street address
    street_segments = sorted([s for s in segment_scores if s['is_street'] > 20], 
                            key=lambda x: x['is_street'], reverse=True)
    
    if street_segments:
        best_street = street_segments[0]
        result['street'] = best_street['segment']
        
        # Check if previous segment is just a number (house number separated by comma)
        if best_street['index'] > 0:
            prev_seg = segment_scores[best_street['index'] - 1]
            # If previous segment is ONLY digits (house number), combine them
            if prev_seg['segment'].isdigit():
                result['street'] = f"{prev_seg['segment']} {best_street['segment']}"
                logger.debug(f"Combined house number with street: {result['street']}")
    
    # If we only found a number as street, look for street name in next segment
    if result['street'] and result['street'].isdigit():
        street_num_idx = next((s['index'] for s in segment_scores if s['segment'] == result['street']), -1)
        if street_num_idx >= 0 and street_num_idx < len(segment_scores) - 1:
            next_seg = segment_scores[street_num_idx + 1]
            # If next segment looks like a street name (no zip, no state, has city-like score or neutral)
            if (next_seg['is_zip'] == 0 and next_seg['is_state'] == 0 and 
                not next_seg['segment'].isdigit()):
                result['street'] = f"{result['street']} {next_seg['segment']}"
                logger.debug(f"Extended street number with name: {result['street']}")
                # Remove this segment from city consideration
                next_seg['is_city'] = 0
    
    # City - segment with high city score that's not street or state
    # Track which segments are already used
    used_segments = set()
    if result['street']:
        # Mark segments used in street
        for s in segment_scores:
            if s['segment'] in result['street']:
                used_segments.add(s['index'])
    
    city_candidates = [s for s in segment_scores 
                      if s['is_city'] > 20 
                      and s['index'] not in used_segments
                      and s['is_state'] < 50
                      and s['is_zip'] == 0]
    if city_candidates:
        # Prefer city that comes after street but before state
        street_idx = max([s['index'] for s in segment_scores if s['index'] in used_segments], default=-1)
        state_idx = next((s['index'] for s in segment_scores if s['is_state'] > 50), 999)
        
        between_candidates = [c for c in city_candidates if street_idx < c['index'] < state_idx]
        if between_candidates:
            # Prefer higher-scored cities, but avoid "County" names if there's a better option
            non_county = [c for c in between_candidates if 'county' not in c['segment'].lower()]
            if non_county:
                result['city'] = sorted(non_county, key=lambda x: x['is_city'], reverse=True)[0]['segment']
            else:
                result['city'] = between_candidates[0]['segment']
        else:
            result['city'] = city_candidates[0]['segment']
    
    # Business name - first segment if it has high name score
    if segment_scores and segment_scores[0]['is_name'] > 30:
        result['name'] = segment_scores[0]['segment']
    
    # Build line1 and line2
    result['line1'] = result['street']
    line2_parts = []
    if result['city']:
        line2_parts.append(result['city'])
    if result['state']:
        if line2_parts:
            line2_parts.append(result['state'])
        else:
            line2_parts.append(result['state'])
    if result['zip']:
        line2_parts.append(result['zip'])
    
    if len(line2_parts) >= 2 and result['state']:
        # Format: "City, State ZIP"
        city_part = ', '.join([p for p in line2_parts if p != result['state'] and p != result['zip']])
        if city_part and result['state'] and result['zip']:
            result['line2'] = f"{city_part}, {result['state']} {result['zip']}"
        elif city_part and result['state']:
            result['line2'] = f"{city_part}, {result['state']}"
        else:
            result['line2'] = ' '.join(line2_parts)
    else:
        result['line2'] = ' '.join(line2_parts)
    
    logger.debug(f"Parsed: street='{result['street']}', city='{result['city']}', "
                f"state='{result['state']}', zip='{result['zip']}', name='{result['name']}'")
    log_function_exit("parse_address_smart", "success")
    return result


def parse_address(address: str) -> Dict[str, str]:
    """
    Robust address parser that handles multiple formats.
    
    Handles formats like:
    - "123 Main St, City, State ZIP" (Standard format)
    - "Business Name, 123 Main St, City, State ZIP, Country" (OSM display_name)
    - "123 Main Street, City State ZIP"
    - Various other comma-separated formats
    
    Returns:
        Dict with 'street', 'city', 'state', 'zip', 'line1', 'line2' keys
    """
    import re
    
    log_function_entry("parse_address", address=address[:100] if address else None)
    
    result = {'street': '', 'city': '', 'state': '', 'zip': '', 'line1': '', 'line2': ''}
    
    if not address:
        logger.debug("Empty address provided")
        log_function_exit("parse_address", "empty")
        return result
    
    # Remove extra whitespace
    address = ' '.join(address.split())
    
    # Split by commas first
    parts = [p.strip() for p in address.split(',') if p.strip()]
    
    # Remove "USA", "US", "United States" from end
    if parts and parts[-1].lower() in ('usa', 'us', 'united states'):
        parts = parts[:-1]
    
    if not parts:
        log_function_exit("parse_address", "no parts")
        return result
    
    # Extract ZIP code from the last parts (more likely to be actual ZIP)
    # Search backwards to avoid street numbers
    for part in reversed(parts):
        zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', part)
        if zip_match:
            result['zip'] = zip_match.group(1)
            logger.debug(f"Found ZIP: {result['zip']}")
            break
    
    # Common US state abbreviations and full names (uppercase for comparison)
    states = {
        'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
        'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
        'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
        'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
        'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY', 'DC'
    }
    
    # Map full state names to abbreviations
    state_names = {
        'ALABAMA': 'AL', 'ALASKA': 'AK', 'ARIZONA': 'AZ', 'ARKANSAS': 'AR',
        'CALIFORNIA': 'CA', 'COLORADO': 'CO', 'CONNECTICUT': 'CT', 'DELAWARE': 'DE',
        'FLORIDA': 'FL', 'GEORGIA': 'GA', 'HAWAII': 'HI', 'IDAHO': 'ID',
        'ILLINOIS': 'IL', 'INDIANA': 'IN', 'IOWA': 'IA', 'KANSAS': 'KS',
        'KENTUCKY': 'KY', 'LOUISIANA': 'LA', 'MAINE': 'ME', 'MARYLAND': 'MD',
        'MASSACHUSETTS': 'MA', 'MICHIGAN': 'MI', 'MINNESOTA': 'MN', 'MISSISSIPPI': 'MS',
        'MISSOURI': 'MO', 'MONTANA': 'MT', 'NEBRASKA': 'NE', 'NEVADA': 'NV',
        'NEW HAMPSHIRE': 'NH', 'NEW JERSEY': 'NJ', 'NEW MEXICO': 'NM', 'NEW YORK': 'NY',
        'NORTH CAROLINA': 'NC', 'NORTH DAKOTA': 'ND', 'OHIO': 'OH', 'OKLAHOMA': 'OK',
        'OREGON': 'OR', 'PENNSYLVANIA': 'PA', 'RHODE ISLAND': 'RI', 'SOUTH CAROLINA': 'SC',
        'SOUTH DAKOTA': 'SD', 'TENNESSEE': 'TN', 'TEXAS': 'TX', 'UTAH': 'UT',
        'VERMONT': 'VT', 'VIRGINIA': 'VA', 'WASHINGTON': 'WA', 'WEST VIRGINIA': 'WV',
        'WISCONSIN': 'WI', 'WYOMING': 'WY'
    }
    
    # Find the street address (part containing numbers)
    street_idx = None
    for idx, part in enumerate(parts):
        if re.search(r'\d+', part):  # Contains a number
            street_idx = idx
            result['street'] = part
            logger.debug(f"Found street at index {idx}: {part}")
            break
    
    # If no street found with numbers, use first part
    if street_idx is None and parts:
        street_idx = 0
        result['street'] = parts[0]
        logger.debug(f"No numbered street found, using first part: {parts[0]}")
    
    # Find state in remaining parts
    state_idx = None
    for idx in range(street_idx + 1 if street_idx is not None else 0, len(parts)):
        part_upper = parts[idx].upper()
        part_words = part_upper.split()
        
        # Check for state abbreviations in words
        for word in part_words:
            if word in states:
                result['state'] = word
                state_idx = idx
                logger.debug(f"Found state abbreviation at index {idx}: {word}")
                break
        
        # Check each word against state names
        if state_idx is None:
            for word in part_words:
                if word in state_names:
                    result['state'] = state_names[word]
                    state_idx = idx
                    logger.debug(f"Found state name at index {idx}: {word} -> {result['state']}")
                    break
        
        # Check for multi-word state names (e.g., "New York", "North Carolina")
        if state_idx is None:
            for i in range(len(part_words) - 1):
                two_word = f"{part_words[i]} {part_words[i + 1]}"
                if two_word in state_names:
                    result['state'] = state_names[two_word]
                    state_idx = idx
                    logger.debug(f"Found two-word state name at index {idx}: {two_word} -> {result['state']}")
                    break
        
        if state_idx is not None:
            break
    
    # Extract city based on position relative to street and state
    if state_idx is not None and street_idx is not None:
        # City is between street and state
        if state_idx == street_idx + 1:
            # State is in same part as city - "City State ZIP" or just in next part
            # Check if current part has both city and state
            city_state_part = parts[state_idx]
            city_words = []
            for word in city_state_part.split():
                if word.upper() not in states and not re.match(r'\d{5}', word):
                    city_words.append(word)
            if city_words:
                result['city'] = ' '.join(city_words)
                logger.debug(f"Found city in same part as state: {result['city']}")
        elif state_idx > street_idx + 1:
            # City is in the part between street and state
            result['city'] = parts[street_idx + 1]
            logger.debug(f"Found city between street and state: {result['city']}")
    elif street_idx is not None and len(parts) > street_idx + 1:
        # No state found, use part after street as city
        candidate_city = parts[street_idx + 1]
        # Remove any state abbreviations from it
        city_words = []
        for word in candidate_city.split():
            if word.upper() not in states and not re.match(r'\d{5}', word):
                city_words.append(word)
        if city_words:
            result['city'] = ' '.join(city_words)
            logger.debug(f"Found city after street (no state): {result['city']}")
    
    # Build line1 and line2
    result['line1'] = result['street']
    line2_parts = []
    if result['city']:
        line2_parts.append(result['city'])
    if result['state']:
        if line2_parts:
            line2_parts.append(result['state'])
        else:
            line2_parts.append(result['state'])
    if result['zip']:
        line2_parts.append(result['zip'])
    
    if len(line2_parts) >= 2 and line2_parts[-2] in states:
        # Format: "City, State ZIP"
        result['line2'] = f"{', '.join(line2_parts[:-2])}, {line2_parts[-2]} {line2_parts[-1]}" if len(line2_parts) > 2 else f"{line2_parts[-2]} {line2_parts[-1]}"
    else:
        result['line2'] = ' '.join(line2_parts)
    
    logger.debug(f"Parsed address: street='{result['street']}', city='{result['city']}', state='{result['state']}', zip='{result['zip']}'")
    log_function_exit("parse_address", "success")
    return result


def _parse_formatted_address(address: str) -> Dict[str, str]:
    """
    Parse a formatted address string into granular components.
    
    Now uses the smart scoring-based parser.
    Maintained for backward compatibility.
    """
    return parse_address_smart(address)


# Original implementation preserved for reference
def _parse_formatted_address_original(address: str) -> Dict[str, str]:
    """
    Parse a formatted address string into granular components.
    
    "123 Main St, Louisville, KY 40201, USA" ->
    {
        'street': '123 Main St',
        'city': 'Louisville',
        'state': 'KY',
        'zip': '40201',
        'line1': '123 Main St',
        'line2': 'Louisville, KY 40201'
    }
    
    Returns both granular components (street, city, state, zip) and
    traditional line1/line2 format for compatibility.
    """
    log_function_entry("_parse_formatted_address", address=address[:50] if address else None)
    
    result = {'street': '', 'city': '', 'state': '', 'zip': '', 'line1': '', 'line2': ''}
    
    if not address:
        logger.debug("Empty address provided")
        log_function_exit("_parse_formatted_address", "empty")
        return result
    
    # Remove country suffix if present
    parts = [p.strip() for p in address.split(',')]
    
    # Remove "USA", "US", "United States" from end
    if parts and parts[-1].lower() in ('usa', 'us', 'united states'):
        parts = parts[:-1]
    
    if len(parts) >= 3:
        # Format: "123 Main St, City, State ZIP"
        street = parts[0]
        city = parts[1]
        
        # Parse state and ZIP from last part ("KY 40201" or "Kentucky 40201")
        last_part = parts[2].strip()
        state = ''
        zip_code = ''
        
        # Split on whitespace to separate state from ZIP
        last_parts = last_part.split()
        if len(last_parts) >= 2:
            state = last_parts[0]
            zip_code = last_parts[1]
        elif len(last_parts) == 1:
            # Could be just state or just ZIP
            if last_parts[0].isdigit() or '-' in last_parts[0]:
                zip_code = last_parts[0]
            else:
                state = last_parts[0]
        
        result = {
            'street': street,
            'city': city,
            'state': state,
            'zip': zip_code,
            'line1': street,
            'line2': f"{city}, {state} {zip_code}".strip()
        }
        
    elif len(parts) == 2:
        # Format: "123 Main St, Louisville"
        result = {
            'street': parts[0],
            'city': parts[1],
            'state': '',
            'zip': '',
            'line1': parts[0],
            'line2': parts[1]
        }
    else:
        # Just one part - treat as street
        result = {
            'street': address,
            'city': '',
            'state': '',
            'zip': '',
            'line1': address,
            'line2': ''
        }
    
    logger.debug(f"Parsed address: street='{result['street']}', city='{result['city']}', state='{result['state']}', zip='{result['zip']}'")
    log_function_exit("_parse_formatted_address", "success")
    return result




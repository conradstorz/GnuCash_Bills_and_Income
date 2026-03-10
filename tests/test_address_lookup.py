"""
Tests for address lookup functionality in address_lookup.py

Note: API lookup functions are tested with mocking to avoid actual API calls.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from hypothesis import given, strategies as st, settings

from bill_processor.address_lookup import (
    AddressLookupError,
    _parse_formatted_address,
    _get_google_place_phone
)
from bill_processor.utils import format_address_for_display


class TestParseFormattedAddress:
    """Test _parse_formatted_address() function"""
    
    def test_full_us_address(self):
        """Test parsing full US address"""
        address = "123 Main St, Springfield, IL 62701, USA"
        result = _parse_formatted_address(address)
        
        # Test legacy line1/line2 format
        assert result['line1'] == "123 Main St"
        assert "Springfield" in result['line2']
        assert "IL 62701" in result['line2']
        
        # Test new granular fields
        assert result['street'] == "123 Main St"
        assert result['city'] == "Springfield"
        assert result['state'] == "IL"
        assert result['zip'] == "62701"
    
    def test_address_without_country(self):
        """Test parsing address without country suffix"""
        address = "456 Oak Ave, Louisville, KY 40205"
        result = _parse_formatted_address(address)
        
        # Test legacy format
        assert result['line1'] == "456 Oak Ave"
        assert "Louisville" in result['line2']
        
        # Test granular fields
        assert result['street'] == "456 Oak Ave"
        assert result['city'] == "Louisville"
        assert result['state'] == "KY"
        assert result['zip'] == "40205"
    
    def test_two_part_address(self):
        """Test parsing simple two-part address"""
        address = "789 Elm St, Chicago"
        result = _parse_formatted_address(address)
        
        # Test legacy format
        assert result['line1'] == "789 Elm St"
        assert result['line2'] == "Chicago"
        
        # Test granular fields
        assert result['street'] == "789 Elm St"
        assert result['city'] == "Chicago"
        assert result['state'] == ""
        assert result['zip'] == ""
    
    def test_single_part_address(self):
        """Test parsing single-line address"""
        address = "123 Main Street"
        result = _parse_formatted_address(address)
        
        # Test legacy format
        assert result['line1'] == "123 Main Street"
        assert result['line2'] == ""
        
        # Test granular fields
        assert result['street'] == "123 Main Street"
        assert result['city'] == ""
        assert result['state'] == ""
        assert result['zip'] == ""
    
    def test_empty_address(self):
        """Test parsing empty address"""
        result = _parse_formatted_address("")
        
        # Test all fields are empty
        assert result['line1'] == ""
        assert result['line2'] == ""
        assert result['street'] == ""
        assert result['city'] == ""
        assert result['state'] == ""
        assert result['zip'] == ""
    
    def test_removes_usa_suffix(self):
        """Test that USA suffix is removed"""
        address1 = "123 Main St, City, State, USA"
        result1 = _parse_formatted_address(address1)
        assert "USA" not in result1['line2']
        
        address2 = "123 Main St, City, State, US"
        result2 = _parse_formatted_address(address2)
        assert "US" not in result2['line2']
        
        address3 = "123 Main St, City, State, United States"
        result3 = _parse_formatted_address(address3)
        assert "United States" not in result3['line2']
    
    def test_strips_whitespace(self):
        """Test that whitespace is stripped from parts"""
        address = "  123 Main St  ,  Springfield  ,  IL  "
        result = _parse_formatted_address(address)
        
        assert result['line1'] == "123 Main St"
        assert not result['line2'].startswith(" ")
        assert not result['line2'].endswith(" ")
    
    def test_zip_code_with_dash(self):
        """Test parsing ZIP+4 format"""
        address = "100 Tech Blvd, San Francisco, CA 94105-1234"
        result = _parse_formatted_address(address)
        
        assert result['street'] == "100 Tech Blvd"
        assert result['city'] == "San Francisco"
        assert result['state'] == "CA"
        assert result['zip'] == "94105-1234"
    
    def test_state_only_no_zip(self):
        """Test parsing address with state but no ZIP"""
        # Note: 'New York' is both a city and state name. Parser identifies it as state.
        # For unambiguous city test, use a different city
        address = "200 Park Ave, Albany, NY"
        result = _parse_formatted_address(address)
        
        assert result['street'] == "200 Park Ave"
        assert result['city'] == "Albany"
        assert result['state'] == "NY"
        assert result['zip'] == ""
    
    def test_zip_only_no_state(self):
        """Test parsing address with ZIP but no state (edge case)"""
        address = "300 Main St, Sometown, 12345"
        result = _parse_formatted_address(address)
        
        assert result['street'] == "300 Main St"
        assert result['city'] == "Sometown"
        assert result['state'] == ""
        assert result['zip'] == "12345"
    
    def test_full_state_name(self):
        """Test parsing with full state name - parser normalizes to abbreviation"""
        address = "400 River Rd, Boston, Massachusetts 02101"
        result = _parse_formatted_address(address)
        
        assert result['street'] == "400 River Rd"
        assert result['city'] == "Boston"
        assert result['state'] == "MA"  # Parser normalizes full state names to abbreviations
        assert result['zip'] == "02101"


class TestFormatAddressForDisplay:
    """Test format_address_for_display() function"""
    
    def test_full_address_display(self):
        """Test displaying full address"""
        address = {
            'addr_name': 'Acme Corp',
            'addr_line1': '123 Main St',
            'addr_line2': 'Springfield, IL 62701',
            'phone': '(555) 123-4567'
        }
        result = format_address_for_display(address)
        
        assert 'Acme Corp' in result
        assert '123 Main St' in result
        assert 'Springfield, IL 62701' in result
        assert '(555) 123-4567' in result
    
    def test_partial_address_display(self):
        """Test displaying partial address (no phone)"""
        address = {
            'addr_name': 'Acme Corp',
            'addr_line1': '123 Main St',
            'addr_line2': 'Springfield, IL 62701'
        }
        result = format_address_for_display(address)
        
        assert 'Acme Corp' in result
        assert '123 Main St' in result
        assert 'Phone' not in result
    
    def test_minimal_address_display(self):
        """Test displaying minimal address (just name and line1)"""
        address = {
            'addr_name': 'Acme Corp',
            'addr_line1': '123 Main St'
        }
        result = format_address_for_display(address)
        
        assert 'Acme Corp' in result
        assert '123 Main St' in result
    
    def test_empty_address_display(self):
        """Test displaying empty address"""
        result = format_address_for_display({})
        assert result == "(No address)"
    
    def test_multiline_format(self):
        """Test that output uses newlines"""
        address = {
            'addr_name': 'Test',
            'addr_line1': 'Line 1',
            'addr_line2': 'Line 2'
        }
        result = format_address_for_display(address)
        
        assert '\n' in result
        lines = result.split('\n')
        assert len(lines) == 3


class TestGooglePlacePhone:
    """Test _get_google_place_phone() with mocking"""
    
    @patch('bill_processor.address_lookup.config.GOOGLE_PLACES_API_KEY', 'test_key')
    @patch('bill_processor.address_lookup.requests.get')
    def test_successful_phone_retrieval(self, mock_get):
        """Test successful phone number retrieval"""
        # Mock successful API response
        mock_response = Mock()
        mock_response.json.return_value = {
            'result': {
                'formatted_phone_number': '(555) 123-4567'
            }
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        phone = _get_google_place_phone('test_place_id')
        
        assert phone == '(555) 123-4567'
        assert mock_get.called
    
    @patch('bill_processor.address_lookup.config.GOOGLE_PLACES_API_KEY', 'test_key')
    @patch('bill_processor.address_lookup.requests.get')
    def test_no_phone_in_response(self, mock_get):
        """Test when API returns no phone number"""
        mock_response = Mock()
        mock_response.json.return_value = {'result': {}}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        phone = _get_google_place_phone('test_place_id')
        
        assert phone is None
    
    @patch('bill_processor.address_lookup.config.GOOGLE_PLACES_API_KEY', None)
    def test_no_api_key(self):
        """Test behavior when API key is not configured"""
        phone = _get_google_place_phone('test_place_id')
        assert phone is None
    
    def test_empty_place_id(self):
        """Test behavior with empty place_id"""
        phone = _get_google_place_phone('')
        assert phone is None
        
        phone = _get_google_place_phone(None)
        assert phone is None
    
    @patch('bill_processor.address_lookup.config.GOOGLE_PLACES_API_KEY', 'test_key')
    @patch('bill_processor.address_lookup.requests.get')
    def test_api_request_exception(self, mock_get):
        """Test handling of API request exceptions"""
        import requests
        mock_get.side_effect = requests.RequestException("API Error")
        
        phone = _get_google_place_phone('test_place_id')
        
        assert phone is None


class TestPropertyBasedAddressLookup:
    """Property-based tests for address lookup functions using Hypothesis"""
    
    @settings(max_examples=1000)
    @given(st.text())
    def test_parse_formatted_address_never_crashes(self, address):
        """Test that _parse_formatted_address never crashes on any text input"""
        try:
            result = _parse_formatted_address(address)
            assert isinstance(result, dict)
            
            # Check legacy fields
            assert 'line1' in result
            assert 'line2' in result
            assert isinstance(result['line1'], str)
            assert isinstance(result['line2'], str)
            
            # Check granular fields
            assert 'street' in result
            assert 'city' in result
            assert 'state' in result
            assert 'zip' in result
            assert isinstance(result['street'], str)
            assert isinstance(result['city'], str)
            assert isinstance(result['state'], str)
            assert isinstance(result['zip'], str)
        except Exception as e:
            pytest.fail(f"_parse_formatted_address crashed on input '{address}': {e}")
    
    @settings(max_examples=1000)
    @given(st.text(min_size=0, max_size=500))
    def test_parse_address_smart_never_crashes(self, address):
        """Test that parse_address_smart never crashes on any text input"""
        from bill_processor.address_lookup import parse_address_smart
        try:
            result = parse_address_smart(address)
            assert isinstance(result, dict)
            assert all(key in result for key in ['street', 'city', 'state', 'zip', 'phone', 'name', 'line1', 'line2'])
            assert all(isinstance(result[key], str) for key in result.keys())
        except Exception as e:
            pytest.fail(f"parse_address_smart crashed on input '{address}': {e}")
    
    @settings(max_examples=500)
    @given(
        street_num=st.integers(min_value=1, max_value=99999),
        street_name=st.text(alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')), min_size=1, max_size=30),
        city=st.text(alphabet=st.characters(whitelist_categories=('Lu', 'Ll')), min_size=1, max_size=30),
        state=st.sampled_from(['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'NY', 'TX', 'IL']),
        zip_code=st.integers(min_value=10000, max_value=99999)
    )
    def test_parse_realistic_addresses(self, street_num, street_name, city, state, zip_code):
        """Test parsing realistic address formats"""
        from bill_processor.address_lookup import parse_address_smart
        
        # Test various realistic formats
        formats = [
            f"{street_num} {street_name}, {city}, {state} {zip_code}",
            f"{street_num} {street_name}, {city}, {state}",
            f"{street_num} {street_name}, {city} {zip_code}",
            f"{street_num} {street_name}\n{city}, {state} {zip_code}",
        ]
        
        for address in formats:
            try:
                result = parse_address_smart(address)
                assert isinstance(result, dict)
                # Parser should extract something, even if not perfect
                assert isinstance(result['street'], str)
                assert isinstance(result['state'], str)
            except Exception as e:
                pytest.fail(f"parse_address_smart crashed on realistic address '{address}': {e}")
    
    @settings(max_examples=500)
    @given(
        zip_code=st.one_of(
            st.integers(min_value=10000, max_value=99999).map(str),  # 5-digit
            st.tuples(
                st.integers(min_value=10000, max_value=99999),
                st.integers(min_value=1000, max_value=9999)
            ).map(lambda x: f"{x[0]}-{x[1]}")  # ZIP+4
        )
    )
    def test_parse_zip_codes(self, zip_code):
        """Test that ZIP codes are correctly identified in various formats"""
        from bill_processor.address_lookup import parse_address_smart
        
        address = f"123 Main St, Anytown, CA {zip_code}"
        try:
            result = parse_address_smart(address)
            # Should extract the zip code
            if result['zip']:
                assert zip_code in result['zip'] or result['zip'] in zip_code
        except Exception as e:
            pytest.fail(f"parse_address_smart crashed on ZIP code '{zip_code}': {e}")
    
    @settings(max_examples=500)
    @given(
        phone=st.one_of(
            st.tuples(st.integers(100, 999), st.integers(100, 999), st.integers(1000, 9999))
              .map(lambda x: f"({x[0]}) {x[1]}-{x[2]}"),
            st.tuples(st.integers(100, 999), st.integers(100, 999), st.integers(1000, 9999))
              .map(lambda x: f"{x[0]}-{x[1]}-{x[2]}"),
            st.tuples(st.integers(100, 999), st.integers(100, 999), st.integers(1000, 9999))
              .map(lambda x: f"{x[0]}.{x[1]}.{x[2]}"),
        )
    )
    def test_parse_phone_numbers(self, phone):
        """Test that phone numbers are correctly identified in various formats"""
        from bill_processor.address_lookup import parse_address_smart
        
        address = f"Acme Corp, {phone}, 123 Main St, Anytown, CA 12345"
        try:
            result = parse_address_smart(address)
            # Should not crash, phone may or may not be extracted depending on position
            assert isinstance(result, dict)
        except Exception as e:
            pytest.fail(f"parse_address_smart crashed on phone number '{phone}': {e}")
    
    @settings(max_examples=500)
    @given(
        text=st.one_of(
            st.text(alphabet=st.characters(blacklist_characters='\x00'), min_size=0, max_size=200),
            st.text(alphabet='0123456789,.- \n\t', min_size=0, max_size=100),
            st.text(alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd', 'Zs')), min_size=0, max_size=200),
        )
    )
    def test_parse_edge_case_inputs(self, text):
        """Test parsing with edge case inputs: numbers only, special chars, unicode, etc."""
        from bill_processor.address_lookup import parse_address_smart
        
        try:
            result = parse_address_smart(text)
            assert isinstance(result, dict)
            assert all(isinstance(result[key], str) for key in result.keys())
        except Exception as e:
            pytest.fail(f"parse_address_smart crashed on edge case '{text[:50]}': {e}")
    
    @settings(max_examples=50)
    @given(st.dictionaries(
        st.sampled_from(['addr_name', 'addr_line1', 'addr_line2', 'phone', 'email']),
        st.text(max_size=100),
        min_size=0,
        max_size=5
    ))
    def test_format_address_for_display_never_crashes(self, address_dict):
        """Test that format_address_for_display never crashes"""
        try:
            result = format_address_for_display(address_dict)
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"format_address_for_display crashed on input {address_dict}: {e}")


class TestAddressLookupError:
    """Test AddressLookupError exception"""
    
    def test_can_raise_error(self):
        """Test that AddressLookupError can be raised and caught"""
        with pytest.raises(AddressLookupError):
            raise AddressLookupError("Test error")
    
    def test_error_message(self):
        """Test that error message is preserved"""
        try:
            raise AddressLookupError("Custom error message")
        except AddressLookupError as e:
            assert str(e) == "Custom error message"


class TestMockedAPILookups:
    """Test API lookup functions with comprehensive mocking"""
    
    @patch('bill_processor.address_lookup.config.GOOGLE_PLACES_API_KEY', 'test_key')
    @patch('bill_processor.address_lookup.config.DEFAULT_LOCALITY', 'Springfield, IL')
    @patch('bill_processor.address_lookup.config.CENTER_LAT', None)
    @patch('bill_processor.address_lookup.config.CENTER_LON', None)
    @patch('bill_processor.address_lookup.requests.post')
    def test_google_places_lookup_success(self, mock_post):
        """Test successful Google Places lookup"""
        from bill_processor.address_lookup import lookup_google_places
        
        # Mock successful API response
        mock_response = Mock()
        mock_response.json.return_value = {
            'places': [{
                'displayName': {'text': 'Acme Electric'},
                'formattedAddress': '123 Main St, Springfield, IL 62701',
                'location': {
                    'latitude': 39.8,
                    'longitude': -89.6
                },
                'id': 'test_place_id_123'
            }]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        result = lookup_google_places("Acme Electric")
        
        assert result is not None
        assert result['name'] == 'Acme Electric'
        assert result['source'] == 'google'
        assert result['place_id'] == 'test_place_id_123'
    
    @patch('bill_processor.address_lookup.config.GOOGLE_PLACES_API_KEY', 'test_key')
    @patch('bill_processor.address_lookup.config.DEFAULT_LOCALITY', 'Springfield, IL')
    @patch('bill_processor.address_lookup.requests.post')
    def test_google_places_no_results(self, mock_post):
        """Test Google Places when no results found"""
        from bill_processor.address_lookup import lookup_google_places
        
        mock_response = Mock()
        mock_response.json.return_value = {
            'places': []
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        result = lookup_google_places("Nonexistent Business")
        
        assert result is None
    
    @patch('bill_processor.address_lookup.config.GOOGLE_PLACES_API_KEY', None)
    def test_google_places_no_api_key(self):
        """Test Google Places when API key not configured"""
        from bill_processor.address_lookup import lookup_google_places
        
        result = lookup_google_places("Test Business")
        
        assert result is None
    
    @patch('bill_processor.address_lookup.config.GOOGLE_PLACES_API_KEY', 'test_key')
    @patch('bill_processor.address_lookup.config.DEFAULT_LOCALITY', 'Louisville, KY')
    @patch('bill_processor.address_lookup.config.CENTER_LAT', None)
    @patch('bill_processor.address_lookup.config.CENTER_LON', None)
    @patch('bill_processor.address_lookup.requests.post')
    def test_google_places_return_all_true(self, mock_post):
        """Test Google Places with return_all=True returns list of all results"""
        from bill_processor.address_lookup import lookup_google_places
        
        # Mock multiple results
        mock_response = Mock()
        mock_response.json.return_value = {
            'places': [
                {
                    'displayName': {'text': 'Home Depot - Main St'},
                    'formattedAddress': '123 Main St, Louisville, KY 40202',
                    'location': {'latitude': 38.25, 'longitude': -85.76},
                    'id': 'place_1'
                },
                {
                    'displayName': {'text': 'Home Depot - Oak Ave'},
                    'formattedAddress': '456 Oak Ave, Louisville, KY 40204',
                    'location': {'latitude': 38.26, 'longitude': -85.75},
                    'id': 'place_2'
                },
                {
                    'displayName': {'text': 'Home Depot - Elm St'},
                    'formattedAddress': '789 Elm St, Louisville, KY 40205',
                    'location': {'latitude': 38.27, 'longitude': -85.74},
                    'id': 'place_3'
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        results = lookup_google_places("Home Depot", return_all=True)
        
        # Should return a list
        assert isinstance(results, list)
        assert len(results) == 3
        
        # Check first result
        assert results[0]['name'] == 'Home Depot - Main St'
        assert results[0]['source'] == 'google'
        assert results[0]['place_id'] == 'place_1'
        
        # Check all results have required fields
        for result in results:
            assert 'name' in result
            assert 'formatted_address' in result
            assert 'addr_line1' in result
            assert 'addr_line2' in result
            assert 'lat' in result
            assert 'lng' in result
            assert 'place_id' in result
            assert result['source'] == 'google'
    
    @patch('bill_processor.address_lookup.config.GOOGLE_PLACES_API_KEY', 'test_key')
    @patch('bill_processor.address_lookup.config.DEFAULT_LOCALITY', 'Louisville, KY')
    @patch('bill_processor.address_lookup.requests.post')
    def test_google_places_return_all_no_results(self, mock_post):
        """Test Google Places with return_all=True when no results found"""
        from bill_processor.address_lookup import lookup_google_places
        
        mock_response = Mock()
        mock_response.json.return_value = {
            'places': []
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        results = lookup_google_places("Nonexistent", return_all=True)
        
        # Should return None when no results with return_all=False
        # But empty list with return_all=True
        assert results is None or results == []
    
    @patch('bill_processor.address_lookup.config.GOOGLE_PLACES_API_KEY', 'test_key')
    @patch('bill_processor.address_lookup.config.DEFAULT_LOCALITY', 'Louisville, KY')
    @patch('bill_processor.address_lookup.config.CENTER_LAT', None)
    @patch('bill_processor.address_lookup.config.CENTER_LON', None)
    @patch('bill_processor.address_lookup.requests.post')
    def test_google_places_return_all_false_returns_single(self, mock_post):
        """Test Google Places with return_all=False returns only best result"""
        from bill_processor.address_lookup import lookup_google_places
        
        # Mock multiple results
        mock_response = Mock()
        mock_response.json.return_value = {
            'places': [
                {
                    'displayName': {'text': 'Best Match'},
                    'formattedAddress': '123 Main St, Louisville, KY 40202',
                    'location': {'latitude': 38.25, 'longitude': -85.76},
                    'id': 'place_1'
                },
                {
                    'displayName': {'text': 'Second Match'},
                    'formattedAddress': '456 Oak Ave, Louisville, KY 40204',
                    'location': {'latitude': 38.26, 'longitude': -85.75},
                    'id': 'place_2'
                }
            ]
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        # Need to mock the phone lookup too
        with patch('bill_processor.address_lookup._get_google_place_phone', return_value=None):
            result = lookup_google_places("Test", return_all=False)
        
        # Should return a dict (single result), not a list
        assert isinstance(result, dict)
        assert result['name'] == 'Best Match'
        assert result['source'] == 'google'


class TestOpenStreetMapLookup:
    """Test lookup_openstreetmap() with mocking"""
    
    @patch('bill_processor.address_lookup.config.DEFAULT_LOCALITY', 'Louisville, KY')
    @patch('bill_processor.address_lookup.config.CENTER_LAT', None)
    @patch('bill_processor.address_lookup.config.CENTER_LON', None)
    @patch('bill_processor.address_lookup.config.OSM_USER_AGENT', 'TestAgent/1.0')
    @patch('bill_processor.address_lookup.time.sleep')  # Skip the rate limiting sleep
    @patch('bill_processor.address_lookup.requests.get')
    def test_openstreetmap_success(self, mock_get, mock_sleep):
        """Test successful OpenStreetMap lookup"""
        from bill_processor.address_lookup import lookup_openstreetmap
        
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                'display_name': 'Acme Corp, 123 Main St, Louisville, KY, USA',
                'lat': '38.2527',
                'lon': '-85.7585',
                'place_id': 'osm_place_123',
                'address': {
                    'house_number': '123',
                    'road': 'Main St',
                    'city': 'Louisville',
                    'state': 'Kentucky',
                    'postcode': '40202'
                }
            }
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        result = lookup_openstreetmap("Acme Corp")
        
        assert result is not None
        assert result['source'] == 'openstreetmap'
        assert 'Main St' in result['addr_line1']
        assert 'Louisville' in result['addr_line2']
        assert result['lat'] == 38.2527
        assert result['lng'] == -85.7585
        
        # Verify rate limiting sleep was called
        assert mock_sleep.called
    
    @patch('bill_processor.address_lookup.config.DEFAULT_LOCALITY', 'Louisville, KY')
    @patch('bill_processor.address_lookup.config.OSM_USER_AGENT', 'TestAgent/1.0')
    @patch('bill_processor.address_lookup.time.sleep')
    @patch('bill_processor.address_lookup.requests.get')
    def test_openstreetmap_no_results(self, mock_get, mock_sleep):
        """Test OpenStreetMap when no results found"""
        from bill_processor.address_lookup import lookup_openstreetmap
        
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        result = lookup_openstreetmap("Nonexistent Business")
        
        assert result is None
    
    @patch('bill_processor.address_lookup.config.DEFAULT_LOCALITY', 'Louisville, KY')
    @patch('bill_processor.address_lookup.config.CENTER_LAT', 38.2527)
    @patch('bill_processor.address_lookup.config.CENTER_LON', -85.7585)
    @patch('bill_processor.address_lookup.config.SEARCH_RADIUS_MILES', 25)
    @patch('bill_processor.address_lookup.config.OSM_USER_AGENT', 'TestAgent/1.0')
    @patch('bill_processor.address_lookup.time.sleep')
    @patch('bill_processor.address_lookup.requests.get')
    def test_openstreetmap_with_distance_filter(self, mock_get, mock_sleep):
        """Test OpenStreetMap with distance filtering"""
        from bill_processor.address_lookup import lookup_openstreetmap
        
        # Mock results - one close, one far
        mock_response = Mock()
        mock_response.json.return_value = [
            {
                'display_name': 'Nearby Business',
                'lat': '38.26',  # Very close to center
                'lon': '-85.76',
                'place_id': 'near',
                'address': {
                    'road': 'Near St',
                    'city': 'Louisville',
                    'state': 'KY',
                    'postcode': '40202'
                }
            },
            {
                'display_name': 'Far Business',
                'lat': '40.0',  # Far from center
                'lon': '-87.0',
                'place_id': 'far',
                'address': {
                    'road': 'Far St',
                    'city': 'Farville',
                    'state': 'KY',
                    'postcode': '99999'
                }
            }
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        result = lookup_openstreetmap("Test Business")
        
        # Should return the nearby result, not the far one
        assert result is not None
        assert 'Near St' in result['addr_line1']
    
    @patch('bill_processor.address_lookup.config.DEFAULT_LOCALITY', 'Louisville, KY')
    @patch('bill_processor.address_lookup.config.OSM_USER_AGENT', 'TestAgent/1.0')
    @patch('bill_processor.address_lookup.time.sleep')
    @patch('bill_processor.address_lookup.requests.get')
    def test_openstreetmap_request_exception(self, mock_get, mock_sleep):
        """Test OpenStreetMap handles request exceptions"""
        from bill_processor.address_lookup import lookup_openstreetmap
        import requests
        
        mock_get.side_effect = requests.RequestException("Network error")
        
        result = lookup_openstreetmap("Test Business")
        
        assert result is None
    
    @patch('bill_processor.address_lookup.config.DEFAULT_LOCALITY', None)
    @patch('bill_processor.address_lookup.config.OSM_USER_AGENT', 'TestAgent/1.0')
    @patch('bill_processor.address_lookup.time.sleep')
    @patch('bill_processor.address_lookup.requests.get')
    def test_openstreetmap_uses_default_locality(self, mock_get, mock_sleep):
        """Test that OpenStreetMap uses DEFAULT_LOCALITY when locality not provided"""
        from bill_processor.address_lookup import lookup_openstreetmap
        
        # Set up to succeed but we just want to check the call
        mock_response = Mock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        # Should not crash even with None locality
        result = lookup_openstreetmap("Test")
        
        # Function should handle None locality gracefully
        assert mock_get.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

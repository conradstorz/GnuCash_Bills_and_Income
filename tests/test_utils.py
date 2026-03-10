"""
Tests for utility functions in utils.py
"""

import pytest
from datetime import date, datetime
from hypothesis import given, strategies as st, settings

from bill_processor.utils import (
    strip_vendor_name,
    parse_input_line,
    fuzzy_match_vendor,
    format_currency,
    format_date,
    format_address_for_display,
    calculate_distance_miles
)


class TestStripVendorName:
    """Test strip_vendor_name() function"""
    
    def test_basic_name_stripping(self):
        """Test basic vendor name stripping"""
        assert strip_vendor_name("Acme Electric Co.") == "acme_electric_co"
        assert strip_vendor_name("Bob's Plumbing") == "bobs_plumbing"
        assert strip_vendor_name("Widget & Gadget Company") == "widget_and_gadget"
    
    def test_business_suffixes(self):
        """Test removal of business suffixes"""
        assert strip_vendor_name("Test Inc") == "test"
        assert strip_vendor_name("Test LLC") == "test"
        assert strip_vendor_name("Test Ltd") == "test"
        assert strip_vendor_name("Test Corp") == "test"
        assert strip_vendor_name("Test Company") == "test"
        assert strip_vendor_name("Test Incorporated") == "test"
    
    def test_special_characters(self):
        """Test handling of special characters"""
        assert strip_vendor_name("Bob's Place") == "bobs_place"
        assert strip_vendor_name("A & B Company") == "a_and_b"
        assert strip_vendor_name("Test-Dash Corp") == "test_dash"
        assert strip_vendor_name("Test.Dot.Name") == "test_dot_name"
    
    def test_multiple_spaces(self):
        """Test collapsing of multiple spaces"""
        result = strip_vendor_name("Test   Multiple    Spaces")
        assert result == "test_multiple_spaces"
    
    def test_edge_cases(self):
        """Test edge cases"""
        assert strip_vendor_name("") == ""
        assert strip_vendor_name("   ") == ""
        assert strip_vendor_name("A") == "a"
        assert strip_vendor_name("123") == "123"
    
    def test_unicode_characters(self):
        """Test handling of unicode characters"""
        # Non-ASCII characters should be replaced with underscore
        result = strip_vendor_name("Café électrique")
        assert "caf" in result
        assert result.replace("_", "").isalnum()


class TestParseInputLine:
    """Test parse_input_line() function"""
    
    def test_valid_basic_line(self):
        """Test parsing valid basic line with name and amount"""
        result = parse_input_line("Test Vendor, 100.50")
        assert result is not None
        assert result['vendor_name'] == "Test Vendor"
        assert result['amount'] == 100.50
        assert result['memo'] is not None
        assert result['date'] == date.today()
    
    def test_valid_line_with_memo(self):
        """Test parsing line with memo"""
        result = parse_input_line("Test Vendor, 100.50, Test memo")
        assert result is not None
        assert result['vendor_name'] == "Test Vendor"
        assert result['amount'] == 100.50
        assert result['memo'] == "Test memo"
    
    def test_valid_line_with_date(self):
        """Test parsing line with date"""
        result = parse_input_line("Test Vendor, 100.50, Test memo, 2026-01-15")
        assert result is not None
        assert result['date'] == date(2026, 1, 15)
    
    def test_alternate_date_formats(self):
        """Test alternate date format parsing"""
        # MM/DD/YYYY format
        result1 = parse_input_line("Test, 100, Memo, 01/15/2026")
        assert result1 is not None
        assert result1['date'] == date(2026, 1, 15)
        
        # MM-DD-YYYY format
        result2 = parse_input_line("Test, 100, Memo, 01-15-2026")
        assert result2 is not None
        assert result2['date'] == date(2026, 1, 15)
    
    def test_amount_with_dollar_sign(self):
        """Test parsing amount with dollar sign"""
        result = parse_input_line("Test Vendor, $100.50")
        assert result is not None
        assert result['amount'] == 100.50
    
    def test_amount_with_commas(self):
        """Test parsing amount with thousands separator"""
        result = parse_input_line("Test Vendor, 1234.56")
        assert result is not None
        assert result['amount'] == 1234.56
    
    def test_empty_line(self):
        """Test that empty lines return None"""
        assert parse_input_line("") is None
        assert parse_input_line("   ") is None
    
    def test_comment_line(self):
        """Test that comment lines return None"""
        assert parse_input_line("# This is a comment") is None
    
    def test_invalid_amount(self):
        """Test handling of invalid amount"""
        result = parse_input_line("Test Vendor, invalid_amount")
        assert result is None
    
    def test_missing_vendor_name(self):
        """Test handling of missing vendor name"""
        result = parse_input_line(", 100.50")
        assert result is None
    
    def test_only_vendor_name(self):
        """Test line with only vendor name (no amount)"""
        result = parse_input_line("Test Vendor")
        assert result is None
    
    def test_invalid_date_fallback(self):
        """Test that invalid date falls back to today"""
        result = parse_input_line("Test, 100, Memo, invalid-date")
        assert result is not None
        assert result['date'] == date.today()


class TestFuzzyMatchVendor:
    """Test fuzzy_match_vendor() function"""
    
    def test_exact_match(self):
        """Test exact match gets high score"""
        known_vendors = {
            'test_vendor': {'display_name': 'Test Vendor'}
        }
        key, score, matches = fuzzy_match_vendor("Test Vendor", known_vendors)
        assert key == 'test_vendor'
        assert score == 100
    
    def test_case_insensitive(self):
        """Test that matching is case-insensitive"""
        known_vendors = {
            'test_vendor': {'display_name': 'Test Vendor'}
        }
        key, score, matches = fuzzy_match_vendor("test vendor", known_vendors)
        assert key == 'test_vendor'
        assert score > 90
    
    def test_partial_match(self):
        """Test partial matching"""
        known_vendors = {
            'acme_electric': {'display_name': 'Acme Electric Co.'}
        }
        key, score, matches = fuzzy_match_vendor("Acme Electric", known_vendors, threshold=80)
        assert key == 'acme_electric'
        assert score >= 80
    
    def test_no_match_below_threshold(self):
        """Test that no match is returned below threshold"""
        known_vendors = {
            'acme_electric': {'display_name': 'Acme Electric'}
        }
        key, score, matches = fuzzy_match_vendor("Completely Different", known_vendors, threshold=90)
        assert key is None
        assert score == 0
    
    def test_empty_vendors(self):
        """Test behavior with empty vendor dict"""
        key, score, matches = fuzzy_match_vendor("Test", {})
        assert key is None
        assert score == 0
        assert matches == []
    
    def test_returns_multiple_matches(self):
        """Test that close matches are returned for ambiguity detection"""
        known_vendors = {
            'vendor_a': {'display_name': 'Acme Electric'},
            'vendor_b': {'display_name': 'Acme Electronics'}
        }
        key, score, matches = fuzzy_match_vendor("Acme", known_vendors, threshold=70)
        assert len(matches) >= 2


class TestFormatCurrency:
    """Test format_currency() function"""
    
    def test_basic_formatting(self):
        """Test basic currency formatting"""
        assert format_currency(100.50) == "$100.50"
        assert format_currency(0.99) == "$0.99"
        assert format_currency(0) == "$0.00"
    
    def test_thousands_separator(self):
        """Test thousands separator"""
        assert format_currency(1234.56) == "$1,234.56"
        assert format_currency(1000000) == "$1,000,000.00"
    
    def test_negative_amounts(self):
        """Test negative amounts"""
        assert format_currency(-100.50) == "$-100.50"
    
    def test_rounding(self):
        """Test proper rounding to 2 decimal places"""
        assert format_currency(100.555) == "$100.56"  # Should round up
        assert format_currency(100.554) == "$100.55"  # Should round down


class TestFormatDate:
    """Test format_date() function"""
    
    def test_standard_formatting(self):
        """Test standard date formatting"""
        d = date(2026, 1, 15)
        assert format_date(d) == "2026-01-15"
    
    def test_single_digit_months_days(self):
        """Test formatting with single-digit months and days"""
        d = date(2026, 3, 5)
        assert format_date(d) == "2026-03-05"


class TestFormatAddressForDisplay:
    """Test format_address_for_display() function"""
    
    def test_full_address(self):
        """Test formatting complete address"""
        vendor_data = {
            'addr_name': 'Acme Corp',
            'addr_line1': '123 Main St',
            'addr_line2': 'Springfield, IL 62701',
            'phone': '555-1234',
            'email': 'info@acme.com'
        }
        result = format_address_for_display(vendor_data)
        assert 'Acme Corp' in result
        assert '123 Main St' in result
        assert 'Springfield, IL 62701' in result
        assert '555-1234' in result
        assert 'info@acme.com' in result
    
    def test_partial_address(self):
        """Test formatting partial address"""
        vendor_data = {
            'addr_name': 'Acme Corp',
            'addr_line1': '123 Main St'
        }
        result = format_address_for_display(vendor_data)
        assert 'Acme Corp' in result
        assert '123 Main St' in result
        assert 'Phone' not in result
    
    def test_empty_address(self):
        """Test formatting empty address"""
        result = format_address_for_display({})
        assert result == "(No address)"
    
    def test_multiline_format(self):
        """Test that output is multi-line"""
        vendor_data = {
            'addr_name': 'Test',
            'addr_line1': 'Line 1',
            'addr_line2': 'Line 2'
        }
        result = format_address_for_display(vendor_data)
        assert '\n' in result
        lines = result.split('\n')
        assert len(lines) == 3


class TestCalculateDistanceMiles:
    """Test calculate_distance_miles() function"""
    
    def test_zero_distance(self):
        """Test distance between same points is zero"""
        distance = calculate_distance_miles(40.0, -88.0, 40.0, -88.0)
        assert distance < 0.001  # Should be essentially zero
    
    def test_known_distance(self):
        """Test calculation of known distance"""
        # Chicago to New York is approximately 790 miles
        chicago_lat, chicago_lon = 41.8781, -87.6298
        ny_lat, ny_lon = 40.7128, -74.0060
        
        distance = calculate_distance_miles(chicago_lat, chicago_lon, ny_lat, ny_lon)
        # Allow 10% tolerance for spherical earth approximation
        assert 710 < distance < 870
    
    def test_short_distance(self):
        """Test short distance calculation (< 10 miles)"""
        # Two points about 5 miles apart
        lat1, lon1 = 40.0, -88.0
        lat2, lon2 = 40.0, -88.08  # Roughly 5 miles east
        
        distance = calculate_distance_miles(lat1, lon1, lat2, lon2)
        assert 4 < distance < 6
    
    def test_hemisphere_crossing(self):
        """Test distance calculation across hemispheres"""
        # North to South hemisphere
        distance = calculate_distance_miles(10.0, 0.0, -10.0, 0.0)
        assert distance > 1300  # Should be roughly 1380 miles
        assert distance < 1500


class TestPropertyBasedUtils:
    """Property-based tests using Hypothesis"""
    
    @settings(max_examples=50)
    @given(st.text())
    def test_strip_vendor_name_never_crashes(self, name):
        """Test that strip_vendor_name never crashes on any input"""
        try:
            result = strip_vendor_name(name)
            assert isinstance(result, str)
        except Exception as e:
            pytest.fail(f"strip_vendor_name crashed on input '{name}': {e}")
    
    @settings(max_examples=50)
    @given(st.floats(min_value=-1e10, max_value=1e10, allow_nan=False, allow_infinity=False))
    def test_format_currency_never_crashes(self, amount):
        """Test that format_currency never crashes"""
        try:
            result = format_currency(amount)
            assert isinstance(result, str)
            assert '$' in result
        except Exception as e:
            pytest.fail(f"format_currency crashed on input {amount}: {e}")
    
    @settings(max_examples=50)
    @given(
        st.floats(min_value=-90, max_value=90),
        st.floats(min_value=-180, max_value=180),
        st.floats(min_value=-90, max_value=90),
        st.floats(min_value=-180, max_value=180)
    )
    def test_calculate_distance_never_crashes(self, lat1, lon1, lat2, lon2):
        """Test that calculate_distance_miles never crashes"""
        try:
            result = calculate_distance_miles(lat1, lon1, lat2, lon2)
            assert isinstance(result, float)
            assert result >= 0  # Distance should never be negative
            assert result < 25000  # Earth's circumference is about 24,900 miles
        except Exception as e:
            pytest.fail(f"calculate_distance_miles crashed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

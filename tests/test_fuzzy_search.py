"""
Test script to demonstrate fuzzy search functionality.
"""

from bill_processor.address_lookup import _generate_fuzzy_search_terms


def test_fuzzy_terms():
    """Test the fuzzy search term generator."""
    
    test_cases = [
        "Walmart Supercenter #1234",
        "Kroger Store #567",
        "Target Inc",
        "McDonald's Corporation",
        "CVS Pharmacy #789",
        "Home Depot",
        "Wendy's Old Fashioned Hamburgers"
    ]
    
    print("Fuzzy Search Term Generator Test")
    print("=" * 60)
    
    for business_name in test_cases:
        variations = _generate_fuzzy_search_terms(business_name)
        print(f"\nOriginal: {business_name}")
        print(f"Variations: {variations}")


if __name__ == "__main__":
    test_fuzzy_terms()

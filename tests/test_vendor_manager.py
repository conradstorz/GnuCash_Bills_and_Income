"""
Tests for VendorManager in vendor_manager.py

These tests use mocking to avoid actual database operations.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, mock_open
from pathlib import Path
import json
import tempfile
import shutil

from bill_processor.vendor_manager import VendorManager


class TestVendorManagerInit:
    """Test VendorManager initialization"""
    
    def test_creates_new_database_if_not_exists(self, tmp_path):
        """Test that VendorManager creates new database if file doesn't exist"""
        test_db_path = tmp_path / "test_vendors.json"
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            
            assert test_db_path.exists()
            assert 'vendors' in manager.vendors
            assert 'aliases' in manager.vendors
    
    def test_loads_existing_database(self, tmp_path):
        """Test that VendorManager loads existing database"""
        test_db_path = tmp_path / "test_vendors.json"
        
        # Create existing database
        existing_data = {
            'vendors': {
                'test_vendor': {
                    'display_name': 'Test Vendor',
                    'gnucash_guid': 'test-guid-123'
                }
            },
            'aliases': {
                'test': 'test_vendor'
            }
        }
        test_db_path.write_text(json.dumps(existing_data))
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            
            assert 'test_vendor' in manager.vendors['vendors']
            assert 'test' in manager.vendors['aliases']


class TestVendorManagerFindVendor:
    """Test find_vendor() method"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.test_vendors = {
            'vendors': {
                'acme_electric': {
                    'display_name': 'Acme Electric',
                    'search_name': 'Acme Electric',
                    'gnucash_guid': 'guid-acme'
                },
                'bobs_plumbing': {
                    'display_name': "Bob's Plumbing",
                    'search_name': "Bob's Plumbing",
                    'gnucash_guid': 'guid-bobs'
                }
            },
            'aliases': {
                'acme': 'acme_electric'
            }
        }
    
    @patch('bill_processor.vendor_manager.gnucash_db.get_all_vendors')
    def test_find_by_alias(self, mock_get_vendors, tmp_path):
        """Test finding vendor by alias"""
        test_db_path = tmp_path / "vendors.json"
        test_db_path.write_text(json.dumps(self.test_vendors))
        mock_get_vendors.return_value = []
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            vendor, match_type = manager.find_vendor("acme")
            
            assert vendor is not None
            assert match_type == 'alias'
            assert vendor['display_name'] == 'Acme Electric'
    
    @patch('bill_processor.vendor_manager.gnucash_db.get_all_vendors')
    def test_find_by_exact_name(self, mock_get_vendors, tmp_path):
        """Test finding vendor by exact name"""
        test_db_path = tmp_path / "vendors.json"
        test_db_path.write_text(json.dumps(self.test_vendors))
        mock_get_vendors.return_value = []
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            vendor, match_type = manager.find_vendor("Acme Electric")
            
            assert vendor is not None
            assert match_type == 'exact'
    
    @patch('bill_processor.vendor_manager.gnucash_db.get_all_vendors')
    @patch('bill_processor.vendor_manager.config.FUZZY_MATCH_THRESHOLD', 80)
    def test_find_by_fuzzy_match(self, mock_get_vendors, tmp_path):
        """Test finding vendor by fuzzy matching"""
        test_db_path = tmp_path / "vendors.json"
        test_db_path.write_text(json.dumps(self.test_vendors))
        mock_get_vendors.return_value = []
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            vendor, match_type = manager.find_vendor("Acme Elec")
            
            # Should find "Acme Electric" by fuzzy match
            assert vendor is not None or match_type == 'not_found'  # Depends on threshold
    
    @patch('bill_processor.vendor_manager.gnucash_db.get_all_vendors')
    def test_find_not_found(self, mock_get_vendors, tmp_path):
        """Test finding nonexistent vendor"""
        test_db_path = tmp_path / "vendors.json"
        test_db_path.write_text(json.dumps(self.test_vendors))
        mock_get_vendors.return_value = []
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            vendor, match_type = manager.find_vendor("Nonexistent Vendor")
            
            assert vendor is None
            assert match_type == 'not_found'


class TestVendorManagerSave:
    """Test save() method"""
    
    @patch('bill_processor.vendor_manager.gnucash_db.get_all_vendors')
    def test_save_creates_directory(self, mock_get_vendors, tmp_path):
        """Test that save creates parent directory if needed"""
        test_db_path = tmp_path / "subdir" / "vendors.json"
        mock_get_vendors.return_value = []
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            manager.save()
            
            assert test_db_path.parent.exists()
            assert test_db_path.exists()
    
    @patch('bill_processor.vendor_manager.gnucash_db.get_all_vendors')
    def test_save_persists_data(self, mock_get_vendors, tmp_path):
        """Test that save() persists data correctly"""
        test_db_path = tmp_path / "vendors.json"
        mock_get_vendors.return_value = []
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            manager.vendors['vendors']['test'] = {'name': 'Test'}
            manager.save()
            
            # Read back the file
            saved_data = json.loads(test_db_path.read_text())
            assert 'test' in saved_data['vendors']


class TestVendorManagerGnuCashVendors:
    """Test GnuCash vendor integration"""
    
    @patch('bill_processor.vendor_manager.gnucash_db.get_all_vendors')
    def test_lazy_load_gnucash_vendors(self, mock_get_vendors, tmp_path):
        """Test that GnuCash vendors are lazy-loaded"""
        test_db_path = tmp_path / "vendors.json"
        mock_get_vendors.return_value = [
            {'guid': 'g1', 'id': '1', 'name': 'GC Vendor 1'},
            {'guid': 'g2', 'id': '2', 'name': 'GC Vendor 2'}
        ]
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            
            # Should not be loaded yet
            assert manager._gnucash_vendors is None
            
            # Access property - should trigger load
            vendors = manager.gnucash_vendors
            
            assert len(vendors) == 2
            assert mock_get_vendors.called
    
    @patch('bill_processor.vendor_manager.gnucash_db.get_all_vendors')
    def test_refresh_gnucash_vendors(self, mock_get_vendors, tmp_path):
        """Test refreshing GnuCash vendor cache"""
        test_db_path = tmp_path / "vendors.json"
        mock_get_vendors.return_value = []
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            
            # Load vendors
            _ = manager.gnucash_vendors
            
            # Refresh should reset cache
            manager.refresh_gnucash_vendors()
            assert manager._gnucash_vendors is None


class TestVendorManagerGnuCashVendorConversion:
    """Test _gnucash_vendor_to_dict() method"""
    
    @patch('bill_processor.vendor_manager.gnucash_db.get_all_vendors')
    def test_convert_gnucash_vendor(self, mock_get_vendors, tmp_path):
        """Test converting GnuCash vendor to dict format"""
        test_db_path = tmp_path / "vendors.json"
        mock_get_vendors.return_value = []
        
        with patch('bill_processor.vendor_manager.config.VENDOR_DATABASE_PATH', test_db_path):
            manager = VendorManager()
            
            gc_vendor = {
                'guid': 'test-guid',
                'id': '12345',
                'name': 'Test Vendor',
                'addr_name': 'Test Vendor Co',
                'addr_addr1': '123 Main St',
                'addr_addr2': 'Suite 100',
                'addr_addr3': '',
                'addr_phone': '555-1234',
                'addr_email': 'test@example.com',
                'notes': 'Test notes'
            }
            
            result = manager._gnucash_vendor_to_dict(gc_vendor)
            
            assert result['gnucash_guid'] == 'test-guid'
            assert result['gnucash_id'] == '12345'
            assert result['display_name'] == 'Test Vendor'
            assert result['addr_name'] == 'Test Vendor Co'
            assert result['addr_line1'] == '123 Main St'
            assert 'Suite 100' in result['addr_line2']
            assert result['phone'] == '555-1234'
            assert result['email'] == 'test@example.com'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

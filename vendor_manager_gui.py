"""
Address Lookup GUI - Standalone tool for managing vendor addresses.

Can be launched standalone or with a vendor name passed as argument.
Use the Save Changes button to persist edits to vendor_database.json.
"""

import sys
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path
from typing import Optional, Dict
from loguru import logger

from bill_processor.vendor_manager import VendorManager
from bill_processor.address_lookup import lookup_google_places, lookup_openstreetmap, _parse_formatted_address, _get_google_place_phone
from bill_processor.logging_setup import setup_logging_for_script, log_function_entry, log_function_exit
from bill_processor.utils import strip_vendor_name


class AddressLookupGUI:
    """GUI for looking up and editing vendor addresses."""
    
    def __init__(self, root: tk.Tk, vendor_name: Optional[str] = None):
        self.root = root
        self.root.title("Address Lookup Tool")
        self.root.geometry("1000x650")
        
        self.vendor_manager = VendorManager()
        self.vendor_key = None
        self.vendor_data = {}
        
        # Track if we're in the middle of loading data (to avoid marking dirty during load)
        self.loading = False
        
        # Track the trace ID for new vendor name changes
        self.name_trace_id = None
        
        # Track whether there are unsaved changes
        self.dirty = False
        
        # Sync vendors from GnuCash to JSON at startup to ensure consistency
        self._initial_sync()
        
        # Create GUI
        self._create_widgets()
        
        # Load vendor if provided
        if vendor_name:
            # Set name and make it read-only since loading existing vendor
            self.name_entry.config(state="normal")
            self.vendor_name_var.set(vendor_name)
            self.name_entry.config(state="readonly")
            self._load_vendor(vendor_name)
    
    def _initial_sync(self):
        """Sync vendors from GnuCash to JSON at startup to catch external changes."""
        try:
            logger.info("Performing initial vendor sync from GnuCash...")
            from bill_processor.vendor_sync import VendorSyncUtility
            
            sync_util = VendorSyncUtility()
            if sync_util.discover_schema():
                # Sync from GnuCash to JSON (quiet mode)
                sync_util.sync_gnucash_to_json()
                # Reload vendor manager to get updated data
                self.vendor_manager = VendorManager()
                logger.info("Initial vendor sync completed")
        except Exception as e:
            logger.warning(f"Initial vendor sync failed: {e}")
            # Continue anyway - this is not critical
    
    
    def _load_vendor_list(self):
        """Load all vendors into the listbox."""
        self.vendor_listbox.delete(0, tk.END)
        
        # Get all vendors sorted by display name
        vendors = []
        for key, data in self.vendor_manager.vendors.get('vendors', {}).items():
            display_name = data.get('display_name', key)
            has_address = bool(data.get('addr_line1'))
            vendors.append((display_name, key, has_address))
        
        vendors.sort(key=lambda x: x[0].lower())
        
        # Store for filtering
        self.all_vendors = vendors
        
        # Add to listbox
        for display_name, key, has_address in vendors:
            indicator = "📍" if has_address else "  "
            self.vendor_listbox.insert(tk.END, f"{indicator} {display_name}")
        
        self.status_var.set(f"Loaded {len(vendors)} vendors")
    
    def _filter_vendors(self, *args):
        """Filter vendor list based on search term."""
        search_term = self.filter_var.get().lower()
        
        self.vendor_listbox.delete(0, tk.END)
        
        for display_name, key, has_address in self.all_vendors:
            if search_term in display_name.lower():
                indicator = "📍" if has_address else "  "
                self.vendor_listbox.insert(tk.END, f"{indicator} {display_name}")
    
    def _on_vendor_selected(self, event):
        """Handle vendor selection from list."""
        selection = self.vendor_listbox.curselection()
        if not selection:
            return
        
        # Warn about unsaved changes before switching
        if self.dirty:
            answer = messagebox.askyesnocancel(
                "Unsaved Changes",
                "You have unsaved changes. Save before switching vendors?"
            )
            if answer is None:  # Cancel
                return
            if answer:  # Yes - save first
                self._save_vendor()
        
        # Remove any active name trace from new vendor creation
        if self.name_trace_id:
            self.vendor_name_var.trace_remove("write", self.name_trace_id)
            self.name_trace_id = None
        
        # Get selected vendor name (strip the indicator)
        selected_text = self.vendor_listbox.get(selection[0])
        vendor_name = selected_text[2:].strip()  # Remove "📍 " or "  " prefix
        
        # Load this vendor and make name field read-only
        self.name_entry.config(state="normal")
        self.vendor_name_var.set(vendor_name)
        self.name_entry.config(state="readonly")
        self._load_vendor(vendor_name)
    
    def _new_vendor(self):
        """Clear fields to create a new vendor and enable name editing."""
        self.loading = True
        
        try:
            # Remove any existing trace first
            if self.name_trace_id:
                self.vendor_name_var.trace_remove("write", self.name_trace_id)
                self.name_trace_id = None
            
            # Enable name field for editing
            self.name_entry.config(state="normal")
            
            self.vendor_name_var.set("")
            self.addr_name_var.set("")
            self.addr_line1_var.set("")
            self.addr_line2_var.set("")
            self.city_var.set("")
            self.state_var.set("")
            self.zip_var.set("")
            self.phone_var.set("")
            self.email_var.set("")
            
            self.vendor_key = None
            self.vendor_data = {}
            
            self.vendor_listbox.selection_clear(0, tk.END)
            self.status_var.set("Enter new vendor details - name field is editable")
            
        finally:
            self.loading = False
        
        # Add trace for name changes only when creating new vendor (after loading=False)
        self.name_trace_id = self.vendor_name_var.trace_add("write", self._on_new_vendor_name_changed)
    
    def _on_new_vendor_name_changed(self, *args):
        """Handle name changes when creating a new vendor."""
        if self.loading:
            return
        
        vendor_name = self.vendor_name_var.get().strip()
        if vendor_name:
            # Create vendor key and initialize
            self.vendor_key = strip_vendor_name(vendor_name)
            if 'display_name' not in self.vendor_data:
                self.vendor_data['display_name'] = vendor_name
                self.vendor_data['search_name'] = vendor_name.lower()
            else:
                # Update display name as user types
                self.vendor_data['display_name'] = vendor_name
                self.vendor_data['search_name'] = vendor_name.lower()
    
    def _create_widgets(self):
        """Create all GUI widgets."""
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill="both", expand=True)
        
        # Create paned window for vendor list and details
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill="both", expand=True)
        
        # Left panel - Vendor List
        left_panel = ttk.Frame(paned)
        paned.add(left_panel, weight=1)
        
        list_label = ttk.Label(left_panel, text="All Vendors", font=("Arial", 10, "bold"))
        list_label.pack(pady=(0, 5))
        
        # Search/filter box for vendor list
        filter_frame = ttk.Frame(left_panel)
        filter_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(filter_frame, text="Filter:").pack(side="left", padx=(0, 5))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", self._filter_vendors)
        ttk.Entry(filter_frame, textvariable=self.filter_var).pack(side="left", fill="x", expand=True)
        
        # Vendor listbox with scrollbar
        list_frame = ttk.Frame(left_panel)
        list_frame.pack(fill="both", expand=True)
        
        scrollbar_vendors = ttk.Scrollbar(list_frame, orient="vertical")
        scrollbar_vendors.pack(side="right", fill="y")
        
        self.vendor_listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar_vendors.set, font=("Arial", 9))
        self.vendor_listbox.pack(side="left", fill="both", expand=True)
        scrollbar_vendors.config(command=self.vendor_listbox.yview)
        
        self.vendor_listbox.bind('<<ListboxSelect>>', self._on_vendor_selected)
        
        # Right panel - Vendor Details
        right_panel = ttk.Frame(paned)
        paned.add(right_panel, weight=2)
        
        # Vendor Name Section
        name_frame = ttk.LabelFrame(right_panel, text="Vendor Name", padding="5")
        name_frame.pack(fill="x", pady=(0, 10))
        
        self.vendor_name_var = tk.StringVar()
        # Removed auto-matching trace - only triggers on field changes for auto-save
        
        ttk.Label(name_frame, text="Name:").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.name_entry = ttk.Entry(name_frame, textvariable=self.vendor_name_var, width=40, state="readonly")
        self.name_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(name_frame, text="Search Web", command=self._search_web).grid(row=0, column=2, padx=(5, 0))
        ttk.Button(name_frame, text="New Vendor", command=self._new_vendor).grid(row=0, column=3, padx=(5, 0))
        
        name_frame.columnconfigure(1, weight=1)
        
        # Address Fields Section
        addr_frame = ttk.LabelFrame(right_panel, text="Address Details", padding="5")
        addr_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # Create entry variables and widgets
        self.addr_name_var = tk.StringVar()
        self.addr_line1_var = tk.StringVar()
        self.addr_line2_var = tk.StringVar()
        self.city_var = tk.StringVar()
        self.state_var = tk.StringVar()
        self.zip_var = tk.StringVar()
        self.phone_var = tk.StringVar()
        self.email_var = tk.StringVar()
        
        # Add trace to all variables for dirty tracking
        for var in [self.addr_name_var, self.addr_line1_var, self.addr_line2_var,
                    self.city_var, self.state_var, self.zip_var, self.phone_var, self.email_var]:
            var.trace_add("write", self._on_field_changed)
        
        fields = [
            ("Address Name:", self.addr_name_var),
            ("Street Address:", self.addr_line1_var),
            ("Address Line 2:", self.addr_line2_var),
            ("City:", self.city_var),
            ("State:", self.state_var),
            ("ZIP Code:", self.zip_var),
            ("Phone:", self.phone_var),
            ("Email:", self.email_var),
        ]
        
        for idx, (label, var) in enumerate(fields):
            ttk.Label(addr_frame, text=label).grid(row=idx, column=0, sticky="w", padx=(0, 5), pady=2)
            ttk.Entry(addr_frame, textvariable=var, width=60).grid(row=idx, column=1, sticky="ew", pady=2)
        
        addr_frame.columnconfigure(1, weight=1)
        
        # Save button
        self.save_button = ttk.Button(addr_frame, text="Save Changes", command=self._save_vendor, state="disabled")
        self.save_button.grid(row=len(fields), column=1, sticky="e", pady=(10, 0))
        
        # Search Results Section (initially hidden)
        self.results_frame = ttk.LabelFrame(right_panel, text="Search Results", padding="5")
        
        # Create frame for listbox and scrollbar
        list_frame = ttk.Frame(self.results_frame)
        list_frame.pack(fill="both", expand=True)
        
        # Scrollbar for results list
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        
        # Listbox for results
        self.results_listbox = tk.Listbox(list_frame, height=8, yscrollcommand=scrollbar.set, font=("Courier", 9))
        self.results_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.results_listbox.yview)
        
        # Bind double-click to use result
        self.results_listbox.bind('<Double-Button-1>', lambda e: self._use_selected_result())
        
        # Button to use selected result
        ttk.Button(self.results_frame, text="Use Selected Result", 
                  command=self._use_selected_result).pack(pady=5)
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(right_panel, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w")
        status_bar.pack(fill="x", side="bottom", pady=(5, 0))
        
        # Store current search results
        self.current_results = []
        
        # Load vendor list
        self._load_vendor_list()
    
    def _load_vendor(self, vendor_name: str):
        """Load vendor data from JSON database."""
        log_function_entry("_load_vendor", vendor_name=vendor_name)
        
        self.loading = True  # Prevent auto-save during load
        
        try:
            # Normalize the vendor name to get the key
            vendor_key = strip_vendor_name(vendor_name)
            
            # Try to find vendor - returns (vendor_data, vendor_key) tuple
            result = self.vendor_manager.find_vendor(vendor_name)
            vendor_data = result[0] if result else None
            
            if vendor_data:
                self.vendor_key = vendor_key
                self.vendor_data = vendor_data
                
                # Populate fields - name is already set and read-only
                self.addr_name_var.set(vendor_data.get('addr_name', ''))
                self.addr_line1_var.set(vendor_data.get('addr_line1', ''))
                self.addr_line2_var.set(vendor_data.get('addr_line2', ''))
                
                # Try to extract city, state, zip from addr_line2 if they're not separate
                city = vendor_data.get('city', '')
                state = vendor_data.get('state', '')
                zip_code = vendor_data.get('zip', '')
                
                self.city_var.set(city)
                self.state_var.set(state)
                self.zip_var.set(zip_code)
                
                self.phone_var.set(vendor_data.get('phone', ''))
                self.email_var.set(vendor_data.get('email', '') or vendor_data.get('addr_email', ''))
                
                self.status_var.set(f"Loaded: {vendor_data.get('display_name', vendor_name)} (read-only name)")
                logger.info(f"Loaded vendor: {vendor_name}")
            else:
                # Vendor not found - shouldn't happen when loading from list
                self.vendor_key = vendor_key
                self.vendor_data = {
                    'display_name': vendor_name,
                    'search_name': vendor_name.lower(),
                }
                self.addr_name_var.set(vendor_name)
                self.status_var.set(f"Vendor not found: {vendor_name}")
                logger.warning(f"Vendor not found: {vendor_name}")
        
        finally:
            self.loading = False
            self.dirty = False
            self.save_button.config(state="disabled")
        
        log_function_exit("_load_vendor")
    
    # Removed _on_name_changed method - no longer needed
    
    def _on_field_changed(self, *args):
        """Mark record as having unsaved changes."""
        if self.loading:
            return
        
        if not self.vendor_key:
            return
        
        if not self.dirty:
            self.dirty = True
            self.save_button.config(state="normal")
            self.status_var.set("Unsaved changes")
    
    def _save_vendor(self):
        """Save the current vendor details to the JSON database and sync to GnuCash."""
        if not self.vendor_key:
            messagebox.showwarning("No Vendor", "Select or create a vendor first.")
            return
        
        # Update vendor_data with current field values
        self.vendor_data['addr_name'] = self.addr_name_var.get()
        self.vendor_data['addr_line1'] = self.addr_line1_var.get()
        self.vendor_data['addr_line2'] = self.addr_line2_var.get()
        self.vendor_data['city'] = self.city_var.get()
        self.vendor_data['state'] = self.state_var.get()
        self.vendor_data['zip'] = self.zip_var.get()
        self.vendor_data['phone'] = self.phone_var.get()
        self.vendor_data['email'] = self.email_var.get()
        
        # Ensure display_name and search_name are set
        if 'display_name' not in self.vendor_data:
            self.vendor_data['display_name'] = self.vendor_name_var.get()
        if 'search_name' not in self.vendor_data:
            self.vendor_data['search_name'] = self.vendor_name_var.get().lower()
        
        # Save to JSON
        self.vendor_manager.vendors['vendors'][self.vendor_key] = self.vendor_data
        self.vendor_manager.save()
        
        # Sync to GnuCash database
        try:
            # Build city, state for addr_addr3
            city = self.vendor_data.get('city', '').strip()
            state = self.vendor_data.get('state', '').strip()
            addr_addr3 = f"{city}, {state}".strip(', ') if city or state else ''
            
            # addr_addr4 is postal code
            addr_addr4 = self.vendor_data.get('zip', '').strip()
            
            if self.vendor_data.get('gnucash_guid'):
                # Vendor exists in GnuCash - update it
                logger.info(f"Syncing vendor changes to GnuCash: {self.vendor_key}")
                from bill_processor import gnucash_db
                gnucash_db.update_vendor_address(
                    vendor_guid=self.vendor_data['gnucash_guid'],
                    addr_name=self.vendor_data.get('addr_name', ''),
                    addr_addr1=self.vendor_data.get('addr_line1', ''),
                    addr_addr2=self.vendor_data.get('addr_line2', ''),
                    addr_addr3=addr_addr3,
                    addr_addr4=addr_addr4,
                    addr_phone=self.vendor_data.get('phone', ''),
                    addr_email=self.vendor_data.get('email', '')
                )
                logger.info(f"Successfully updated vendor in GnuCash: {self.vendor_key}")
            else:
                # Vendor doesn't exist in GnuCash yet - create it
                logger.info(f"Creating new vendor in GnuCash: {self.vendor_key}")
                from bill_processor import gnucash_db
                vendor_guid = gnucash_db.create_vendor(
                    name=self.vendor_data['display_name'],
                    addr_name=self.vendor_data.get('addr_name', ''),
                    addr_addr1=self.vendor_data.get('addr_line1', ''),
                    addr_addr2=self.vendor_data.get('addr_line2', ''),
                    addr_addr3=addr_addr3,
                    addr_addr4=addr_addr4,
                    addr_phone=self.vendor_data.get('phone', ''),
                    addr_email=self.vendor_data.get('email', '')
                )
                # Update JSON with the new GUID
                self.vendor_data['gnucash_guid'] = vendor_guid
                self.vendor_manager.vendors['vendors'][self.vendor_key] = self.vendor_data
                self.vendor_manager.save()
                logger.info(f"Successfully created vendor in GnuCash with GUID: {vendor_guid}")
        except Exception as e:
            logger.error(f"Failed to sync vendor to GnuCash: {e}")
            messagebox.showwarning(
                "Sync Warning",
                f"Vendor saved to JSON but failed to sync to GnuCash:\n{e}\n\n"
                f"Use 'Vendor Sync' tool to sync changes."
            )
        
        self.dirty = False
        self.save_button.config(state="disabled")
        self.status_var.set("Saved and synced to GnuCash")
        logger.debug(f"Saved vendor: {self.vendor_key}")
        
        # Refresh vendor list
        self._load_vendor_list()
    
    def _search_web(self):
        """Search for vendor address using Google Places API with OpenStreetMap fallback."""
        from bill_processor import config
        vendor_name = self.vendor_name_var.get().strip()
        
        if not vendor_name:
            messagebox.showwarning("No Vendor Name", "Please enter a vendor name first.")
            return
        
        # Progress callback to update status
        def update_progress(message: str):
            self.status_var.set(message)
            self.root.update()
        
        # Try Google Places first
        results = None
        source = None
        
        if config.GOOGLE_PLACES_API_KEY:
            update_progress("Searching Google Places...")
            
            try:
                # Call Google Places API with return_all=True to get all results
                results = lookup_google_places(vendor_name, return_all=True, 
                                              progress_callback=update_progress)
                source = "Google Places"
                
            except Exception as e:
                logger.error(f"Error searching Google Places: {e}")
                update_progress("Google failed, trying OpenStreetMap...")
        else:
            logger.info("Google Places API key not configured, using OpenStreetMap")
        
        # Try OpenStreetMap as fallback
        if not results and config.USE_OPENSTREETMAP:
            update_progress("Searching OpenStreetMap...")
            
            try:
                osm_results = lookup_openstreetmap(vendor_name, return_all=True,
                                                  progress_callback=update_progress)
                
                if osm_results:
                    results = osm_results
                    source = "OpenStreetMap"
                    logger.info(f"OpenStreetMap found {len(osm_results)} result(s) for '{vendor_name}'")
                    
            except Exception as e:
                logger.error(f"Error searching OpenStreetMap: {e}")
                update_progress(f"Search error: {e}")
        
        # Handle no results
        if not results:
            self.status_var.set("No results found")
            
            # Provide helpful error message based on configuration
            if not config.GOOGLE_PLACES_API_KEY:
                msg = (f"No results found for '{vendor_name}'.\n\n"
                       "💡 TIP: For better results, configure a Google Places API key:\n"
                       "1. Go to: https://console.cloud.google.com/\n"
                       "2. Create project and enable Places API\n"
                       "3. Create API key in Credentials\n"
                       "4. Add key to config.py (GOOGLE_PLACES_API_KEY)\n\n"
                       "Currently using OpenStreetMap (free but less accurate).\n"
                       "Try a different search term or enter address manually.")
            else:
                msg = (f"No results found for '{vendor_name}'.\n\n"
                       "Try:\n"
                       "• A simpler search term (e.g., 'Kroger' instead of 'Kroger Store #123')\n"
                       "• Just the business name without location\n"
                       "• Or enter the address manually")
            
            messagebox.showinfo("No Results", msg)
            return
        
        # Display results
        self._display_search_results(results)
        self.status_var.set(f"Found {len(results)} result(s) from {source}")
    
    def _display_search_results(self, results: list):
        """Display multiple search results in listbox."""
        # Show results frame
        self.results_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # Store results for later use
        self.current_results = results
        
        # Clear listbox
        self.results_listbox.delete(0, tk.END)
        
        # Add results to listbox
        for idx, result in enumerate(results):
            name = result.get('name', 'N/A')
            address = result.get('formatted_address', 'N/A')
            distance = result.get('distance')
            
            # Format the display string
            if distance is not None:
                display = f"{idx+1}. {name} - {address} ({distance:.1f} mi)"
            else:
                display = f"{idx+1}. {name} - {address}"
            
            self.results_listbox.insert(tk.END, display)
        
        # Select first result by default
        if results:
            self.results_listbox.selection_set(0)
        
        self.status_var.set(f"Found {len(results)} result(s) - select one and click 'Use Selected Result' or double-click")
    
    def _use_selected_result(self):
        """Use the selected result from the listbox."""
        selection = self.results_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a result from the list.")
            return
        
        # Get the selected result
        idx = selection[0]
        if idx >= len(self.current_results):
            return
        
        result = self.current_results[idx]
        
        # Populate fields with this result
        self._use_search_result(result)
    
    def _use_search_result(self, result: Dict):
        """Populate fields with search result."""
        self.loading = True
        
        try:
            # Check if the result already has parsed address components
            # (e.g., from OSM's structured address data)
            if result.get('addr_line1') or result.get('addr_line2'):
                # Use pre-parsed address from the lookup function
                street = result.get('addr_line1', '')
                addr_line2 = result.get('addr_line2', '')
                
                # Parse addr_line2 to get city, state, zip
                # Format is usually "City, State ZIP"
                addr_parts = _parse_formatted_address(addr_line2)
                city = addr_parts.get('city', '')
                state = addr_parts.get('state', '')
                zip_code = addr_parts.get('zip', '')
            else:
                # Parse the formatted_address for all components
                addr_parts = _parse_formatted_address(result.get('formatted_address', ''))
                street = addr_parts.get('street', '')
                city = addr_parts.get('city', '')
                state = addr_parts.get('state', '')
                zip_code = addr_parts.get('zip', '')
            
            # Check for name collision when creating a new vendor
            result_name = result.get('name', self.vendor_name_var.get())
            final_vendor_name = result_name
            
            # If creating a new vendor (name field is editable) and name would collide
            if str(self.name_entry.cget('state')) != 'readonly':
                test_key = strip_vendor_name(result_name)
                
                # Check if this key already exists in the database
                if test_key in self.vendor_manager.vendors.get('vendors', {}):
                    # Name collision - make it unique by appending location
                    location_suffix = None
                    
                    # Try to use city first
                    if city:
                        location_suffix = city
                    # Fall back to street address
                    elif street:
                        # Use just the street name without number for readability
                        import re
                        street_parts = street.split()
                        # Take everything after the first number
                        street_name = ' '.join([p for p in street_parts if not p.isdigit()])
                        location_suffix = street_name.strip()
                    
                    if location_suffix:
                        final_vendor_name = f"{result_name} - {location_suffix}"
                        logger.info(f"Name collision detected. Changed '{result_name}' to '{final_vendor_name}'")
                        
                        # Verify the new name is unique, if not add a number
                        counter = 2
                        test_key = strip_vendor_name(final_vendor_name)
                        while test_key in self.vendor_manager.vendors.get('vendors', {}):
                            final_vendor_name = f"{result_name} - {location_suffix} {counter}"
                            test_key = strip_vendor_name(final_vendor_name)
                            counter += 1
                        
                        self.status_var.set(f"Name collision - renamed to: {final_vendor_name}")
                        logger.info(f"Final unique name: {final_vendor_name}")
                
                # Update vendor name field and create NEW vendor data dictionary
                self.vendor_name_var.set(final_vendor_name)
                self.vendor_key = strip_vendor_name(final_vendor_name)
                # Create a fresh vendor_data dict to avoid modifying existing vendor
                self.vendor_data = {
                    'display_name': final_vendor_name,
                    'search_name': final_vendor_name.lower()
                }
                logger.debug(f"Created new vendor_data for: {final_vendor_name}")
            
            # Populate fields
            self.addr_name_var.set(result.get('name', final_vendor_name))
            self.addr_line1_var.set(street)
            
            self.city_var.set(city)
            self.state_var.set(state)
            self.zip_var.set(zip_code)
            
            # Build conventional addr_line2
            line2_parts = []
            if city:
                line2_parts.append(city)
            if state:
                line2_parts.append(state)
            if zip_code:
                line2_parts.append(zip_code)
            self.addr_line2_var.set(' '.join(line2_parts))
            
            # Phone number
            phone = result.get('phone', '')
            if not phone and result.get('place_id'):
                # Try to get phone from place details
                phone = _get_google_place_phone(result['place_id']) or ''
            self.phone_var.set(phone)
            
            # Store coordinates if available
            if result.get('lat') and result.get('lng'):
                self.vendor_data['latitude'] = result['lat']
                self.vendor_data['longitude'] = result['lng']
            
            if result.get('place_id'):
                self.vendor_data['place_id'] = result['place_id']
            
            self.vendor_data['address_source'] = 'google'
            
            self.status_var.set("Search result populated - saving...")
            
        finally:
            self.loading = False
        
        # Save the populated result immediately
        self._save_vendor()
        
        # Hide results frame
        self.results_frame.pack_forget()
        
        self.status_var.set("Search result applied and saved")


def main():
    """Main entry point."""
    # Setup logging
    setup_logging_for_script("address_lookup_gui")
    
    # Get vendor name from command line if provided
    vendor_name = None
    if len(sys.argv) > 1:
        vendor_name = sys.argv[1]
        logger.info(f"Launched with vendor: {vendor_name}")
    
    # Create GUI
    root = tk.Tk()
    app = AddressLookupGUI(root, vendor_name)
    
    logger.info("Address Lookup GUI started")
    root.mainloop()
    logger.info("Address Lookup GUI closed")


if __name__ == "__main__":
    main()

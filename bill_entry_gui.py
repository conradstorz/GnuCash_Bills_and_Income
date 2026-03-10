"""
Bill Entry GUI - Simple tool for building bills_to_process.txt

Features:
- Simple form for entering bill data
- Direct writing to bills_to_process.txt
- Launch external tools for vendor management and database operations
- View and edit current bills queue
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import sys
import os
import json
import subprocess
import threading
import queue
from pathlib import Path
from datetime import date, datetime
from typing import List, Dict, Optional
from loguru import logger

from bill_processor import config
from bill_processor.utils import parse_input_line, fuzzy_match_vendor
from bill_processor.logging_setup import setup_logging_for_script, log_function_entry, log_function_exit, log_stage
from bill_processor import vendor_manager
from bill_processor import gnucash_db


class VendorSyncProgressDialog:
    """Dialog to show vendor sync progress."""
    
    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Vendor Sync Progress")
        self.dialog.geometry("600x400")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        # Progress text area
        frame = ttk.Frame(self.dialog, padding=10)
        frame.pack(fill="both", expand=True)
        
        ttk.Label(frame, text="Vendor Sync Progress:", font=('TkDefaultFont', 10, 'bold')).pack(anchor="w", pady=(0, 5))
        
        self.text = scrolledtext.ScrolledText(frame, wrap="word", height=20, font=('Consolas', 9))
        self.text.pack(fill="both", expand=True)
        
        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x", pady=(10, 0))
        
        self.close_btn = ttk.Button(btn_frame, text="Close", command=self.close, state="disabled")
        self.close_btn.pack(side="right")
        
        # Status
        self.status_var = tk.StringVar()
        self.status_var.set("Running vendor sync...")
        ttk.Label(btn_frame, textvariable=self.status_var).pack(side="left")
        
        self.is_running = True
        
    def append_text(self, text):
        """Append text to the progress display."""
        self.text.insert("end", text + "\n")
        self.text.see("end")
        self.dialog.update_idletasks()
        
    def set_complete(self, success=True):
        """Mark sync as complete."""
        self.is_running = False
        if success:
            self.status_var.set("✅ Sync completed successfully!")
        else:
            self.status_var.set("❌ Sync completed with errors")
        self.close_btn.config(state="normal")
        
    def close(self):
        """Close the dialog."""
        self.dialog.destroy()


class AccountSelectionDialog:
    """Dialog for selecting expense and checking accounts before processing bills."""
    
    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Select Accounts for Bill Processing")
        self.dialog.geometry("600x400")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self.selected_expense_guid = None
        self.selected_checking_guid = None
        self.cancelled = True
        
        self._create_widgets()
        
    def _create_widgets(self):
        """Create dialog widgets."""
        frame = ttk.Frame(self.dialog, padding=20)
        frame.pack(fill="both", expand=True)
        
        # Title
        ttk.Label(
            frame, 
            text="Select accounts for processing bills:",
            font=('TkDefaultFont', 11, 'bold')
        ).pack(anchor="w", pady=(0, 15))
        
        # Expense Account Section
        exp_frame = ttk.LabelFrame(frame, text="Expense Account", padding=10)
        exp_frame.pack(fill="x", pady=(0, 15))
        
        ttk.Label(exp_frame, text="Select an expense account (non-placeholder):").pack(anchor="w", pady=(0, 5))
        
        self.expense_var = tk.StringVar()
        self.expense_combo = ttk.Combobox(exp_frame, textvariable=self.expense_var, state="readonly", width=70)
        self.expense_combo.pack(fill="x")
        
        # Checking Account Section
        check_frame = ttk.LabelFrame(frame, text="Checking Account", padding=10)
        check_frame.pack(fill="x", pady=(0, 15))
        
        ttk.Label(check_frame, text="Select a checking account (non-placeholder):").pack(anchor="w", pady=(0, 5))
        
        self.checking_var = tk.StringVar()
        self.checking_combo = ttk.Combobox(check_frame, textvariable=self.checking_var, state="readonly", width=70)
        self.checking_combo.pack(fill="x")
        
        # Status message
        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(frame, textvariable=self.status_var, foreground="red")
        self.status_label.pack(fill="x", pady=(0, 10))
        
        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill="x")
        
        ttk.Button(btn_frame, text="Cancel", command=self.cancel).pack(side="right", padx=(5, 0))
        ttk.Button(btn_frame, text="OK", command=self.ok).pack(side="right")
        
        # Load accounts
        self._load_accounts()
        
    def _load_accounts(self):
        """Load accounts from database."""
        try:
            # Get expense accounts
            expense_accounts = gnucash_db.get_expense_accounts()
            if not expense_accounts:
                self.status_var.set("⚠️ No expense accounts found. Please create an expense account in GnuCash first.")
                self.expense_combo.config(state="disabled")
            else:
                expense_items = [f"{acc['name']} ({acc['guid'][:8]}...)" for acc in expense_accounts]
                self.expense_combo['values'] = expense_items
                self.expense_accounts = expense_accounts
                if expense_items:
                    self.expense_combo.current(0)
            
            # Get checking accounts
            checking_accounts = gnucash_db.get_checking_accounts()
            if not checking_accounts:
                self.status_var.set("⚠️ No checking accounts found. Please create a checking account in GnuCash first.")
                self.checking_combo.config(state="disabled")
            else:
                checking_items = [f"{acc['name']} ({acc['guid'][:8]}...)" for acc in checking_accounts]
                self.checking_combo['values'] = checking_items
                self.checking_accounts = checking_accounts
                if checking_items:
                    self.checking_combo.current(0)
                    
        except Exception as e:
            logger.error(f"Failed to load accounts: {e}")
            self.status_var.set(f"Error loading accounts: {e}")
    
    def ok(self):
        """OK button handler."""
        # Validate selections
        exp_idx = self.expense_combo.current()
        check_idx = self.checking_combo.current()
        
        if exp_idx < 0:
            self.status_var.set("Please select an expense account")
            return
            
        if check_idx < 0:
            self.status_var.set("Please select a checking account")
            return
        
        # Get selected GUIDs
        self.selected_expense_guid = self.expense_accounts[exp_idx]['guid']
        self.selected_checking_guid = self.checking_accounts[check_idx]['guid']
        self.cancelled = False
        self.dialog.destroy()
    
    def cancel(self):
        """Cancel button handler."""
        self.cancelled = True
        self.dialog.destroy()


class SimpleBillEntryGUI:
    """Simple GUI application for bill entry - no database operations."""
    
    def __init__(self, root: tk.Tk):
        log_function_entry("SimpleBillEntryGUI.__init__")
        logger.info("Initializing Simple Bill Entry GUI application")
        
        self.root = root
        self.root.title("Simple Bill Entry - GnuCash Bills")
        self.root.geometry("800x700")
        self.root.minsize(600, 500)
        
        # Status
        self.status_var = tk.StringVar()
        self.status_var.set("Ready")
        self.vendor_stats_var = tk.StringVar()
        self.vendor_stats_var.set("Vendors: Loading...")
        
        # Vendor autocomplete state
        self.vendor_mgr = None
        self.autocomplete_window = None
        self.autocomplete_listbox = None
        self.vendor_matches = []
        
        # STEP 0: Check if database is locked BEFORE anything else
        if not self._check_database_lock():
            # Database is locked - error shown, exit
            logger.error("Database lock check failed - exiting")
            return
        
        # Verify/create AP account at startup
        try:
            ap_guid = gnucash_db.ensure_ap_account_exists()
            logger.info(f"AP account verified/created: {ap_guid}")
        except Exception as e:
            logger.error(f"Failed to verify AP account at startup: {e}")
            messagebox.showerror(
                "Database Error",
                f"Could not verify Accounts Payable account:\n{e}\n\nThe application may not function correctly."
            )
        
        # Build UI
        self._create_widgets()
        self._load_current_bills()
        self._update_vendor_stats()  # Load vendor statistics
        
        # Bind keyboard shortcuts
        self.root.bind('<Control-s>', lambda e: self._save_bill())
        self.root.bind('<Control-n>', lambda e: self._clear_form())
        
        # Bind cleanup on window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        log_function_exit("SimpleBillEntryGUI.__init__")
    
    def _on_closing(self):
        """Handle window close - release database lock."""
        logger.info("Application closing - releasing database lock")
        gnucash_db.release_lock()
        self.root.destroy()
    
    def _check_database_lock(self) -> bool:
        """
        Check if GnuCash database is locked, and acquire our own lock if available.
        
        This MUST be called before ANY database access.
        
        Returns:
            True if database is accessible and lock acquired
            False if database is locked (GnuCash or another instance running)
        """
        # Check if database is locked
        is_locked, hostname, pid = gnucash_db.is_gnucash_locked()
        if is_locked:
            logger.warning(f"GnuCash database is LOCKED by {hostname} (PID {pid})")
            
            # Check if the lock is stale (PID not running)
            from bill_processor.gnucash_db import _is_process_running
            import socket
            
            is_running = _is_process_running(pid)
            local_machine = socket.gethostname()
            
            # Build detailed message
            pid_status = "RUNNING" if is_running else "NOT RUNNING"
            
            if is_running:
                # Process is still running - cannot clean
                logger.error(f"Database locked by active process: {hostname} (PID {pid})")
                messagebox.showerror(
                    "Database is Locked",
                    f"The GnuCash database is currently locked by an active process.\n\n"
                    f"Locked by: {hostname}\n"
                    f"Process ID (PID): {pid}\n"
                    f"Status: {pid_status}\n\n"
                    f"Please close GnuCash or other instances of this application\n"
                    f"before continuing."
                )
                self.root.destroy()
                return False
            else:
                # Stale lock detected - ask user what to do
                message = (
                    f"DATABASE LOCK DETECTED\n\n"
                    f"Lock Details:\n"
                    f"  • Hostname: {hostname}\n"
                    f"  • Process ID (PID): {pid}\n"
                    f"  • Status: {pid_status}\n"
                    f"  • Your machine: {local_machine}\n\n"
                    f"What is a PID?\n"
                    f"A PID (Process ID) is a unique number assigned to each running\n"
                    f"program. When a program crashes or is force-closed, it may leave\n"
                    f"behind a lock even though the process is no longer running.\n\n"
                    f"Common Causes of Stale Locks:\n"
                    f"  • GnuCash crashed or was force-closed\n"
                    f"  • This application was terminated abnormally (Ctrl+C, crash)\n"
                    f"  • Computer was shut down while the database was open\n"
                    f"  • Power failure or system crash\n\n"
                    f"Since PID {pid} is NOT RUNNING, this appears to be a stale lock.\n\n"
                    f"Do you want to clear this stale lock and continue?"
                )
                
                response = messagebox.askyesno(
                    "Stale Database Lock Found",
                    message,
                    icon='warning',
                    default='no'
                )
                
                if response:  # User chose Yes - clear the lock
                    logger.info(f"User chose to clear stale lock: {hostname} (PID {pid})")
                    if gnucash_db.clean_stale_lock():
                        logger.info("Stale lock successfully cleared")
                        messagebox.showinfo(
                            "Lock Cleared",
                            "The stale lock has been cleared.\n\n"
                            "The application will now proceed."
                        )
                        # Continue to acquire our own lock below
                    else:
                        logger.error("Failed to clear stale lock")
                        messagebox.showerror(
                            "Error",
                            "Failed to clear the stale lock.\n\n"
                            "The database may be in use or you may lack permissions."
                        )
                        self.root.destroy()
                        return False
                else:  # User chose No - exit without modifying
                    logger.info("User chose NOT to clear stale lock - exiting")
                    messagebox.showinfo(
                        "Exiting",
                        "Database lock was not modified.\n\n"
                        "The application will now exit."
                    )
                    self.root.destroy()
                    return False
        
        # Database is available - acquire our lock
        if not gnucash_db.acquire_lock():
            logger.error("Failed to acquire database lock")
            messagebox.showerror(
                "Lock Error",
                "Failed to acquire database lock.\n\n"
                "The database may have been locked by another process."
            )
            self.root.destroy()
            return False
        
        logger.info("Database lock check: PASSED - lock acquired")
        return True
    
    def _create_widgets(self):
        """Create the main GUI elements."""
        log_function_entry("SimpleBillEntryGUI._create_widgets")
        
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill="both", expand=True)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # === Bill Entry Form ===
        entry_frame = ttk.LabelFrame(main_frame, text="Enter New Bill", padding="10")
        entry_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        entry_frame.columnconfigure(1, weight=1)
        
        # Vendor name
        ttk.Label(entry_frame, text="Vendor Name:").grid(row=0, column=0, sticky="w", pady=5)
        self.vendor_entry = ttk.Entry(entry_frame, width=50, font=('TkDefaultFont', 10))
        self.vendor_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=5)
        self.vendor_entry.focus()
        
        # Bind events for real-time autocomplete
        self.vendor_entry.bind('<KeyRelease>', self._on_vendor_keyrelease)
        self.vendor_entry.bind('<FocusOut>', self._on_vendor_focusout)
        self.vendor_entry.bind('<Down>', self._on_vendor_down)
        self.vendor_entry.bind('<Return>', self._on_vendor_return)
        
        # Amount
        ttk.Label(entry_frame, text="Amount:").grid(row=1, column=0, sticky="w", pady=5)
        self.amount_entry = ttk.Entry(entry_frame, width=20)
        self.amount_entry.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=5)
        
        # Memo
        ttk.Label(entry_frame, text="Memo:").grid(row=2, column=0, sticky="w", pady=5)
        self.memo_entry = ttk.Entry(entry_frame, width=50)
        self.memo_entry.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=5)
        
        # Date
        ttk.Label(entry_frame, text="Date:").grid(row=3, column=0, sticky="w", pady=5)
        date_frame = ttk.Frame(entry_frame)
        date_frame.grid(row=3, column=1, sticky="w", padx=(10, 0), pady=5)
        
        self.date_entry = ttk.Entry(date_frame, width=15)
        self.date_entry.pack(side="left")
        self.date_entry.insert(0, date.today().strftime("%Y-%m-%d"))
        
        ttk.Button(date_frame, text="Today", command=self._set_today, width=8).pack(side="left", padx=(5, 0))
        
        # Buttons
        btn_frame = ttk.Frame(entry_frame)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=(10, 0))
        
        ttk.Button(btn_frame, text="Save Bill (Ctrl+S)", command=self._save_bill).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Clear (Ctrl+N)", command=self._clear_form).pack(side="left", padx=5)
        
        # === External Tools ===
        tools_frame = ttk.LabelFrame(main_frame, text="External Tools", padding="10")
        tools_frame.grid(row=0, column=2, sticky="new", padx=(10, 0))
        
        ttk.Button(tools_frame, text="🔍 Manage Vendors:\nFind, create,\nand manage vendors", 
                   command=self._launch_address_lookup, width=20).pack(pady=5, fill="x")
        ttk.Button(tools_frame, text="🗃️ Vendor Sync:\nSync Vendor Records\nbetween this tool and\nthe GnuCash Database", 
                   command=self._launch_vendor_sync, width=20).pack(pady=5, fill="x")
        ttk.Button(tools_frame, text="💳 Process Bills:\nCreate queued bills\n in GnuCash database", 
                   command=self._launch_bill_processor, width=20).pack(pady=5, fill="x")
        
        # === Current Bills List ===
        bills_frame = ttk.LabelFrame(main_frame, text="Current Bills Queue", padding="5")
        bills_frame.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(0, 10))
        bills_frame.columnconfigure(0, weight=1)
        bills_frame.rowconfigure(0, weight=1)
        
        # Treeview for bills
        columns = ("vendor", "amount", "memo", "date")
        self.bills_tree = ttk.Treeview(bills_frame, columns=columns, show="headings", height=12)
        
        # Configure columns
        self.bills_tree.heading("vendor", text="Vendor")
        self.bills_tree.heading("amount", text="Amount")
        self.bills_tree.heading("memo", text="Memo")
        self.bills_tree.heading("date", text="Date")
        
        self.bills_tree.column("vendor", width=200)
        self.bills_tree.column("amount", width=80, anchor="e")
        self.bills_tree.column("memo", width=250)
        self.bills_tree.column("date", width=80, anchor="center")
        
        self.bills_tree.grid(row=0, column=0, sticky="nsew")
        
        # Scrollbar for treeview
        scrollbar = ttk.Scrollbar(bills_frame, orient="vertical", command=self.bills_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.bills_tree.configure(yscrollcommand=scrollbar.set)
        
        # Bind selection event to show vendor details
        self.bills_tree.bind('<<TreeviewSelect>>', self._on_bill_selected)
        
        # Bills management buttons
        bills_btn_frame = ttk.Frame(bills_frame)
        bills_btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        
        ttk.Button(bills_btn_frame, text="Edit Selected", command=self._edit_selected_bill).pack(side="left", padx=5)
        ttk.Button(bills_btn_frame, text="Delete Selected", command=self._delete_selected_bill).pack(side="left", padx=5)
        ttk.Button(bills_btn_frame, text="Clear All", command=self._clear_all_bills).pack(side="left", padx=5)
        ttk.Button(bills_btn_frame, text="Refresh List", command=self._load_current_bills).pack(side="right", padx=5)
        
        # === Vendor Details Display ===
        details_frame = ttk.LabelFrame(main_frame, text="Vendor Details", padding="10")
        details_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        details_frame.columnconfigure(0, weight=1)
        
        self.vendor_details_text = tk.Text(details_frame, height=8, wrap="word", font=('TkDefaultFont', 9))
        self.vendor_details_text.pack(fill="both", expand=True)
        self.vendor_details_text.insert("1.0", "Select a bill to view vendor details...")
        self.vendor_details_text.config(state="disabled")
        
        # === Status Bar ===
        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=3, column=0, columnspan=3, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        
        ttk.Label(status_frame, textvariable=self.status_var, relief="sunken", anchor="w").grid(row=0, column=0, sticky="ew")
        ttk.Label(status_frame, textvariable=self.vendor_stats_var, relief="sunken", anchor="e").grid(row=0, column=1, sticky="ew")
        
        log_function_exit("SimpleBillEntryGUI._create_widgets")
    
    def _set_today(self):
        """Set date entry to today."""
        logger.debug("Setting date to today")
        self.date_entry.delete(0, tk.END)
        self.date_entry.insert(0, date.today().strftime("%Y-%m-%d"))
    
    def _save_bill(self):
        """Save current bill to bills_to_process.txt."""
        log_function_entry("SimpleBillEntryGUI._save_bill")
        
        vendor_name = self.vendor_entry.get().strip()
        amount_str = self.amount_entry.get().strip()
        memo = self.memo_entry.get().strip()
        date_str = self.date_entry.get().strip()
        
        # Basic validation
        if not vendor_name:
            messagebox.showerror("Error", "Vendor name is required.")
            self.vendor_entry.focus()
            return
        
        if not amount_str:
            messagebox.showerror("Error", "Amount is required.")
            self.amount_entry.focus()
            return
        
        try:
            amount = float(amount_str.replace('$', '').replace(',', ''))
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid amount: {amount_str}")
            self.amount_entry.focus()
            return
        
        if not memo:
            memo = f"Bill from {vendor_name}"
        
        # Validate date
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Error", f"Invalid date format: {date_str}. Use YYYY-MM-DD.")
            self.date_entry.focus()
            return
        
        # Create bill line (comma-separated to match parse_input_line format)
        bill_line = f"{vendor_name}, {amount:.2f}, {memo}, {date_str}\n"
        
        # Append to bills file
        bills_file = Path(config.PROJECT_ROOT) / "data" / "bills_to_process.txt"
        try:
            with open(bills_file, "a", encoding="utf-8") as f:
                f.write(bill_line)
            
            logger.info(f"Bill saved: {vendor_name} - ${amount:.2f}")
            self.status_var.set(f"Bill saved: {vendor_name} - ${amount:.2f}")
            
            # Clear form and reload list
            self._clear_form()
            self._load_current_bills()
            
        except Exception as e:
            logger.error(f"Failed to save bill: {e}")
            messagebox.showerror("Error", f"Failed to save bill: {e}")
        
        log_function_exit("SimpleBillEntryGUI._save_bill")
    
    def _clear_form(self):
        """Clear all form fields."""
        logger.debug("Clearing form fields")
        self.vendor_entry.delete(0, tk.END)
        self.amount_entry.delete(0, tk.END)
        self.memo_entry.delete(0, tk.END)
        self.date_entry.delete(0, tk.END)
        self.date_entry.insert(0, date.today().strftime("%Y-%m-%d"))
        self.vendor_entry.focus()
        self.status_var.set("Form cleared")
    
    def _load_current_bills(self):
        """Load and display current bills from bills_to_process.txt."""
        log_function_entry("SimpleBillEntryGUI._load_current_bills")
        
        # Clear existing items
        for item in self.bills_tree.get_children():
            self.bills_tree.delete(item)
        
        bills_file = Path(config.PROJECT_ROOT) / "data" / "bills_to_process.txt"
        if not bills_file.exists():
            logger.debug("Bills file does not exist yet")
            self.status_var.set("No bills file found - ready for first bill")
            log_function_exit("SimpleBillEntryGUI._load_current_bills")
            return
        
        try:
            bill_count = 0
            with open(bills_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    try:
                        bill_data = parse_input_line(line)
                        if bill_data:
                            # Add to tree
                            self.bills_tree.insert("", "end", values=(
                                bill_data['vendor_name'],
                                f"${bill_data['amount']:.2f}",
                                bill_data['memo'],
                                bill_data['date']
                            ))
                            bill_count += 1
                    except Exception as e:
                        logger.warning(f"Skipping invalid line {line_num}: {line} - {e}")
            
            logger.info(f"Loaded {bill_count} bills")
            self.status_var.set(f"Loaded {bill_count} bills")
            
        except Exception as e:
            logger.error(f"Error loading bills: {e}")
            messagebox.showerror("Error", f"Error loading bills: {e}")
    
    def _update_vendor_stats(self):
        """Update vendor statistics display."""
        try:
            # Count vendors in JSON
            json_count = 0
            try:
                from bill_processor.vendor_manager import VendorManager
                vendor_mgr = VendorManager()
                json_count = len(vendor_mgr.vendors.get('vendors', {}))
            except Exception as e:
                logger.warning(f"Could not load JSON vendors: {e}")
            
            # Count vendors in GnuCash
            gnucash_count = 0
            try:
                from bill_processor.gnucash_db import get_connection
                with get_connection() as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM vendors")
                    gnucash_count = cursor.fetchone()[0]
            except Exception as e:
                logger.warning(f"Could not count GnuCash vendors: {e}")
            
            # Update display
            self.vendor_stats_var.set(f"Vendors: JSON={json_count} | GnuCash={gnucash_count}")
            
        except Exception as e:
            logger.error(f"Error updating vendor stats: {e}")
            self.vendor_stats_var.set("Vendors: Error loading stats")
        
        log_function_exit("SimpleBillEntryGUI._load_current_bills")
    
    def _get_vendor_manager(self):
        """Lazy-load vendor manager for autocomplete."""
        if self.vendor_mgr is None:
            try:
                self.vendor_mgr = vendor_manager.VendorManager()
            except Exception as e:
                logger.error(f"Failed to load vendor manager: {e}")
        return self.vendor_mgr

    def _reload_vendor_manager(self):
        """Force-reload the vendor manager (e.g. after external changes)."""
        logger.info("Reloading vendor manager after external changes")
        self.vendor_mgr = None  # Clear cached instance
        self._get_vendor_manager()  # Re-load from disk
        self._update_vendor_stats()
        self.status_var.set("Vendor list reloaded")
    
    def _on_vendor_keyrelease(self, event):
        """Handle key release in vendor entry for autocomplete."""
        # Ignore navigation keys
        if event.keysym in ('Up', 'Down', 'Left', 'Right', 'Escape', 'Return', 'Tab'):
            return
        
        search_text = self.vendor_entry.get().strip()
        
        # Hide autocomplete if text is too short
        if len(search_text) < 2:
            self._hide_autocomplete()
            return
        
        # Find matching vendors
        self._show_vendor_matches(search_text)
    
    def _on_vendor_down(self, event):
        """Handle down arrow to move to autocomplete list."""
        if self.autocomplete_listbox and self.autocomplete_listbox.winfo_viewable():
            self.autocomplete_listbox.focus_set()
            if self.autocomplete_listbox.size() > 0:
                self.autocomplete_listbox.selection_clear(0, tk.END)
                self.autocomplete_listbox.selection_set(0)
                self.autocomplete_listbox.activate(0)
            return 'break'
    
    def _on_vendor_return(self, event):
        """Handle Enter key in vendor entry."""
        if self.autocomplete_listbox and self.autocomplete_listbox.winfo_viewable():
            # If autocomplete is showing, select first item
            if self.autocomplete_listbox.size() > 0:
                self._select_autocomplete_item(0)
            return 'break'
    
    def _on_vendor_focusout(self, event):
        """Hide autocomplete when vendor entry loses focus."""
        # Don't hide if focus is moving to the autocomplete listbox
        def check_and_hide():
            current_focus = self.root.focus_get()
            if current_focus != self.autocomplete_listbox:
                self._hide_autocomplete()
        # Delay hiding to allow clicking on autocomplete list
        self.root.after(200, check_and_hide)
    
    def _show_vendor_matches(self, search_text):
        """Show autocomplete matches for vendor search."""
        vm = self._get_vendor_manager()
        if not vm:
            return
        
        try:
            # Get all vendor names and their display names
            vendor_names = []
            vendors_dict = vm.vendors.get('vendors', {})
            
            # Use fuzzy matching to find relevant vendors
            best_key, best_score, matches = fuzzy_match_vendor(
                search_text, 
                vendors_dict,
                threshold=50  # Lower threshold for autocomplete
            )
            
            # Get unique vendor display names from matches
            seen = set()
            for vendor_key, score in matches:
                if vendor_key in vendors_dict:
                    display_name = vendors_dict[vendor_key].get('display_name', vendor_key)
                    if display_name not in seen:
                        vendor_names.append((display_name, score))
                        seen.add(display_name)
            
            # Also check GnuCash vendors for exact/prefix matches
            try:
                gc_vendors = vm.gnucash_vendors
                search_lower = search_text.lower()
                for gv in gc_vendors:
                    name = gv['name']
                    if search_lower in name.lower() and name not in seen:
                        # Calculate a simple score based on position
                        score = 90 if name.lower().startswith(search_lower) else 70
                        vendor_names.append((name, score))
                        seen.add(name)
            except Exception as e:
                logger.debug(f"Could not search GnuCash vendors: {e}")
            
            # Sort by score descending, limit to top 10
            vendor_names.sort(key=lambda x: x[1], reverse=True)
            vendor_names = vendor_names[:10]
            
            if vendor_names:
                self._display_autocomplete([name for name, score in vendor_names])
            else:
                self._hide_autocomplete()
                
        except Exception as e:
            logger.error(f"Error finding vendor matches: {e}")
            self._hide_autocomplete()
    
    def _display_autocomplete(self, matches):
        """Display autocomplete dropdown with matching vendors."""
        self.vendor_matches = matches
        
        # Create autocomplete window if it doesn't exist
        if not self.autocomplete_window:
            self.autocomplete_window = tk.Toplevel(self.root)
            self.autocomplete_window.wm_overrideredirect(True)
            self.autocomplete_window.withdraw()
            
            # Create listbox
            frame = ttk.Frame(self.autocomplete_window, relief="solid", borderwidth=1)
            frame.pack(fill="both", expand=True)
            
            self.autocomplete_listbox = tk.Listbox(
                frame,
                height=min(len(matches), 10),
                font=('TkDefaultFont', 10),
                activestyle='dotbox',
                relief="flat"
            )
            self.autocomplete_listbox.pack(fill="both", expand=True)
            
            # Bind selection events
            self.autocomplete_listbox.bind('<Button-1>', self._on_autocomplete_click)
            self.autocomplete_listbox.bind('<Return>', lambda e: self._on_autocomplete_select(None))
            self.autocomplete_listbox.bind('<Double-Button-1>', lambda e: self._on_autocomplete_select(None))
            self.autocomplete_listbox.bind('<Escape>', lambda e: self._hide_autocomplete())
            self.autocomplete_listbox.bind('<Up>', self._on_autocomplete_up)
            self.autocomplete_listbox.bind('<FocusOut>', self._on_autocomplete_focusout)
        
        # Clear and populate listbox
        self.autocomplete_listbox.delete(0, tk.END)
        for match in matches:
            self.autocomplete_listbox.insert(tk.END, match)
        
        # Update height
        self.autocomplete_listbox.config(height=min(len(matches), 10))
        
        # Position window below vendor entry
        x = self.vendor_entry.winfo_rootx()
        y = self.vendor_entry.winfo_rooty() + self.vendor_entry.winfo_height()
        width = self.vendor_entry.winfo_width()
        
        self.autocomplete_window.wm_geometry(f"{width}x{min(len(matches) * 25, 250)}+{x}+{y}")
        self.autocomplete_window.deiconify()
        self.autocomplete_window.lift()
    
    def _hide_autocomplete(self):
        """Hide the autocomplete dropdown."""
        if self.autocomplete_window:
            self.autocomplete_window.withdraw()
    
    def _on_autocomplete_click(self, event):
        """Handle click on autocomplete item."""
        # Get the index of the clicked item
        index = self.autocomplete_listbox.nearest(event.y)
        self._select_autocomplete_item(index)
    
    def _on_autocomplete_select(self, event):
        """Handle Enter/double-click on autocomplete item."""
        selection = self.autocomplete_listbox.curselection()
        if selection:
            self._select_autocomplete_item(selection[0])
    
    def _on_autocomplete_up(self, event):
        """Handle up arrow in autocomplete - return to entry if at top."""
        if self.autocomplete_listbox.curselection():
            index = self.autocomplete_listbox.curselection()[0]
            if index == 0:
                self.vendor_entry.focus_set()
                self._hide_autocomplete()
                return 'break'
    
    def _on_autocomplete_focusout(self, event):
        """Hide autocomplete when listbox loses focus."""
        # Don't hide if focus is moving back to the vendor entry
        def check_and_hide():
            current_focus = self.root.focus_get()
            if current_focus != self.vendor_entry:
                self._hide_autocomplete()
        # Delay to allow focus transitions
        self.root.after(200, check_and_hide)
    
    def _select_autocomplete_item(self, index):
        """Select an item from autocomplete list."""
        if 0 <= index < len(self.vendor_matches):
            selected_vendor = self.vendor_matches[index]
            self.vendor_entry.delete(0, tk.END)
            self.vendor_entry.insert(0, selected_vendor)
            self._hide_autocomplete()
            # Move focus to next field
            self.amount_entry.focus_set()
    
    def _edit_selected_bill(self):
        """Edit the selected bill."""
        logger.debug("Editing selected bill")
        selection = self.bills_tree.selection()
        if not selection:
            logger.warning("No bill selected for editing")
            messagebox.showwarning("No Selection", "Please select a bill to edit.")
            return
        
        item = selection[0]
        values = self.bills_tree.item(item, "values")
        logger.info(f"Loading bill for editing: vendor={values[0]}, amount={values[1]}")
        
        # Fill form with selected bill data
        self.vendor_entry.delete(0, tk.END)
        self.vendor_entry.insert(0, values[0])
        
        self.amount_entry.delete(0, tk.END)
        amount_str = values[1].replace('$', '')
        self.amount_entry.insert(0, amount_str)
        
        self.memo_entry.delete(0, tk.END)
        self.memo_entry.insert(0, values[2])
        
        self.date_entry.delete(0, tk.END)
        self.date_entry.insert(0, values[3])
        
        # Remove from list (will be re-added when saved)
        self._delete_selected_bill_from_file(item)
        
        self.status_var.set(f"Editing bill: {values[0]}")
    
    def _delete_selected_bill(self):
        """Delete the selected bill."""
        logger.debug("Attempting to delete selected bill")
        selection = self.bills_tree.selection()
        if not selection:
            logger.warning("No bill selected for deletion")
            messagebox.showwarning("No Selection", "Please select a bill to delete.")
            return
        
        item = selection[0]
        values = self.bills_tree.item(item, "values")
        logger.info(f"Prompting to delete bill: vendor={values[0]}, amount={values[1]}")
        
        if messagebox.askyesno("Confirm Delete", f"Delete bill for {values[0]} - {values[1]}?"):
            logger.info(f"Deleting bill for vendor: {values[0]}")
            self._delete_selected_bill_from_file(item)
            self.status_var.set(f"Deleted bill: {values[0]}")
    
    def _delete_selected_bill_from_file(self, tree_item):
        """Remove the selected bill from the file."""
        logger.debug("Removing bill from file")
        values = self.bills_tree.item(tree_item, "values")
        vendor_name = values[0]
        amount_str = values[1].replace('$', '')
        memo = values[2]
        date_str = values[3]
        
        bills_file = Path(config.PROJECT_ROOT) / "data" / "bills_to_process.txt"
        
        try:
            # Read all lines
            lines = []
            with open(bills_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # Find and remove matching line
            new_lines = []
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                
                try:
                    bill_data = parse_input_line(line_stripped)
                    if (bill_data and 
                        bill_data['vendor_name'] == vendor_name and
                        f"{bill_data['amount']:.2f}" == amount_str and
                        bill_data['memo'] == memo and
                        bill_data['date'] == date_str):
                        # Skip this line (delete it)
                        continue
                except:
                    pass
                
                new_lines.append(line)
            
            # Write back to file
            with open(bills_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            
            # Remove from tree
            self.bills_tree.delete(tree_item)
            
        except Exception as e:
            logger.error(f"Error deleting bill: {e}")
            messagebox.showerror("Error", f"Error deleting bill: {e}")
    
    def _clear_all_bills(self):
        """Clear all bills from the file."""
        logger.debug("Clear all bills requested")
        if messagebox.askyesno("Confirm Clear All", "Delete ALL bills from the queue?"):
            logger.warning("Clearing all bills from queue")
            bills_file = Path(config.PROJECT_ROOT) / "data" / "bills_to_process.txt"
            try:
                bills_file.unlink(missing_ok=True)
                self._load_current_bills()
                self.status_var.set("All bills cleared")
            except Exception as e:
                logger.error(f"Error clearing bills: {e}")
                messagebox.showerror("Error", f"Error clearing bills: {e}")
    
    def _on_bill_selected(self, event):
        """Handle bill selection - display vendor details."""
        logger.debug("Bill selection changed")
        selection = self.bills_tree.selection()
        if not selection:
            # Clear vendor details
            self.vendor_details_text.config(state="normal")
            self.vendor_details_text.delete("1.0", "end")
            self.vendor_details_text.insert("1.0", "Select a bill to view vendor details...")
            self.vendor_details_text.config(state="disabled")
            return
        
        item = selection[0]
        values = self.bills_tree.item(item, "values")
        vendor_name = values[0]
        logger.info(f"Loading vendor details for: {vendor_name}")
        
        # Update display
        self.vendor_details_text.config(state="normal")
        self.vendor_details_text.delete("1.0", "end")
        
        try:
            # Load vendor manager
            vm = vendor_manager.VendorManager()
            
            # Search for vendor
            vendor_data, match_type = vm.find_vendor(vendor_name)
            
            # Build details text
            details = f"Vendor: {vendor_name}\n"
            details += "=" * 60 + "\n\n"
            
            if vendor_data:
                details += f"✅ FOUND in database ({match_type} match)\n\n"
                details += f"Display Name: {vendor_data.get('display_name', 'N/A')}\n"
                details += f"GnuCash GUID: {vendor_data.get('gnucash_guid', 'Not set')}\n"
                details += f"GnuCash ID: {vendor_data.get('gnucash_id', 'Not set')}\n\n"
                
                # Address info
                details += "Address:\n"
                addr_name = vendor_data.get('addr_name', '')
                addr_line1 = vendor_data.get('addr_line1', '')
                addr_line2 = vendor_data.get('addr_line2', '')
                phone = vendor_data.get('phone', '')
                
                if addr_name:
                    details += f"  {addr_name}\n"
                if addr_line1:
                    details += f"  {addr_line1}\n"
                if addr_line2:
                    details += f"  {addr_line2}\n"
                if phone:
                    details += f"  Phone: {phone}\n"
                if not (addr_name or addr_line1 or addr_line2):
                    details += "  (No address on file)\n"
                
                details += f"\nExpense Account: {vendor_data.get('expense_account', 'Not set')}\n"
                
                # Check if vendor exists in GnuCash
                if vendor_data.get('gnucash_guid'):
                    try:
                        gc_vendor = gnucash_db.find_vendor_by_guid(vendor_data['gnucash_guid'])
                        if gc_vendor:
                            details += "\n✅ Verified in GnuCash database\n"
                        else:
                            details += "\n⚠️ GUID exists but vendor not found in GnuCash database\n"
                    except Exception as e:
                        details += f"\n⚠️ Error checking GnuCash: {e}\n"
                else:
                    details += "\n❌ Not yet created in GnuCash database\n"
            else:
                details += "❌ NOT FOUND in vendor database\n\n"
                details += "This vendor does not exist in the system yet.\n"
                details += "Use 'Vendor Manager' to create this vendor before processing bills.\n"
            
            self.vendor_details_text.insert("1.0", details)
            
        except Exception as e:
            error_msg = f"Error loading vendor details:\n{e}"
            logger.error(error_msg)
            self.vendor_details_text.insert("1.0", error_msg)
        
        self.vendor_details_text.config(state="disabled")
    
    def _launch_address_lookup(self):
        """Launch the vendor manager GUI with selected vendor if available."""
        logger.debug("Launching Vendor Manager")
        try:
            script_path = Path(__file__).parent / "vendor_manager_gui.py"
            
            # Get selected vendor from the bills queue
            vendor_name = None
            selection = self.bills_tree.selection()
            if selection:
                item = self.bills_tree.item(selection[0])
                vendor_name = item['values'][0]  # First column is vendor name
            
            # Launch with vendor name if available
            cmd = [sys.executable, str(script_path)]
            if vendor_name:
                cmd.append(vendor_name)
                logger.info(f"Launching Vendor Manager for vendor: {vendor_name}")
                self.status_var.set(f"Launched Vendor Manager for {vendor_name}")
            else:
                logger.info("Launching Vendor Manager (no vendor selected)")
                self.status_var.set("Launched Vendor Manager")
            
            proc = subprocess.Popen(cmd, cwd=str(Path(__file__).parent))
            # Poll for subprocess exit, then reload vendors
            self._poll_subprocess(proc)
            
        except Exception as e:
            logger.error(f"Error launching vendor manager: {e}")
            messagebox.showerror("Error", f"Could not launch vendor manager: {e}")

    def _poll_subprocess(self, proc):
        """Poll a subprocess and reload vendors when it exits."""
        if proc.poll() is None:
            # Still running — check again in 500ms
            self.root.after(500, self._poll_subprocess, proc)
        else:
            # Subprocess exited — reload vendor data
            self._reload_vendor_manager()
    
    def _launch_vendor_sync(self):
        """Launch the vendor sync utility with progress dialog."""
        logger.debug("Launching Vendor Sync")
        
        # Create progress dialog
        progress = VendorSyncProgressDialog(self.root)
        
        def run_sync():
            """Run vendor sync in a thread."""
            try:
                # Import vendor_sync module
                from bill_processor import vendor_sync
                
                # Create sync utility
                sync_util = vendor_sync.VendorSyncUtility()
                
                # Redirect output to progress dialog
                class ProgressWriter:
                    def __init__(self, dialog):
                        self.dialog = dialog
                        
                    def write(self, text):
                        if text.strip():
                            self.dialog.append_text(text.rstrip())
                            
                    def flush(self):
                        pass
                
                # Temporarily redirect stdout
                import sys
                old_stdout = sys.stdout
                sys.stdout = ProgressWriter(progress)
                
                try:
                    # Run bidirectional sync (default behavior)
                    progress.append_text("🔄 Starting bidirectional vendor sync...")
                    progress.append_text("")
                    
                    success = sync_util.sync_bidirectional(dry_run=False)
                    
                    # Update UI on main thread
                    self.root.after(0, lambda: progress.set_complete(success))
                    self.root.after(100, self._update_vendor_stats)
                    
                    if success:
                        self.root.after(0, lambda: self.status_var.set("✅ Vendor sync completed"))
                    else:
                        self.root.after(0, lambda: self.status_var.set("❌ Vendor sync had errors"))
                        
                finally:
                    # Restore stdout
                    sys.stdout = old_stdout
                    
            except Exception as e:
                logger.error(f"Error during vendor sync: {e}")
                import traceback
                error_msg = f"❌ Error: {e}\n\n{traceback.format_exc()}"
                self.root.after(0, lambda: progress.append_text(error_msg))
                self.root.after(0, lambda: progress.set_complete(False))
                self.root.after(0, lambda: self.status_var.set("❌ Vendor sync failed"))
        
        # Start sync in background thread
        sync_thread = threading.Thread(target=run_sync, daemon=True)
        sync_thread.start()
        
        logger.info("Vendor Sync started in background")

    
    def _launch_bill_processor(self):
        """Launch the bill processor with progress dialog."""
        logger.debug("Launching Bill Processor")
        
        # Check if there are bills to process
        bills_file = Path(config.PROJECT_ROOT) / "data" / "bills_to_process.txt"
        if not bills_file.exists() or bills_file.stat().st_size == 0:
            messagebox.showinfo(
                "No Bills", 
                "There are no bills in the queue to process.\n\nAdd bills first, then click 'Process Bills'."
            )
            return
        
        # Show account selection dialog
        account_dialog = AccountSelectionDialog(self.root)
        self.root.wait_window(account_dialog.dialog)
        
        # If user cancelled, abort
        if account_dialog.cancelled:
            logger.info("Bill processing cancelled by user")
            return
        
        # Get selected accounts
        expense_guid = account_dialog.selected_expense_guid
        checking_guid = account_dialog.selected_checking_guid
        
        logger.info(f"Selected expense account: {expense_guid}")
        logger.info(f"Selected checking account: {checking_guid}")
        
        # Create progress dialog
        progress = VendorSyncProgressDialog(self.root)
        progress.dialog.title("Bill Processing Progress")
        
        def run_bill_processor():
            """Run bill processor in a thread."""
            try:
                # Import required modules
                from bill_processor.vendor_manager import VendorManager
                from bill_processor.utils import parse_input_line, format_currency
                
                # Redirect output to progress dialog
                class ProgressWriter:
                    def __init__(self, dialog):
                        self.dialog = dialog
                        
                    def write(self, text):
                        if text.strip():
                            self.dialog.append_text(text.rstrip())
                            
                    def flush(self):
                        pass
                
                # Temporarily redirect stdout
                import sys
                old_stdout = sys.stdout
                sys.stdout = ProgressWriter(progress)
                
                try:
                    progress.append_text("💳 Starting bill processor...")
                    progress.append_text(f"Input file: {bills_file}")
                    progress.append_text("")
                    
                    # Read and parse bills
                    bills = []
                    with open(bills_file, 'r', encoding='utf-8') as f:
                        for line_num, line in enumerate(f, 1):
                            parsed = parse_input_line(line)
                            if parsed:
                                parsed['line_num'] = line_num
                                bills.append(parsed)
                    
                    if not bills:
                        progress.append_text("⚠️  No bills found to process")
                        self.root.after(0, lambda: progress.set_complete(True))
                        return
                    
                    # Show bills
                    total_amount = sum(b['amount'] for b in bills)
                    progress.append_text(f"Found {len(bills)} bill(s) totaling {format_currency(total_amount)}")
                    progress.append_text("")
                    
                    for i, bill in enumerate(bills, 1):
                        progress.append_text(f"  {i}. {bill['vendor_name']}: {format_currency(bill['amount'])}")
                    
                    progress.append_text("")
                    progress.append_text("Processing bills...")
                    progress.append_text("")
                    
                    # Ensure Accounts Payable account exists before processing bills
                    try:
                        ap_guid = gnucash_db.ensure_ap_account_exists()
                        progress.append_text("✓ Accounts Payable account ready")
                        progress.append_text("")
                    except Exception as e:
                        progress.append_text(f"✗ Could not create/find Accounts Payable account: {e}")
                        self.root.after(0, lambda: progress.set_complete(False))
                        return
                    
                    # Process bills (non-interactive mode)
                    vendor_manager = VendorManager()
                    results = {'total': len(bills), 'success': 0, 'failed': 0, 'skipped': 0}
                    successful_bills = []  # Track successfully created bills
                    
                    for bill in bills:
                        try:
                            # NOTE: This is simplified non-interactive processing
                            # It will skip vendors that don't exist rather than prompting
                            vendor_name = bill['vendor_name']
                            amount = bill['amount']
                            memo = bill['memo']
                            bill_date = bill['date']
                            
                            progress.append_text(f"Processing: {vendor_name}")
                            
                            # Find vendor
                            vendor_data, match_type = vendor_manager.find_vendor(vendor_name)
                            
                            if vendor_data:
                                progress.append_text(f"  ✓ Found vendor: {vendor_data.get('display_name')} ({match_type} match)")
                                
                                # Get vendor GUID
                                vendor_guid = vendor_data.get('gnucash_guid')
                                if not vendor_guid:
                                    # Try to find in GnuCash by name
                                    gc_vendor = gnucash_db.find_vendor_by_name(vendor_data.get('display_name'))
                                    if gc_vendor:
                                        vendor_guid = gc_vendor['guid']
                                    else:
                                        progress.append_text(f"  ✗ Could not find vendor GUID")
                                        results['failed'] += 1
                                        progress.append_text("")
                                        continue
                                
                                # Use the user-selected expense account for all bills
                                expense_acct_guid = expense_guid
                                
                                # Create, post, and pay the bill (3-step workflow)
                                try:
                                    # Step 1: Create the bill
                                    progress.append_text(f"  Step 1/3: Creating bill...")
                                    bill_guid = gnucash_db.create_bill(
                                        vendor_guid=vendor_guid,
                                        expense_account_guid=expense_acct_guid,
                                        amount=amount,
                                        memo=memo,
                                        bill_date=bill_date,
                                        verify=True
                                    )
                                    
                                    # Step 2: Post the bill
                                    progress.append_text(f"  Step 2/3: Posting bill...")
                                    gnucash_db.post_bill(bill_guid, post_date=bill_date, due_date=bill_date, verify=True)
                                    
                                    # Step 3: Pay the bill
                                    progress.append_text(f"  Step 3/3: Paying bill...")
                                    gnucash_db.pay_bill(
                                        bill_guid=bill_guid,
                                        checking_account_guid=checking_guid,
                                        payment_date=bill_date,
                                        memo=memo,
                                        verify=True
                                    )
                                    
                                    progress.append_text(f"  ✓ Bill created, posted, and paid ({format_currency(amount)})")
                                    results['success'] += 1
                                    successful_bills.append(bill)  # Track for removal from file
                                    
                                except Exception as e:
                                    progress.append_text(f"  ✗ Failed: {e}")
                                    results['failed'] += 1
                            else:
                                progress.append_text(f"  ⚠️  Vendor not found - skipping")
                                progress.append_text(f"     Use 'Manage Vendors' to create '{vendor_name}' first")
                                results['skipped'] += 1
                            
                            progress.append_text("")
                            
                        except Exception as e:
                            progress.append_text(f"  ✗ Error: {e}")
                            results['failed'] += 1
                            progress.append_text("")
                    
                    # Show summary
                    progress.append_text("=" * 50)
                    progress.append_text("PROCESSING COMPLETE")
                    progress.append_text("=" * 50)
                    progress.append_text(f"Total bills: {results['total']}")
                    progress.append_text(f"Successful:  {results['success']}")
                    progress.append_text(f"Failed:      {results['failed']}")
                    progress.append_text(f"Skipped:     {results['skipped']}")
                    
                    success = results['failed'] == 0 and results['skipped'] == 0
                    
                    if results['success'] > 0:
                        progress.append_text("")
                        progress.append_text(f"✓ {results['success']} bill(s) created, posted, and paid!")
                        progress.append_text("  Bills are now visible in GnuCash")
                        progress.append_text("  Check transactions appear in the check register with memos")
                        
                        # Remove successfully created bills from the file
                        try:
                            if success:
                                # All bills succeeded - delete the entire file
                                bills_file.unlink(missing_ok=True)
                                progress.append_text("")
                                progress.append_text("✓ All bills processed - file cleared")
                                logger.info("Cleared bills_to_process.txt - all bills processed")
                            elif successful_bills:
                                # Some bills succeeded - rewrite file with only failed/skipped bills
                                progress.append_text("")
                                progress.append_text(f"✓ Removing {len(successful_bills)} successful bill(s) from queue...")
                                
                                # Read original file
                                with open(bills_file, 'r', encoding='utf-8') as f:
                                    all_lines = f.readlines()
                                
                                # Create set of successful bill identifiers for fast lookup
                                successful_set = set()
                                for bill in successful_bills:
                                    # Use vendor_name, amount, date as unique identifier
                                    key = (bill['vendor_name'], bill['amount'], bill['date'])
                                    successful_set.add(key)
                                
                                # Keep only lines that don't match successful bills
                                remaining_lines = []
                                for line in all_lines:
                                    parsed = parse_input_line(line)
                                    if parsed:
                                        key = (parsed['vendor_name'], parsed['amount'], parsed['date'])
                                        if key not in successful_set:
                                            remaining_lines.append(line)
                                    else:
                                        # Keep comments and empty lines
                                        remaining_lines.append(line)
                                
                                # Rewrite file with remaining bills
                                with open(bills_file, 'w', encoding='utf-8') as f:
                                    f.writelines(remaining_lines)
                                
                                progress.append_text(f"✓ File updated - {len(remaining_lines)} line(s) remain")
                                logger.info(f"Removed {len(successful_bills)} successful bills from bills_to_process.txt")
                        except Exception as e:
                            logger.error(f"Failed to update bills file: {e}")
                            progress.append_text(f"⚠️  Could not update bills file: {e}")
                    
                    # Update UI on main thread
                    self.root.after(0, lambda: progress.set_complete(success))
                    self.root.after(100, self._load_current_bills)  # Refresh bill list
                    
                    if success:
                        self.root.after(0, lambda: self.status_var.set("✅ Bills processed successfully"))
                    else:
                        self.root.after(0, lambda: self.status_var.set("⚠️  Some bills were skipped or failed"))
                        
                finally:
                    # Restore stdout
                    sys.stdout = old_stdout
                    
            except Exception as e:
                logger.error(f"Error during bill processing: {e}")
                import traceback
                error_msg = f"❌ Error: {e}\n\n{traceback.format_exc()}"
                self.root.after(0, lambda: progress.append_text(error_msg))
                self.root.after(0, lambda: progress.set_complete(False))
                self.root.after(0, lambda: self.status_var.set("❌ Bill processing failed"))
        
        # Start processing in background thread
        processor_thread = threading.Thread(target=run_bill_processor, daemon=True)
        processor_thread.start()
        
        logger.info("Bill Processor started in background")


def main():
    """Main function."""
    # Set up logging
    setup_logging_for_script("simple_bill_entry_gui")
    
    log_stage("Starting Simple Bill Entry GUI")
    
    root = tk.Tk()
    app = SimpleBillEntryGUI(root)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        raise
    finally:
        logger.info("Simple Bill Entry GUI application ended")


if __name__ == "__main__":
    main()
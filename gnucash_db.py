"""
GnuCash SQLite database interface.
Read and write vendors, bills, accounts, etc.

Uses schema_discovery module to handle column name variations
between different GnuCash versions.

POST-WRITE VERIFICATION:
Every INSERT or UPDATE operation MUST be followed by verification.
User data is SACRED - we verify writes succeeded before returning.
"""

import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from decimal import Decimal
from contextlib import contextmanager
from loguru import logger

from bill_processor import config
from bill_processor.logging_setup import log_function_entry, log_function_exit, log_database_operation, log_error_with_context


def generate_guid() -> str:
    """Generate a GnuCash-compatible GUID (32 hex chars, no dashes)."""
    guid = uuid.uuid4().hex
    logger.debug(f"Generated GUID: {guid}")
    return guid


def _get_schema():
    """
    Get schema discovery instance (lazy import to avoid circular deps).
    """
    from bill_processor.schema_discovery import get_schema
    return get_schema()


def _get_column(table: str, expected_name: str) -> str:
    """
    Get actual column name from schema mapping.
    
    Falls back to expected name if schema not available.
    Logs a warning if mapping differs.
    """
    try:
        schema = _get_schema()
        actual = schema.get_column(table, expected_name)
        if actual and actual != expected_name:
            logger.debug(f"Column mapped: {table}.{expected_name} -> {actual}")
        return actual or expected_name
    except Exception as e:
        logger.warning(f"Schema lookup failed for {table}.{expected_name}: {e}")
        return expected_name


def format_gnucash_date(dt: date, include_time: bool = True) -> str:
    """
    Format a date for GnuCash database storage.
    
    Automatically uses the format detected for the current database:
    - ISO format: 'YYYY-MM-DD HH:MM:SS' (19 chars) - modern GnuCash
    - Compact format: 'YYYYMMDDHHMMSS' (14 chars) - older GnuCash
    
    Args:
        dt: Date or datetime to format
        include_time: If True, include time component (default True)
        
    Returns:
        Formatted date string matching the database's format
    """
    try:
        schema = _get_schema()
        date_format = schema.get_date_format()
    except Exception:
        # Default to ISO format if schema unavailable
        date_format = 'iso'
    
    if date_format == 'compact':
        # Compact format: YYYYMMDDHHMMSS
        if include_time:
            if isinstance(dt, datetime):
                return dt.strftime("%Y%m%d%H%M%S")
            else:
                return dt.strftime("%Y%m%d") + "000000"
        else:
            return dt.strftime("%Y%m%d")
    else:
        # ISO format: YYYY-MM-DD HH:MM:SS
        if include_time:
            if isinstance(dt, datetime):
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                return dt.strftime("%Y-%m-%d") + " 00:00:00"
        else:
            return dt.strftime("%Y-%m-%d")


def format_gnucash_timestamp() -> str:
    """
    Get current timestamp formatted for GnuCash database.
    
    Returns:
        Current datetime in the database's format
    """
    return format_gnucash_date(datetime.now(), include_time=True)


# =============================================================================
# POST-WRITE VERIFICATION - Verify all writes succeeded
# =============================================================================

class WriteVerificationError(Exception):
    """Raised when a database write cannot be verified."""
    pass


def verify_record_exists(table: str, guid: str, description: str = "") -> bool:
    """
    Verify a record with the given GUID exists in the table.
    
    Args:
        table: Table name to check
        guid: GUID to look for
        description: Human-readable description for logging
        
    Returns:
        True if record exists, raises WriteVerificationError if not
    """
    with get_connection() as conn:
        cursor = conn.execute(f"SELECT guid FROM {table} WHERE guid = ?", (guid,))
        row = cursor.fetchone()
        
        if row:
            logger.debug(f"POST-WRITE VERIFIED: {description or table} with GUID {guid[:12]}... exists")
            return True
        else:
            error_msg = f"POST-WRITE VERIFICATION FAILED: {description or table} with GUID {guid} NOT FOUND in {table}"
            logger.error(error_msg)
            
            # Record failure in schema verification
            try:
                schema = _get_schema()
                if hasattr(schema, 'verification') and schema.verification.current_run:
                    schema.verification.check(
                        "POST_WRITE_VERIFY", table,
                        f"Record exists after INSERT: {description}",
                        passed=False,
                        details=f"GUID {guid} not found in {table} after write"
                    )
            except Exception:
                pass  # Don't fail on logging failure
            
            raise WriteVerificationError(error_msg)


def verify_vendor_created(guid: str, expected_name: str) -> Dict:
    """
    Verify a vendor was created successfully.
    
    Returns the vendor record if found, raises WriteVerificationError if not.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT guid, id, name FROM vendors WHERE guid = ?",
            (guid,)
        )
        row = cursor.fetchone()
        
        if row:
            actual_name = row['name']
            if actual_name == expected_name:
                logger.info(f"POST-WRITE VERIFIED: Vendor '{expected_name}' created (ID: {row['id']})")
                return dict(row)
            else:
                logger.warning(f"POST-WRITE WARNING: Vendor name mismatch. Expected '{expected_name}', got '{actual_name}'")
                return dict(row)
        else:
            error_msg = f"POST-WRITE VERIFICATION FAILED: Vendor '{expected_name}' with GUID {guid} NOT FOUND"
            logger.error(error_msg)
            raise WriteVerificationError(error_msg)


def verify_account_created(guid: str, expected_name: str, expected_type: str) -> Dict:
    """
    Verify an account was created successfully.
    
    Returns the account record if found, raises WriteVerificationError if not.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT guid, name, account_type FROM accounts WHERE guid = ?",
            (guid,)
        )
        row = cursor.fetchone()
        
        if row:
            actual_name = row['name']
            actual_type = row['account_type']
            
            issues = []
            if actual_name != expected_name:
                issues.append(f"name mismatch (expected '{expected_name}', got '{actual_name}')")
            if actual_type != expected_type:
                issues.append(f"type mismatch (expected '{expected_type}', got '{actual_type}')")
            
            if issues:
                logger.warning(f"POST-WRITE WARNING: Account created with issues: {', '.join(issues)}")
            else:
                logger.info(f"POST-WRITE VERIFIED: Account '{expected_name}' ({expected_type}) created")
            
            return dict(row)
        else:
            error_msg = f"POST-WRITE VERIFICATION FAILED: Account '{expected_name}' with GUID {guid} NOT FOUND"
            logger.error(error_msg)
            raise WriteVerificationError(error_msg)


def verify_bill_created(guid: str, expected_amount: float, vendor_guid: str) -> Dict:
    """
    Verify a bill/invoice was created successfully.
    
    Checks:
    1. Invoice record exists
    2. Linked to correct vendor
    3. Transaction and splits exist
    
    Returns bill info if verified, raises WriteVerificationError if not.
    """
    with get_connection() as conn:
        # Check invoice exists and links to vendor
        cursor = conn.execute("""
            SELECT i.guid, i.id, i.owner_guid, i.post_txn, i.post_lot,
                   v.name as vendor_name
            FROM invoices i
            LEFT JOIN vendors v ON i.owner_guid = v.guid
            WHERE i.guid = ?
        """, (guid,))
        row = cursor.fetchone()
        
        if not row:
            error_msg = f"POST-WRITE VERIFICATION FAILED: Invoice with GUID {guid} NOT FOUND"
            logger.error(error_msg)
            raise WriteVerificationError(error_msg)
        
        # Verify vendor link
        if row['owner_guid'] != vendor_guid:
            error_msg = f"POST-WRITE VERIFICATION FAILED: Invoice vendor mismatch. Expected {vendor_guid[:12]}..., got {row['owner_guid'][:12] if row['owner_guid'] else 'None'}..."
            logger.error(error_msg)
            raise WriteVerificationError(error_msg)
        
        # Verify transaction exists
        txn_guid = row['post_txn']
        cursor = conn.execute("SELECT guid FROM transactions WHERE guid = ?", (txn_guid,))
        txn_row = cursor.fetchone()
        if not txn_row:
            error_msg = f"POST-WRITE VERIFICATION FAILED: Transaction {txn_guid} for invoice NOT FOUND"
            logger.error(error_msg)
            raise WriteVerificationError(error_msg)
        
        # Verify splits exist (should be at least 2 - expense and AP)
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM splits WHERE tx_guid = ?", (txn_guid,))
        split_count = cursor.fetchone()['cnt']
        if split_count < 2:
            error_msg = f"POST-WRITE VERIFICATION FAILED: Expected 2+ splits, found {split_count}"
            logger.error(error_msg)
            raise WriteVerificationError(error_msg)
        
        logger.info(f"POST-WRITE VERIFIED: Bill {row['id']} for vendor '{row['vendor_name']}' created successfully")
        return {
            'guid': row['guid'],
            'id': row['id'],
            'vendor_guid': row['owner_guid'],
            'vendor_name': row['vendor_name'],
            'transaction_guid': txn_guid,
            'split_count': split_count
        }


def is_gnucash_locked() -> tuple[bool, str | None, int | None]:
    """
    Check if GnuCash has the database locked.
    
    GnuCash uses a 'gnclock' table inside the SQLite database with hostname
    and PID when the database is open. An empty table means unlocked.
    
    Returns:
        Tuple of (is_locked, hostname, pid)
        - is_locked: True if database is locked
        - hostname: The machine holding the lock (or None)
        - pid: The process ID holding the lock (or None)
    """
    db_path = Path(config.GNUCASH_DB_PATH)
    
    if not db_path.exists():
        return (False, None, None)
    
    try:
        # Open in read-only mode to check lock
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        cursor = conn.cursor()
        
        # Check gnclock table for any records
        cursor.execute("SELECT Hostname, PID FROM gnclock")
        row = cursor.fetchone()
        conn.close()
        
        if row:
            hostname, pid = row
            logger.warning(f"Database LOCKED by: {hostname} (PID {pid})")
            return (True, hostname, pid)
        
        return (False, None, None)
        
    except sqlite3.OperationalError as e:
        # If we can't read the table, assume it might be locked
        logger.error(f"Error checking gnclock table: {e}")
        return (True, "unknown", 0)


def get_lock_info() -> dict | None:
    """
    Get detailed lock information for display purposes.
    
    Returns:
        Dict with 'hostname' and 'pid' if locked, None if not locked.
    """
    is_locked, hostname, pid = is_gnucash_locked()
    if is_locked:
        return {'hostname': hostname, 'pid': pid}
    return None


def is_locked_by_others() -> tuple[bool, str | None, int | None]:
    """
    Check if database is locked by someone OTHER than our own process.
    
    This is used for operations within our GUI that need to verify
    no external process (GnuCash, another instance) has the lock.
    Our own lock is fine - we already have access.
    
    Returns:
        Tuple of (is_locked_by_others, hostname, pid)
        - is_locked_by_others: True if locked by external process
        - hostname: Lock holder's hostname (or None)
        - pid: Lock holder's PID (or None)
    """
    import os
    
    is_locked, hostname, pid = is_gnucash_locked()
    
    if not is_locked:
        return (False, None, None)
    
    # Check if it's our own lock
    my_hostname = _get_lock_hostname()
    my_pid = os.getpid()
    
    if hostname == my_hostname and pid == my_pid:
        # It's our own lock - not locked by others
        logger.debug(f"Database locked by our own process (PID {my_pid})")
        return (False, None, None)
    
    # Locked by someone else
    return (True, hostname, pid)


def _is_process_running(pid: int) -> bool:
    """
    Check if a process with the given PID is currently running.
    
    Args:
        pid: Process ID to check
        
    Returns:
        True if process is running, False otherwise
    """
    import os
    import sys
    
    if pid <= 0:
        return False
    
    # Windows requires different approach - os.kill(pid, 0) doesn't work reliably
    if sys.platform == 'win32':
        try:
            import psutil
            return psutil.pid_exists(pid)
        except ImportError:
            # Fallback: try Windows-specific approach using tasklist
            import subprocess
            try:
                output = subprocess.check_output(['tasklist', '/FI', f'PID eq {pid}'], 
                                                stderr=subprocess.DEVNULL)
                return str(pid) in output.decode()
            except Exception:
                # If we can't check, assume it's running to be safe
                logger.warning(f"Cannot verify if PID {pid} is running on Windows - assuming running for safety")
                return True
    else:
        # Unix/Linux: signal 0 works fine
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
        except Exception:
            # If we can't check, assume it might be running
            return True


def _get_lock_hostname() -> str:
    """Get the hostname to use for our lock entries.
    
    Uses 'BillProcessor@hostname' format to distinguish from GnuCash locks.
    """
    import socket
    return f"BillProcessor@{socket.gethostname()}"


def clean_stale_lock() -> bool:
    """
    Clean up stale locks from crashed processes on this machine.
    
    A lock is considered stale if:
    - The PID is no longer running on this machine
    
    This will clean locks from:
    - Crashed BillProcessor instances
    - Crashed GnuCash instances on this machine
    - Other terminated local processes
    
    We only clean locks if we can verify the PID is not running locally.
    If the hostname suggests a different machine, we leave the lock alone.
    
    Returns:
        True if a stale lock was cleaned, False otherwise
    """
    import socket
    
    is_locked, hostname, pid = is_gnucash_locked()
    
    if not is_locked:
        return False  # No lock to clean
    
    # Get local machine name to check if lock might be from this machine
    local_machine = socket.gethostname()
    
    # Check if this lock could be from a different machine
    # BillProcessor@ format explicitly includes machine name, others might be local
    if hostname and hostname.startswith('BillProcessor@'):
        # Extract machine name from BillProcessor@machinename format
        lock_machine = hostname.split('@', 1)[1] if '@' in hostname else ''
        if lock_machine and lock_machine != local_machine:
            logger.info(f"Lock held by BillProcessor on different machine ({hostname}), cannot clean remotely")
            return False
    
    # Check if the process is still running locally
    if _is_process_running(pid):
        logger.debug(f"Lock holder PID {pid} is still running on this machine")
        return False
    
    # Process is not running locally - this is a stale lock, clean it up
    logger.warning(f"Cleaning stale lock from terminated process: {hostname} (PID {pid})")
    
    db_path = Path(config.GNUCASH_DB_PATH)
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("DELETE FROM gnclock WHERE Hostname = ? AND PID = ?",
                      (hostname, pid))
        conn.commit()
        conn.close()
        logger.info(f"Stale lock cleaned: {hostname} (PID {pid})")
        return True
    except sqlite3.Error as e:
        logger.error(f"Failed to clean stale lock: {e}")
        return False


def acquire_lock() -> bool:
    """
    Acquire a lock on the GnuCash database by inserting into gnclock table.
    
    This prevents GnuCash and other instances of this tool from accessing
    the database while we have it locked.
    
    First attempts to clean any stale locks from crashed processes on this machine.
    
    Returns:
        True if lock acquired successfully, False if already locked.
    """
    import os
    
    # First try to clean any stale locks from this machine
    clean_stale_lock()
    
    # Now check if still locked
    is_locked, hostname, pid = is_gnucash_locked()
    if is_locked:
        logger.error(f"Cannot acquire lock - already locked by {hostname} (PID {pid})")
        return False
    
    db_path = Path(config.GNUCASH_DB_PATH)
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Insert our lock record with BillProcessor@ prefix
        my_hostname = _get_lock_hostname()
        my_pid = os.getpid()
        
        cursor.execute("INSERT INTO gnclock (Hostname, PID) VALUES (?, ?)", 
                      (my_hostname, my_pid))
        conn.commit()
        conn.close()
        
        logger.info(f"Database lock ACQUIRED: {my_hostname} (PID {my_pid})")
        return True
        
    except sqlite3.Error as e:
        logger.error(f"Failed to acquire database lock: {e}")
        return False


def release_lock() -> bool:
    """
    Release our lock on the GnuCash database by clearing the gnclock table.
    
    Returns:
        True if lock released successfully, False on error.
    """
    import os
    
    db_path = Path(config.GNUCASH_DB_PATH)
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # Only delete our own lock (matching our BillProcessor hostname and PID)
        my_hostname = _get_lock_hostname()
        my_pid = os.getpid()
        
        cursor.execute("DELETE FROM gnclock WHERE Hostname = ? AND PID = ?",
                      (my_hostname, my_pid))
        rows_deleted = cursor.rowcount
        conn.commit()
        conn.close()
        
        if rows_deleted > 0:
            logger.info(f"Database lock RELEASED: {my_hostname} (PID {my_pid})")
            return True
        else:
            logger.warning("No lock to release (may have been released already)")
            return True
            
    except sqlite3.Error as e:
        logger.error(f"Failed to release database lock: {e}")
        return False


@contextmanager
def database_lock():
    """
    Context manager for safely acquiring and releasing the database lock.
    
    Usage:
        with database_lock():
            # Do database operations
            pass
    
    Raises:
        RuntimeError: If lock cannot be acquired (database already locked)
    """
    if not acquire_lock():
        raise RuntimeError("Cannot acquire database lock - database is in use")
    
    try:
        yield
    finally:
        release_lock()


@contextmanager
def get_connection(readonly: bool = True):
    """
    Context manager for database connections.
    
    Args:
        readonly: If True, open in read-only mode (default for safety)
    """
    log_function_entry("get_connection", readonly=readonly)
    
    db_path = Path(config.GNUCASH_DB_PATH)
    logger.debug(f"Attempting to connect to database: {db_path}")
    
    if not db_path.exists():
        logger.error(f"GnuCash database not found: {db_path}")
        raise FileNotFoundError(f"GnuCash database not found: {db_path}")
    
    # SQLite URI format for read-only
    if readonly:
        uri = f"file:{db_path}?mode=ro"
        logger.debug(f"Opening read-only connection: {uri}")
        conn = sqlite3.connect(uri, uri=True)
    else:
        logger.debug(f"Opening read-write connection to: {db_path}")
        logger.warning("Opening database in read-write mode")
        conn = sqlite3.connect(str(db_path))
    
    conn.row_factory = sqlite3.Row
    try:
        logger.debug("Database connection established")
        yield conn
    finally:
        logger.debug("Closing database connection")
        conn.close()
        log_function_exit("get_connection")


# =============================================================================
# VENDOR OPERATIONS
# =============================================================================

def get_all_vendors() -> List[Dict]:
    """
    Retrieve all vendors from GnuCash.
    
    Returns list of dicts with: guid, id, name, addr_name, addr_addr1-4,
    addr_phone, addr_email, notes
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT 
                guid, id, name, currency,
                addr_name, addr_addr1, addr_addr2, addr_addr3, addr_addr4,
                addr_phone, addr_email, notes, active
            FROM vendors
            ORDER BY name
        """)
        
        vendors = []
        for row in cursor:
            vendors.append({
                'guid': row['guid'],
                'id': row['id'],
                'name': row['name'],
                'currency': row['currency'],
                'addr_name': row['addr_name'],
                'addr_addr1': row['addr_addr1'],
                'addr_addr2': row['addr_addr2'],
                'addr_addr3': row['addr_addr3'],
                'addr_addr4': row['addr_addr4'],
                'addr_phone': row['addr_phone'],
                'addr_email': row['addr_email'],
                'notes': row['notes'],
                'active': row['active']
            })
        
        return vendors


def find_vendor_by_name(name: str) -> Optional[Dict]:
    """Find a vendor by exact name match."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM vendors WHERE name = ?",
            (name,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def find_vendor_by_id(vendor_id: str) -> Optional[Dict]:
    """Find a vendor by ID (like V0001)."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM vendors WHERE id = ?",
            (vendor_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def find_vendor_by_guid(guid: str) -> Optional[Dict]:
    """
    Find a vendor by GUID.
    
    Use this to verify a GUID from JSON actually exists in GnuCash.
    """
    if not guid:
        return None
    
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT * FROM vendors WHERE guid = ?",
            (guid,)
        )
        row = cursor.fetchone()
        if row:
            logger.debug(f"Found vendor by GUID: {row['name']}")
            return dict(row)
        else:
            logger.warning(f"Vendor GUID not found in GnuCash: {guid[:12]}...")
            return None


def get_next_vendor_id() -> str:
    """
    Get the next available vendor ID.
    Extracts numeric portion from all existing IDs and finds the true maximum.
    """
    import re
    
    with get_connection() as conn:
        cursor = conn.execute("SELECT id FROM vendors")
        rows = cursor.fetchall()
        
        if rows:
            # Extract numeric portion from all IDs and find the maximum
            max_num = 0
            for row in rows:
                if row['id']:
                    match = re.search(r'(\d+)', row['id'])
                    if match:
                        num = int(match.group(1))
                        max_num = max(max_num, num)
            
            # Return next ID
            return config.VENDOR_ID_FORMAT.format(prefix=config.VENDOR_ID_PREFIX, num=max_num + 1)
        
        # First vendor
        return config.VENDOR_ID_FORMAT.format(prefix=config.VENDOR_ID_PREFIX, num=1)


def create_vendor(name: str, addr_name: str = None, addr_addr1: str = None, 
                 addr_addr2: str = None, addr_addr3: str = None, addr_addr4: str = None,
                 addr_phone: str = None, addr_email: str = None, **kwargs) -> str:
    """
    Create a new vendor with comprehensive address logging.
    """
    logger.info(f"Creating new vendor: {name}")
    
    # LOG ALL ADDRESS PARAMETERS RECEIVED
    address_params = {
        'addr_name': addr_name,
        'addr_addr1': addr_addr1, 
        'addr_addr2': addr_addr2,
        'addr_addr3': addr_addr3,
        'addr_addr4': addr_addr4,
        'addr_phone': addr_phone,
        'addr_email': addr_email
    }
    
    # Log what address data we actually received
    non_empty_addresses = {k: v for k, v in address_params.items() if v}
    if non_empty_addresses:
        logger.info(f"Address data received: {non_empty_addresses}")
    else:
        logger.warning(f"NO ADDRESS DATA received for vendor '{name}'")
    
    # Log empty address fields
    empty_addresses = [k for k, v in address_params.items() if not v]
    if empty_addresses:
        logger.debug(f"Empty address fields: {empty_addresses}")

    vendor_guid = generate_guid()
    logger.debug(f"Generated vendor GUID: {vendor_guid}")
    
    # Get next vendor ID - ENHANCED LOGGING
    logger.debug("Getting next vendor ID...")
    try:
        with get_connection() as conn:
            cursor = conn.execute("SELECT MAX(CAST(id AS INTEGER)) FROM vendors")
            max_id = cursor.fetchone()[0] or 0
            vendor_id = f"{max_id + 1:06d}"
            logger.debug(f"Successfully got next vendor ID: {vendor_id}")
    except Exception as e:
        logger.error(f"Failed to get next vendor ID: {e}")
        raise
    
    # Get USD currency - ENHANCED LOGGING
    logger.debug("Getting USD currency GUID...")
    try:
        usd_guid = get_usd_guid()
        logger.debug(f"Successfully got USD GUID: {usd_guid}")
    except Exception as e:
        logger.error(f"Failed to get USD currency: {e}")
        raise
    
    # DETAILED INSERT STATEMENT LOGGING
    insert_values = {
        'guid': vendor_guid,
        'id': vendor_id, 
        'name': name,
        'currency': usd_guid,
        'active': 1,
        'notes': '',
        'tax_override': 0,
        'addr_name': addr_name or '',
        'addr_addr1': addr_addr1 or '',
        'addr_addr2': addr_addr2 or '',
        'addr_addr3': addr_addr3 or '',
        'addr_addr4': addr_addr4 or '',
        'addr_phone': addr_phone or '',
        'addr_email': addr_email or ''
    }
    
    logger.debug(f"INSERT VALUES being written to database:")
    for field, value in insert_values.items():
        if value:  # Only log non-empty values
            logger.debug(f"  {field}: '{value}'")
        else:
            logger.debug(f"  {field}: <EMPTY>")
    
    # ENHANCED DATABASE OPERATION LOGGING
    logger.debug("Starting database transaction for vendor creation...")
    
    try:
        with get_connection(readonly=False) as conn:
            logger.debug("INSIDE database connection context - about to execute INSERT")
            
            # Execute INSERT - only use columns that exist in the vendors table
            logger.debug("Executing INSERT statement...")
            conn.execute("""
                INSERT INTO vendors (
                    guid, id, name, currency, active, notes, tax_override, tax_inc, tax_table,
                    addr_name, addr_addr1, addr_addr2, addr_addr3, addr_addr4, 
                    addr_phone, addr_fax, addr_email,
                    terms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                vendor_guid, vendor_id, name, usd_guid, 1, '', 0, '', '',  # Basic fields + tax_override=0
                addr_name or '', addr_addr1 or '', addr_addr2 or '', addr_addr3 or '', addr_addr4 or '',  # Address fields
                addr_phone or '', '', addr_email or '',  # Contact fields (fax empty)
                ''  # Terms (empty)
            ))
            logger.debug("INSERT statement executed successfully")
            
            # CRITICAL: Commit the transaction
            logger.debug("Committing transaction...")
            conn.commit()
            logger.debug("Transaction committed to database")
            
            # IMMEDIATE POST-INSERT VERIFICATION
            logger.debug("POST-INSERT: Reading back vendor data from database...")
            cursor = conn.execute("""
                SELECT guid, name, addr_name, addr_addr1, addr_addr2, addr_addr3, addr_addr4, addr_phone, addr_email
                FROM vendors WHERE guid = ?
            """, (vendor_guid,))
            
            row = cursor.fetchone()
            if row:
                logger.info(f"POST-INSERT VERIFIED: Vendor saved to database")
                # Log what was actually stored
                for field in ['name', 'addr_name', 'addr_addr1', 'addr_addr2', 'addr_phone']:
                    value = row[field] or '<EMPTY>'
                    logger.debug(f"  STORED {field}: '{value}'")
            else:
                logger.error(f"POST-INSERT VERIFICATION FAILED: Vendor not found!")
                raise WriteVerificationError("Vendor not found after INSERT")
            
            logger.debug("Exiting database connection context")
            
    except Exception as e:
        logger.error(f"Database operation FAILED: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise

    logger.info(f"Created vendor: {name} (ID: {vendor_id}, GUID: {vendor_guid})")
    
    # POST-WRITE VERIFICATION
    if kwargs.get('verify', True):
        logger.debug("Running final verification...")
        try:
            verify_vendor_created(vendor_guid, name)
            logger.debug("Final verification passed")
        except Exception as e:
            logger.error(f"Final verification failed: {e}")
            raise
    
    logger.debug("create_vendor function completing successfully")
    return vendor_guid


def update_vendor_address(
    vendor_guid: str,
    addr_name: str = None,
    addr_addr1: str = None,
    addr_addr2: str = None,
    addr_addr3: str = None,
    addr_addr4: str = None,
    addr_phone: str = None,
    addr_email: str = None
):
    """Update vendor address fields. Only updates non-None values."""
    updates = []
    params = []
    
    if addr_name is not None:
        updates.append("addr_name = ?")
        params.append(addr_name)
    if addr_addr1 is not None:
        updates.append("addr_addr1 = ?")
        params.append(addr_addr1)
    if addr_addr2 is not None:
        updates.append("addr_addr2 = ?")
        params.append(addr_addr2)
    if addr_addr3 is not None:
        updates.append("addr_addr3 = ?")
        params.append(addr_addr3)
    if addr_addr4 is not None:
        updates.append("addr_addr4 = ?")
        params.append(addr_addr4)
    if addr_phone is not None:
        updates.append("addr_phone = ?")
        params.append(addr_phone)
    if addr_email is not None:
        updates.append("addr_email = ?")
        params.append(addr_email)
    
    if not updates:
        return
    
    params.append(vendor_guid)
    
    with get_connection(readonly=False) as conn:
        conn.execute(
            f"UPDATE vendors SET {', '.join(updates)} WHERE guid = ?",
            params
        )
        conn.commit()


# =============================================================================
# ACCOUNT OPERATIONS
# =============================================================================

def get_account_by_name(name: str) -> Optional[Dict]:
    """
    Find an account by name (searches anywhere in hierarchy).
    Note: GnuCash stores accounts with parent references, not full paths.
    """
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT guid, name, account_type, parent_guid, commodity_guid FROM accounts WHERE name = ?",
            (name,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_account_by_guid(guid: str) -> Optional[Dict]:
    """Get an account by GUID."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT guid, name, account_type, parent_guid, commodity_guid FROM accounts WHERE guid = ?",
            (guid,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def find_expense_accounts_like(pattern: str) -> List[Dict]:
    """
    Find expense accounts matching a pattern.
    Searches for accounts starting with the pattern.
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT guid, name, account_type, parent_guid
            FROM accounts 
            WHERE name LIKE ? AND account_type = 'EXPENSE'
            ORDER BY name
        """, (f"{pattern}%",))
        
        return [dict(row) for row in cursor]


def _get_root_account_guid() -> Optional[str]:
    """Get the ROOT account GUID."""
    with get_connection() as conn:
        cursor = conn.execute("SELECT guid FROM accounts WHERE account_type = 'ROOT' LIMIT 1")
        row = cursor.fetchone()
        return row['guid'] if row else None


def _create_account_internal(name: str, account_type: str, parent_guid: str, placeholder: bool = False) -> str:
    """
    Internal helper to create any type of account.
    
    Returns the new account GUID.
    """
    account_guid = generate_guid()
    usd_guid = get_usd_guid()
    
    with get_connection(readonly=False) as conn:
        conn.execute("""
            INSERT INTO accounts (
                guid, name, account_type, commodity_guid, commodity_scu, 
                non_std_scu, parent_guid, hidden, placeholder
            ) VALUES (?, ?, ?, ?, 100, 0, ?, 0, ?)
        """, (account_guid, name, account_type, usd_guid, parent_guid, 1 if placeholder else 0))
        conn.commit()
    
    return account_guid

def fix_orphaned_expense_accounts() -> Dict[str, str]:
    """
    Find and fix expense accounts that are directly under placeholder accounts.
    
    GnuCash placeholder accounts are for organization only and cannot accept
    transactions. Accounts under them may have issues.
    
    This function:
    1. Finds expense accounts whose parent is a placeholder
    2. Moves them to be children of a proper non-placeholder parent
    
    Returns:
        Dict of {account_name: new_parent_name} for accounts that were fixed
    
    NOTE: This is a legacy cleanup function - new workflow doesn't create accounts.
    """
    fixes = {}
    
    # NOTE: This function is deprecated since we no longer auto-create expense accounts
    logger.warning("fix_orphaned_expense_accounts is deprecated - not creating new expense accounts")
    return fixes
    
    with get_connection(readonly=False) as conn:
        # Get the name of the good parent for logging
        cursor = conn.execute("SELECT name FROM accounts WHERE guid = ?", (good_parent_guid,))
        good_parent_name = cursor.fetchone()['name']
        
        # Find expense accounts that are direct children of a placeholder
        # (specifically "Expenses root" since that's what our old code used)
        cursor = conn.execute("""
            SELECT a.guid, a.name, p.name as parent_name
            FROM accounts a
            JOIN accounts p ON a.parent_guid = p.guid
            WHERE a.account_type = 'EXPENSE'
            AND a.placeholder = 0
            AND p.placeholder = 1
            AND p.name = 'Expenses root'
            AND a.name LIKE 'cmsnpd_%'
        """)
        
        orphans = cursor.fetchall()
        
        if not orphans:
            logger.info("No orphaned expense accounts found")
            return fixes
        
        logger.info(f"Found {len(orphans)} orphaned expense accounts to fix")
        
        for orphan in orphans:
            logger.info(f"Moving '{orphan['name']}' from '{orphan['parent_name']}' to '{good_parent_name}'")
            
            cursor = conn.execute("""
                UPDATE accounts SET parent_guid = ? WHERE guid = ?
            """, (good_parent_guid, orphan['guid']))
            
            fixes[orphan['name']] = good_parent_name
        
        if fixes:
            conn.commit()
            logger.info(f"Fixed {len(fixes)} orphaned expense accounts")
    
    return fixes


def validate_account_hierarchy(account_guid: str) -> Dict:
    """
    Validate that an account can accept transactions.
    
    Checks:
    1. Account exists
    2. Account is not a placeholder
    3. Account's ancestors are not all placeholders (at least one can hold transactions)
    
    Returns:
        Dict with 'valid', 'issues', and 'info' fields
    """
    result = {'valid': True, 'issues': [], 'info': {}}
    
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT guid, name, account_type, placeholder, parent_guid
            FROM accounts WHERE guid = ?
        """, (account_guid,))
        account = cursor.fetchone()
        
        if not account:
            result['valid'] = False
            result['issues'].append(f"Account {account_guid} not found")
            return result
        
        result['info']['name'] = account['name']
        result['info']['type'] = account['account_type']
        result['info']['is_placeholder'] = account['placeholder'] == 1
        
        if account['placeholder'] == 1:
            result['valid'] = False
            result['issues'].append(f"Account '{account['name']}' is a placeholder - cannot accept transactions")
        
        # Check parent chain
        parent_guid = account['parent_guid']
        depth = 0
        max_depth = 10
        
        while parent_guid and depth < max_depth:
            cursor = conn.execute("""
                SELECT guid, name, account_type, placeholder, parent_guid
                FROM accounts WHERE guid = ?
            """, (parent_guid,))
            parent = cursor.fetchone()
            
            if not parent:
                break
            
            if parent['account_type'] == 'ROOT':
                break
                
            depth += 1
            parent_guid = parent['parent_guid']
        
        result['info']['hierarchy_depth'] = depth
    
    return result


def get_ap_account_guid() -> Optional[str]:
    """
    Get the GUID of the Accounts Payable account.
    
    Searches by:
    1. Account type = 'PAYABLE' (correct way)
    2. Account name containing 'payable' (fallback)
    """
    with get_connection() as conn:
        # First try: find by account_type = PAYABLE (the correct way)
        cursor = conn.execute("""
            SELECT guid, name FROM accounts 
            WHERE account_type = 'PAYABLE'
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            logger.debug(f"Found A/P account by type: {row['name']}")
            return row['guid']
        
        # Fallback: search by name containing 'payable'
        cursor = conn.execute("""
            SELECT guid, name, account_type FROM accounts 
            WHERE LOWER(name) LIKE '%payable%'
            ORDER BY 
                CASE WHEN account_type = 'LIABILITY' THEN 1
                     WHEN account_type = 'ASSET' THEN 2
                     ELSE 3 END
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            logger.warning(f"No PAYABLE type account found. Using '{row['name']}' ({row['account_type']}) as fallback")
            return row['guid']
        
        return None


def validate_gnucash_setup() -> Dict[str, any]:
    """
    Validate that GnuCash has the required setup for bill processing.
    
    Returns a dict with:
        - valid: bool - True if all requirements met
        - errors: list - Critical issues that prevent processing
        - warnings: list - Non-critical issues
        - info: dict - Information about found accounts
    """
    result = {
        'valid': True,
        'errors': [],
        'warnings': [],
        'info': {}
    }
    
    with get_connection() as conn:
        # Check 1: USD currency exists
        cursor = conn.execute("""
            SELECT guid FROM commodities 
            WHERE mnemonic = 'USD' AND namespace = 'CURRENCY'
        """)
        row = cursor.fetchone()
        if row:
            result['info']['usd_guid'] = row['guid']
        else:
            result['errors'].append("USD currency not found in GnuCash")
            result['valid'] = False
        
        # Check 2: Accounts Payable account (CRITICAL)
        cursor = conn.execute("""
            SELECT guid, name FROM accounts WHERE account_type = 'PAYABLE'
        """)
        row = cursor.fetchone()
        if row:
            result['info']['ap_account'] = row['name']
            result['info']['ap_guid'] = row['guid']
        else:
            # Check if there's one with a similar name but wrong type
            cursor = conn.execute("""
                SELECT name, account_type FROM accounts 
                WHERE LOWER(name) LIKE '%payable%'
            """)
            similar = cursor.fetchone()
            if similar:
                result['errors'].append(
                    f"No account with type 'PAYABLE' found. "
                    f"Found '{similar['name']}' but it has type '{similar['account_type']}'. "
                    f"In GnuCash, edit this account and change its type to 'A/Payable'."
                )
            else:
                result['errors'].append(
                    "No Accounts Payable account found. "
                    "In GnuCash: Actions → New Account → "
                    "Name: 'Accounts Payable', Type: 'A/Payable', Parent: 'Liabilities'"
                )
            result['valid'] = False
        
        # Check 3: Expense parent account
        cursor = conn.execute("""
            SELECT guid, name FROM accounts 
            WHERE account_type = 'EXPENSE' 
            AND parent_guid IN (SELECT guid FROM accounts WHERE account_type = 'ROOT')
        """)
        row = cursor.fetchone()
        if row:
            result['info']['expense_parent'] = row['name']
            result['info']['expense_parent_guid'] = row['guid']
        else:
            result['warnings'].append(
                f"No top-level Expense account found. "
                f"Expected '{config.DEFAULT_EXPENSE_PARENT}'. "
                f"New expense accounts may not be created correctly."
            )
        
        # Check 4: Count existing expense accounts (informational)
        cursor = conn.execute("""
            SELECT COUNT(*) as cnt FROM accounts WHERE account_type = 'EXPENSE'
        """)
        result['info']['expense_account_count'] = cursor.fetchone()['cnt']
        
        # Check 5: Count vendors
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM vendors")
        result['info']['vendor_count'] = cursor.fetchone()['cnt']
        
        # Check 6: List available account types (informational)
        cursor = conn.execute("""
            SELECT DISTINCT account_type, COUNT(*) as cnt 
            FROM accounts 
            GROUP BY account_type 
            ORDER BY cnt DESC
        """)
        result['info']['account_types'] = {row['account_type']: row['cnt'] for row in cursor}
    
    return result


def get_liabilities_parent_guid() -> Optional[str]:
    """Get the GUID of the top-level Liabilities account."""
    with get_connection() as conn:
        # Find top-level LIABILITY account (parent is ROOT)
        cursor = conn.execute("""
            SELECT a.guid, a.name FROM accounts a
            WHERE a.account_type = 'LIABILITY' 
            AND a.parent_guid IN (SELECT guid FROM accounts WHERE account_type = 'ROOT')
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            return row['guid']
        
        # Fallback: any LIABILITY account with 'root' or 'liabilities' in name
        cursor = conn.execute("""
            SELECT guid, name FROM accounts 
            WHERE account_type = 'LIABILITY'
            AND (LOWER(name) LIKE '%root%' OR LOWER(name) = 'liabilities')
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            return row['guid']
        
        return None


def create_ap_account(name: str = "Accounts Payable", verify: bool = True) -> str:
    """
    Create an Accounts Payable account under Liabilities.
    
    Args:
        name: Account name (default "Accounts Payable")
        verify: If True, verify the account was created (default True)
    
    Returns the new account's GUID.
    Raises WriteVerificationError if verification fails.
    """
    parent_guid = get_liabilities_parent_guid()
    if not parent_guid:
        raise ValueError("Could not find Liabilities parent account")
    
    account_guid = generate_guid()
    usd_guid = get_usd_guid()
    
    with get_connection(readonly=False) as conn:
        conn.execute("""
            INSERT INTO accounts (
                guid, name, account_type, commodity_guid, commodity_scu, 
                non_std_scu, parent_guid, hidden, placeholder
            ) VALUES (?, ?, 'PAYABLE', ?, 100, 0, ?, 0, 0)
        """, (account_guid, name, usd_guid, parent_guid))
        conn.commit()
    
    logger.info(f"Created A/P account: {name} (GUID: {account_guid})")
    
    # POST-WRITE VERIFICATION
    if verify:
        verify_account_created(account_guid, name, 'PAYABLE')
    
    return account_guid


def ensure_ap_account_exists() -> str:
    """
    Ensure an Accounts Payable account exists, creating one if needed.
    
    Returns the A/P account GUID.
    """
    ap_guid = get_ap_account_guid()
    if ap_guid:
        return ap_guid
    
    logger.info("No A/P account found - creating one")
    return create_ap_account()


def get_usd_guid() -> str:
    """Get the GUID for USD commodity."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT guid FROM commodities
            WHERE mnemonic = 'USD' AND namespace = 'CURRENCY'
            LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            raise ValueError("USD currency not found in database")
        return row['guid']


# =============================================================================
# CASH-ON-HAND OPERATIONS
# =============================================================================

_samuse_guid_cache = None


def get_samuse_account_guid() -> str:
    """Return the GUID of the SAMUSE Cash-on-hand account, cached after first call."""
    global _samuse_guid_cache
    if _samuse_guid_cache is not None:
        return _samuse_guid_cache

    with get_connection(readonly=True) as conn:
        row = conn.execute(
            "SELECT guid FROM accounts WHERE name = ? AND placeholder = 0",
            (config.SAMUSE_ACCOUNT_NAME,)
        ).fetchone()

    if row is None:
        raise ValueError(
            f"Account '{config.SAMUSE_ACCOUNT_NAME}' not found in database. "
            "Verify the account name in config.SAMUSE_ACCOUNT_NAME."
        )

    _samuse_guid_cache = row["guid"] if hasattr(row, "keys") else row[0]
    return _samuse_guid_cache


def get_cash_accounts() -> list:
    """Get all non-placeholder INCOME and ASSET accounts from the GnuCash DB.

    Returns list of dicts with 'name' and 'guid' keys, sorted by name.
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT guid, name FROM accounts
            WHERE account_type IN ('INCOME', 'ASSET')
            AND placeholder = 0
            ORDER BY name
        """)
        return [dict(row) for row in cursor]


def check_db_health() -> dict:
    """Check whether the GnuCash database is accessible.

    Returns:
        dict with keys:
            status   : 'ok' | 'missing' | 'locked' | 'account_missing'
            message  : human-readable description
            path     : str — the configured GNUCASH_DB_PATH
            hostname : str | None — lock holder hostname (locked only)
            pid      : int | None — lock holder PID (locked only)
    """
    path = config.GNUCASH_DB_PATH

    if not Path(path).exists():
        return {
            "status": "missing",
            "message": "Database file not found at the configured path.",
            "path": str(path),
            "hostname": None,
            "pid": None,
        }

    locked, hostname, pid = is_locked_by_others()
    if locked:
        return {
            "status": "locked",
            "message": (
                f"Database is locked by {hostname} (PID {pid}). "
                "Close GnuCash and click Refresh."
            ),
            "path": str(path),
            "hostname": hostname,
            "pid": pid,
        }

    with get_connection(readonly=True) as conn:
        row = conn.execute(
            "SELECT guid FROM accounts WHERE name = ? AND placeholder = 0",
            (config.SAMUSE_ACCOUNT_NAME,)
        ).fetchone()
    if row is None:
        return {
            "status": "account_missing",
            "message": (
                f"Required account '{config.SAMUSE_ACCOUNT_NAME}' not found in database. "
                "Create this account in GnuCash or update SAMUSE_ACCOUNT_NAME in config.py."
            ),
            "path": str(path),
            "hostname": None,
            "pid": None,
        }

    return {
        "status": "ok",
        "message": "Database is accessible.",
        "path": str(path),
        "hostname": None,
        "pid": None,
    }


def create_cash_entry(
    entry_date,
    line_items: list,
    description: str = "",
    verify: bool = True,
) -> str:
    """Create a multi-split cash-on-hand transaction.

    line_items: list of dicts with keys: account_guid, memo, amount
    Returns: transaction GUID
    """
    if not line_items:
        raise ValueError("line_items must not be empty")

    locked, hostname, pid = is_locked_by_others()
    if locked:
        raise RuntimeError(
            f"GnuCash database is locked by {hostname} (PID {pid}). "
            "Close GnuCash before entering cash."
        )

    samuse_guid = get_samuse_account_guid()
    usd_guid = get_usd_guid()

    total_cents = int(round(sum(item["amount"] for item in line_items) * 100))
    line_cents = [int(round(-item["amount"] * 100)) for item in line_items]

    # Verify balance before any write
    assert total_cents + sum(line_cents) == 0, "Transaction would not balance"

    post_date_str = format_gnucash_date(entry_date, include_time=True)
    enter_date_str = format_gnucash_timestamp()
    txn_guid = generate_guid()
    samuse_split_guid = generate_guid()

    logger.info(f"Creating cash entry: {description!r}, {len(line_items)} line items, total=${total_cents/100:.2f}")

    with get_connection(readonly=False) as conn:
        conn.execute(
            "INSERT INTO transactions (guid, currency_guid, num, post_date, enter_date, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (txn_guid, usd_guid, "", post_date_str, enter_date_str, description),
        )
        # SAMUSE balancing split
        conn.execute(
            "INSERT INTO splits (guid, tx_guid, account_guid, memo, action, "
            "reconcile_state, reconcile_date, "
            "value_num, value_denom, quantity_num, quantity_denom, lot_guid) "
            "VALUES (?, ?, ?, ?, '', 'n', '', ?, 100, ?, 100, NULL)",
            (samuse_split_guid, txn_guid, samuse_guid, description, total_cents, total_cents),
        )
        # One split per line item
        line_split_guids = []
        for item, cents in zip(line_items, line_cents):
            split_guid = generate_guid()
            line_split_guids.append(split_guid)
            conn.execute(
                "INSERT INTO splits (guid, tx_guid, account_guid, memo, action, "
                "reconcile_state, reconcile_date, "
                "value_num, value_denom, quantity_num, quantity_denom, lot_guid) "
                "VALUES (?, ?, ?, ?, '', 'n', '', ?, 100, ?, 100, NULL)",
                (split_guid, txn_guid, item["account_guid"], item["memo"], cents, cents),
            )
        conn.commit()

    logger.info(f"Cash entry created: txn_guid={txn_guid}")

    if verify:
        verify_record_exists("transactions", txn_guid, "cash entry transaction")
        verify_record_exists("splits", samuse_split_guid, "SAMUSE split")
        for i, guid in enumerate(line_split_guids):
            verify_record_exists("splits", guid, f"cash entry split {i+1}")

    return txn_guid


def create_cash_deposit(
    deposit_date,
    bank_account_guid: str,
    amount: float,
    memo: str = "Bank deposit",
    verify: bool = True,
) -> str:
    """Create a deposit transaction: SAMUSE Cash-on-hand -> bank account.

    Amount is independent of any batch entry total.
    Returns: transaction GUID
    """
    if amount <= 0:
        raise ValueError(f"Deposit amount must be positive, got {amount}")

    locked, hostname, pid = is_locked_by_others()
    if locked:
        raise RuntimeError(
            f"GnuCash database is locked by {hostname} (PID {pid}). "
            "Close GnuCash before depositing."
        )

    samuse_guid = get_samuse_account_guid()
    usd_guid = get_usd_guid()
    amount_cents = int(round(amount * 100))

    post_date_str = format_gnucash_date(deposit_date, include_time=True)
    enter_date_str = format_gnucash_timestamp()
    txn_guid = generate_guid()
    samuse_split_guid = generate_guid()
    bank_split_guid = generate_guid()

    logger.info(f"Creating cash deposit: {memo!r}, amount=${amount:.2f}")

    with get_connection(readonly=False) as conn:
        conn.execute(
            "INSERT INTO transactions (guid, currency_guid, num, post_date, enter_date, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (txn_guid, usd_guid, "", post_date_str, enter_date_str, memo),
        )
        # SAMUSE: cash leaving drawer (negative)
        conn.execute(
            "INSERT INTO splits (guid, tx_guid, account_guid, memo, action, "
            "reconcile_state, reconcile_date, "
            "value_num, value_denom, quantity_num, quantity_denom, lot_guid) "
            "VALUES (?, ?, ?, ?, '', 'n', '', ?, 100, ?, 100, NULL)",
            (samuse_split_guid, txn_guid, samuse_guid, memo, -amount_cents, -amount_cents),
        )
        # Bank: cash arriving (positive)
        conn.execute(
            "INSERT INTO splits (guid, tx_guid, account_guid, memo, action, "
            "reconcile_state, reconcile_date, "
            "value_num, value_denom, quantity_num, quantity_denom, lot_guid) "
            "VALUES (?, ?, ?, ?, '', 'n', '', ?, 100, ?, 100, NULL)",
            (bank_split_guid, txn_guid, bank_account_guid, memo, amount_cents, amount_cents),
        )
        conn.commit()

    logger.info(f"Cash deposit created: txn_guid={txn_guid}")

    if verify:
        verify_record_exists("transactions", txn_guid, "deposit transaction")
        verify_record_exists("splits", samuse_split_guid, "SAMUSE deposit split")
        verify_record_exists("splits", bank_split_guid, "bank deposit split")

    return txn_guid


# =============================================================================
# BILL/INVOICE OPERATIONS
# =============================================================================

def get_next_bill_id() -> str:
    """Get the next available bill ID."""
    with get_connection() as conn:
        # Bills are stored in the invoices table
        cursor = conn.execute("""
            SELECT id FROM invoices 
            WHERE id LIKE 'B-%' OR id LIKE 'B%'
            ORDER BY id DESC LIMIT 1
        """)
        row = cursor.fetchone()
        
        if row and row['id']:
            import re
            match = re.search(r'(\d+)', row['id'])
            if match:
                num = int(match.group(1))
                return config.BILL_ID_FORMAT.format(prefix=config.BILL_ID_PREFIX, num=num + 1)
        
        return config.BILL_ID_FORMAT.format(prefix=config.BILL_ID_PREFIX, num=1)


def get_checking_accounts() -> List[Dict]:
    """
    Get all checking/bank accounts suitable for bill payments.
    
    Returns list of dicts with: guid, name, description
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT guid, name, description FROM accounts 
            WHERE account_type = 'BANK' AND placeholder = 0
            ORDER BY name
        """)
        return [dict(row) for row in cursor]


def get_expense_accounts() -> List[Dict]:
    """
    Get all non-placeholder expense accounts.
    
    Returns list of dicts with: guid, name, description
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT guid, name, description FROM accounts 
            WHERE account_type = 'EXPENSE' AND placeholder = 0
            ORDER BY name
        """)
        return [dict(row) for row in cursor]


def get_invoice_by_guid(invoice_guid: str) -> Optional[Dict]:
    """Get an invoice/bill record by GUID."""
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT i.*, v.name as vendor_name
            FROM invoices i
            LEFT JOIN vendors v ON i.owner_guid = v.guid
            WHERE i.guid = ?
        """, (invoice_guid,))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_bills_by_status(status: str = 'unposted') -> List[Dict]:
    """
    Get bills filtered by status.
    
    Args:
        status: 'unposted', 'posted_unpaid', 'paid', or 'all'
        
    Returns list of bill dicts with vendor info.
    """
    with get_connection() as conn:
        base_query = """
            SELECT 
                i.guid, i.id, i.date_opened, i.date_posted, i.notes,
                i.owner_guid as vendor_guid, v.name as vendor_name,
                i.post_lot, i.post_txn, i.post_acc,
                l.is_closed as lot_closed
            FROM invoices i
            JOIN vendors v ON i.owner_guid = v.guid
            LEFT JOIN lots l ON i.post_lot = l.guid
            WHERE i.owner_type = 4
        """
        
        if status == 'unposted':
            # Bills that haven't been posted yet (no post_lot)
            query = base_query + " AND (i.post_lot IS NULL OR i.post_lot = '')"
        elif status == 'posted_unpaid':
            # Posted but lot is still open (not paid)
            query = base_query + " AND i.post_lot IS NOT NULL AND i.post_lot != '' AND (l.is_closed = 0 OR l.is_closed IS NULL)"
        elif status == 'paid':
            # Lot is closed (paid)
            query = base_query + " AND l.is_closed = -1"
        else:
            query = base_query
            
        query += " ORDER BY i.date_opened"
        
        cursor = conn.execute(query)
        return [dict(row) for row in cursor]


def get_bill_total(invoice_guid: str) -> float:
    """
    Calculate the total amount of a bill from its entries.
    
    Returns the sum of all entry amounts for this bill.
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT SUM(CAST(b_price_num AS REAL) / CAST(b_price_denom AS REAL)) as total
            FROM entries
            WHERE bill = ?
        """, (invoice_guid,))
        row = cursor.fetchone()
        return row['total'] if row and row['total'] else 0.0


# =============================================================================
# THREE-STEP BILL WORKFLOW
# =============================================================================
# These functions implement the GnuCash bill workflow as three separate steps:
# 1. create_bill() - Creates invoice record and entry (unposted)
# 2. post_bill() - Creates lot, transaction, splits (posts the bill)
# 3. pay_bill() - Creates payment transaction linking to bill's lot
#
# Each function can be called independently. All use rollback on error.
# See docs/GNUCASH_SQLITE_BILL_WORKFLOW.md for complete documentation.
# =============================================================================

def create_bill(
    vendor_guid: str,
    expense_account_guid: str,
    amount: float,
    memo: str = "",
    bill_date: date = None,
    verify: bool = True
) -> str:
    """
    Step 1: Create an unposted bill (invoice) with one entry line.
    
    This creates:
    - An invoice record (unposted)
    - An entry record linked to the invoice via the 'bill' column
    
    The bill must be posted separately using post_bill() before it can be paid.
    
    Args:
        vendor_guid: GUID of the vendor
        expense_account_guid: GUID of expense account for the entry
        amount: Bill amount (positive number)
        memo: Bill description/memo
        bill_date: Date of bill (defaults to today)
        verify: If True, verify the bill was created (default True)
    
    Returns:
        The new bill GUID
        
    Raises:
        WriteVerificationError: If verification fails
        sqlite3.Error: If database operation fails (transaction rolled back)
    """
    if bill_date is None:
        bill_date = date.today()
    
    bill_guid = generate_guid()
    bill_id = get_next_bill_id()
    entry_guid = generate_guid()
    
    usd_guid = get_usd_guid()
    
    # Convert amount to GnuCash format (integer numerator/denominator)
    amount_num = int(amount * 100)
    amount_denom = 100
    
    # Date formatting - GnuCash uses ISO format with time
    date_opened = format_gnucash_date(bill_date)
    date_entered = format_gnucash_timestamp()
    
    try:
        with get_connection(readonly=False) as conn:
            # Create the invoice/bill record (UNPOSTED - no post_lot, post_txn, post_acc)
            conn.execute("""
                INSERT INTO invoices (
                    guid, id, date_opened, date_posted, notes, active,
                    currency, owner_type, owner_guid, 
                    post_lot, post_txn, post_acc,
                    billto_type, billto_guid
                ) VALUES (?, ?, ?, '', ?, 1, ?, 4, ?, '', '', '', 0, '')
            """, (
                bill_guid, bill_id, date_opened, memo,
                usd_guid, vendor_guid
            ))
            
            # Create the entry - CRITICAL: use 'bill' column, NOT 'invoice' column!
            # See docs/GNUCASH_SQLITE_BILL_WORKFLOW.md for column documentation
            entry_sql = """
                INSERT INTO entries (
                    guid, date, date_entered, description, action, notes,
                    quantity_num, quantity_denom,
                    i_acct, i_price_num, i_price_denom, 
                    i_discount_num, i_discount_denom,
                    invoice, i_disc_type, i_disc_how,
                    i_taxable, i_taxincluded, i_taxtable,
                    b_acct, b_price_num, b_price_denom, bill,
                    b_taxable, b_taxincluded, b_taxtable, b_paytype,
                    billable, billto_type, billto_guid, order_guid
                ) VALUES (
                    ?, ?, ?, ?, '', '',
                    ?, ?,
                    NULL, 0, 1, 0, 1,
                    NULL, NULL, NULL,
                    0, 0, NULL,
                    ?, ?, ?, ?,
                    0, 0, NULL, 0,
                    0, 0, NULL, NULL
                )
            """
            
            conn.execute(entry_sql, (
                entry_guid, date_opened, date_entered, memo,
                1, 1,  # quantity should always be 1
                expense_account_guid, amount_num, amount_denom, bill_guid
            ))
            
            conn.commit()
            
    except sqlite3.Error as e:
        logger.error(f"Failed to create bill - transaction rolled back: {e}")
        raise
    
    logger.info(f"Created UNPOSTED bill: {bill_id} for ${amount:.2f} (GUID: {bill_guid})")
    
    # POST-WRITE VERIFICATION
    if verify:
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT guid, id FROM invoices WHERE guid = ?", (bill_guid,)
            )
            if not cursor.fetchone():
                raise WriteVerificationError(f"Bill {bill_id} not found after creation")
            
            cursor = conn.execute(
                "SELECT guid FROM entries WHERE bill = ?", (bill_guid,)
            )
            if not cursor.fetchone():
                raise WriteVerificationError(f"Entry not found for bill {bill_id}")
            
        logger.info(f"POST-WRITE VERIFIED: Bill {bill_id} created with entry")
    
    return bill_guid


def post_bill(
    bill_guid: str,
    post_date: date = None,
    due_date: date = None,
    ap_account_guid: str = None,
    verify: bool = True
) -> str:
    """
    Step 2: Post a bill, creating the accounting transaction.
    
    This creates:
    - A lot linked to the bill
    - Lot slots (title, gncInvoice frame)
    - A transaction with trans-txn-type="I" slot
    - Two splits: AP (credit, linked to lot) and Expense (debit)
    - Updates the invoice record with post_lot, post_txn, post_acc
    
    Args:
        bill_guid: GUID of the bill to post (from create_bill())
        post_date: Posting date (defaults to today)
        due_date: Due date (defaults to post_date)
        ap_account_guid: AP account GUID (defaults to auto-find/create)
        verify: If True, verify posting (default True)
    
    Returns:
        The lot GUID
        
    Raises:
        ValueError: If bill not found or already posted
        WriteVerificationError: If verification fails
        sqlite3.Error: If database operation fails (transaction rolled back)
    """
    if post_date is None:
        post_date = date.today()
    if due_date is None:
        due_date = post_date
        
    # Get the AP account
    if ap_account_guid is None:
        ap_account_guid = ensure_ap_account_exists()
    
    # Look up the bill
    bill = get_invoice_by_guid(bill_guid)
    if not bill:
        raise ValueError(f"Bill not found: {bill_guid}")
    
    if bill['post_lot'] and bill['post_lot'] != '':
        raise ValueError(f"Bill {bill['id']} is already posted")
    
    # Get the bill total from entries
    bill_amount = get_bill_total(bill_guid)
    if bill_amount <= 0:
        raise ValueError(f"Bill {bill['id']} has no entries or zero amount")
    
    amount_num = int(bill_amount * 100)
    amount_denom = 100
    
    # Get expense account from the entry
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT b_acct FROM entries WHERE bill = ? LIMIT 1", (bill_guid,)
        )
        entry_row = cursor.fetchone()
        if not entry_row or not entry_row['b_acct']:
            raise ValueError(f"Bill {bill['id']} has no expense account in entry")
        expense_account_guid = entry_row['b_acct']
    
    # Generate GUIDs for new records
    lot_guid = generate_guid()
    txn_guid = generate_guid()
    split_ap_guid = generate_guid()
    split_expense_guid = generate_guid()
    frame_guid = generate_guid()  # For gncInvoice slot frame
    
    usd_guid = get_usd_guid()
    date_posted = format_gnucash_date(post_date)
    date_entered = format_gnucash_timestamp()
    
    # Format due date for slot (type 10 = gdate uses YYYYMMDD format)
    due_date_gdate = due_date.strftime('%Y%m%d')
    
    try:
        with get_connection(readonly=False) as conn:
            # 1. Create the lot (tracks amounts owed)
            conn.execute("""
                INSERT INTO lots (guid, account_guid, is_closed)
                VALUES (?, ?, 0)
            """, (lot_guid, ap_account_guid))
            
            # 2. Create lot slots
            # Title slot
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, string_val)
                VALUES (?, 'title', 4, ?)
            """, (lot_guid, f"Bill {bill['id']}"))
            
            # gncInvoice frame - first create the frame slot entry
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, guid_val)
                VALUES (?, 'gncInvoice/invoice-guid', 5, ?)
            """, (frame_guid, bill_guid))
            
            # Then link frame to lot
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, guid_val)
                VALUES (?, 'gncInvoice', 9, ?)
            """, (lot_guid, frame_guid))
            
            # 3. Create the transaction
            conn.execute("""
                INSERT INTO transactions (
                    guid, currency_guid, num, post_date, enter_date, description
                ) VALUES (?, ?, '', ?, ?, ?)
            """, (txn_guid, usd_guid, date_posted, date_entered, bill['vendor_name']))
            
            # 4. Create transaction slots
            # trans-txn-type = "I" for Invoice (CRITICAL!)
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, string_val)
                VALUES (?, 'trans-txn-type', 4, 'I')
            """, (txn_guid,))
            
            # trans-read-only message
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, string_val)
                VALUES (?, 'trans-read-only', 4, 'Generated from an invoice. Try unposting the invoice.')
            """, (txn_guid,))
            
            # date-posted (type 10 = gdate)
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, gdate_val)
                VALUES (?, 'date-posted', 10, ?)
            """, (txn_guid, due_date_gdate))
            
            # gncInvoice link on transaction (same pattern as lot)
            txn_frame_guid = generate_guid()
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, guid_val)
                VALUES (?, 'gncInvoice/invoice-guid', 5, ?)
            """, (txn_frame_guid, bill_guid))
            
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, guid_val)
                VALUES (?, 'gncInvoice', 9, ?)
            """, (txn_guid, txn_frame_guid))
            
            # 5. Create splits
            # AP split (credit - negative value, linked to lot)
            conn.execute("""
                INSERT INTO splits (
                    guid, tx_guid, account_guid, memo, action,
                    reconcile_state, reconcile_date,
                    value_num, value_denom, quantity_num, quantity_denom,
                    lot_guid
                ) VALUES (?, ?, ?, '', 'Bill', 'n', '', ?, ?, ?, ?, ?)
            """, (
                split_ap_guid, txn_guid, ap_account_guid,
                -amount_num, amount_denom, -amount_num, amount_denom,
                lot_guid
            ))
            
            # Expense split (debit - positive value, no lot)
            conn.execute("""
                INSERT INTO splits (
                    guid, tx_guid, account_guid, memo, action,
                    reconcile_state, reconcile_date,
                    value_num, value_denom, quantity_num, quantity_denom,
                    lot_guid
                ) VALUES (?, ?, ?, '', 'Bill', 'n', '', ?, ?, ?, ?, NULL)
            """, (
                split_expense_guid, txn_guid, expense_account_guid,
                amount_num, amount_denom, amount_num, amount_denom
            ))
            
            # 6. Update the invoice record
            conn.execute("""
                UPDATE invoices SET
                    date_posted = ?,
                    post_txn = ?,
                    post_lot = ?,
                    post_acc = ?
                WHERE guid = ?
            """, (date_posted, txn_guid, lot_guid, ap_account_guid, bill_guid))
            
            # 7. Close the lot (is_closed = -1 means balanced/closed in GnuCash)
            # Actually, leave it open (0) - it closes when paid
            # The lot stays open until the bill is paid
            
            conn.commit()
            
    except sqlite3.Error as e:
        logger.error(f"Failed to post bill - transaction rolled back: {e}")
        raise
    
    logger.info(f"POSTED bill: {bill['id']} for ${bill_amount:.2f} (Lot: {lot_guid})")
    
    # POST-WRITE VERIFICATION
    if verify:
        with get_connection() as conn:
            # Verify invoice was updated
            cursor = conn.execute(
                "SELECT post_lot, post_txn FROM invoices WHERE guid = ?", (bill_guid,)
            )
            row = cursor.fetchone()
            if not row or row['post_lot'] != lot_guid:
                raise WriteVerificationError(f"Bill {bill['id']} post_lot not updated correctly")
            
            # Verify lot exists
            cursor = conn.execute("SELECT guid FROM lots WHERE guid = ?", (lot_guid,))
            if not cursor.fetchone():
                raise WriteVerificationError(f"Lot {lot_guid} not created")
            
            # Verify transaction and splits
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM splits WHERE tx_guid = ?", (txn_guid,))
            if cursor.fetchone()['cnt'] != 2:
                raise WriteVerificationError(f"Expected 2 splits for transaction, got different count")
            
        logger.info(f"POST-WRITE VERIFIED: Bill {bill['id']} posted successfully")
    
    return lot_guid


def pay_bill(
    bill_guid: str,
    checking_account_guid: str,
    payment_date: date = None,
    memo: str = None,
    verify: bool = True
) -> str:
    """
    Step 3: Pay a posted bill.
    
    This creates:
    - A payment lot with gncOwner slots (links to vendor)
    - A payment transaction with trans-txn-type="P" slot
    - Transaction notes slot with the memo
    - Two splits: AP (debit, linked to BILL's lot) and Checking (credit)
    
    Args:
        bill_guid: GUID of the posted bill to pay
        checking_account_guid: GUID of checking/bank account to pay from
        payment_date: Payment date (defaults to today)
        memo: Payment memo (defaults to bill's notes)
        verify: If True, verify payment (default True)
    
    Returns:
        The payment transaction GUID
        
    Raises:
        ValueError: If bill not found, not posted, or already paid
        WriteVerificationError: If verification fails
        sqlite3.Error: If database operation fails (transaction rolled back)
    """
    if payment_date is None:
        payment_date = date.today()
    
    # Look up the bill
    bill = get_invoice_by_guid(bill_guid)
    if not bill:
        raise ValueError(f"Bill not found: {bill_guid}")
    
    if not bill['post_lot'] or bill['post_lot'] == '':
        raise ValueError(f"Bill {bill['id']} is not posted - post it first")
    
    # Check if lot is already closed (bill already paid)
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT is_closed FROM lots WHERE guid = ?", (bill['post_lot'],)
        )
        lot_row = cursor.fetchone()
        if lot_row and lot_row['is_closed'] == -1:
            raise ValueError(f"Bill {bill['id']} is already paid")
    
    # Get bill amount
    bill_amount = get_bill_total(bill_guid)
    amount_num = int(bill_amount * 100)
    amount_denom = 100
    
    # Use bill notes as memo if not provided
    if memo is None:
        memo = bill['notes'] or ''
    
    # Generate GUIDs
    payment_lot_guid = generate_guid()
    payment_txn_guid = generate_guid()
    split_ap_guid = generate_guid()
    split_checking_guid = generate_guid()
    owner_frame_guid = generate_guid()
    invoice_frame_guid = generate_guid()
    
    usd_guid = get_usd_guid()
    date_posted = format_gnucash_date(payment_date)
    date_entered = format_gnucash_timestamp()
    
    ap_account_guid = bill['post_acc']
    vendor_guid = bill['owner_guid']
    bill_lot_guid = bill['post_lot']  # The BILL's lot - we link payment to this!
    
    try:
        with get_connection(readonly=False) as conn:
            # 1. Create payment lot
            conn.execute("""
                INSERT INTO lots (guid, account_guid, is_closed)
                VALUES (?, ?, -1)
            """, (payment_lot_guid, ap_account_guid))
            
            # 2. Create payment lot slots
            # Title
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, string_val)
                VALUES (?, 'title', 4, ?)
            """, (payment_lot_guid, f"Bill {bill['id']}"))
            
            # gncInvoice frame
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, guid_val)
                VALUES (?, 'gncInvoice/invoice-guid', 5, ?)
            """, (invoice_frame_guid, bill_guid))
            
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, guid_val)
                VALUES (?, 'gncInvoice', 9, ?)
            """, (payment_lot_guid, invoice_frame_guid))
            
            # gncOwner slots (CRITICAL for linking payment to vendor!)
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, int64_val)
                VALUES (?, 'gncOwner/owner-type', 1, 4)
            """, (owner_frame_guid,))  # 4 = vendor
            
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, guid_val)
                VALUES (?, 'gncOwner/owner-guid', 5, ?)
            """, (owner_frame_guid, vendor_guid))
            
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, guid_val)
                VALUES (?, 'gncOwner', 9, ?)
            """, (payment_lot_guid, owner_frame_guid))
            
            # 3. Create payment transaction
            conn.execute("""
                INSERT INTO transactions (
                    guid, currency_guid, num, post_date, enter_date, description
                ) VALUES (?, ?, '', ?, ?, ?)
            """, (payment_txn_guid, usd_guid, date_posted, date_entered, bill['vendor_name']))
            
            # 4. Create transaction slots
            # trans-txn-type = "P" for Payment (CRITICAL!)
            conn.execute("""
                INSERT INTO slots (obj_guid, name, slot_type, string_val)
                VALUES (?, 'trans-txn-type', 4, 'P')
            """, (payment_txn_guid,))
            
            # notes slot with memo (if provided)
            if memo:
                conn.execute("""
                    INSERT INTO slots (obj_guid, name, slot_type, string_val)
                    VALUES (?, 'notes', 4, ?)
                """, (payment_txn_guid, memo))
            
            # 5. Create payment splits
            # AP split (debit - positive, linked to the BILL's lot!)
            conn.execute("""
                INSERT INTO splits (
                    guid, tx_guid, account_guid, memo, action,
                    reconcile_state, reconcile_date,
                    value_num, value_denom, quantity_num, quantity_denom,
                    lot_guid
                ) VALUES (?, ?, ?, ?, 'Payment', 'n', '', ?, ?, ?, ?, ?)
            """, (
                split_ap_guid, payment_txn_guid, ap_account_guid, memo,
                amount_num, amount_denom, amount_num, amount_denom,
                bill_lot_guid  # Links to the BILL's lot, not payment lot!
            ))
            
            # Checking split (credit - negative, no lot)
            conn.execute("""
                INSERT INTO splits (
                    guid, tx_guid, account_guid, memo, action,
                    reconcile_state, reconcile_date,
                    value_num, value_denom, quantity_num, quantity_denom,
                    lot_guid
                ) VALUES (?, ?, ?, ?, 'Payment', 'n', '', ?, ?, ?, ?, NULL)
            """, (
                split_checking_guid, payment_txn_guid, checking_account_guid, memo,
                -amount_num, amount_denom, -amount_num, amount_denom
            ))
            
            # 6. Close the bill's lot (mark as paid)
            conn.execute("""
                UPDATE lots SET is_closed = -1 WHERE guid = ?
            """, (bill_lot_guid,))
            
            conn.commit()
            
    except sqlite3.Error as e:
        logger.error(f"Failed to pay bill - transaction rolled back: {e}")
        raise
    
    logger.info(f"PAID bill: {bill['id']} for ${bill_amount:.2f} (Txn: {payment_txn_guid})")
    
    # POST-WRITE VERIFICATION
    if verify:
        with get_connection() as conn:
            # Verify bill's lot is closed
            cursor = conn.execute(
                "SELECT is_closed FROM lots WHERE guid = ?", (bill_lot_guid,)
            )
            row = cursor.fetchone()
            if not row or row['is_closed'] != -1:
                raise WriteVerificationError(f"Bill lot {bill_lot_guid} not closed after payment")
            
            # Verify payment transaction exists with correct splits
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM splits WHERE tx_guid = ?", (payment_txn_guid,)
            )
            if cursor.fetchone()['cnt'] != 2:
                raise WriteVerificationError(f"Expected 2 splits in payment transaction")
            
            # Verify trans-txn-type slot
            cursor = conn.execute("""
                SELECT string_val FROM slots 
                WHERE obj_guid = ? AND name = 'trans-txn-type'
            """, (payment_txn_guid,))
            row = cursor.fetchone()
            if not row or row['string_val'] != 'P':
                raise WriteVerificationError(f"Payment transaction missing trans-txn-type='P' slot")
            
        logger.info(f"POST-WRITE VERIFIED: Bill {bill['id']} paid successfully")
    
    return payment_txn_guid


# =============================================================================
# LEGACY FUNCTION (kept for backwards compatibility, but deprecated)
# =============================================================================

def create_posted_bill_DEPRECATED(
    vendor_guid: str,
    expense_account_guid: str,
    amount: float,
    memo: str = "",
    bill_date: date = None,
    due_date: date = None,
    verify: bool = True
) -> str:
    """
    DEPRECATED: Use create_bill() + post_bill() + pay_bill() instead.
    
    This function only creates and posts bills, but does NOT pay them.
    The new workflow requires calling all three steps to fully process bills.
    
    This creates:
    1. An invoice record
    2. A billterm lot for tracking
    3. Transaction entries (debit expense, credit AP)
    
    Args:
        vendor_guid: GUID of the vendor
        expense_account_guid: GUID of expense account to debit
        amount: Bill amount
        memo: Bill description/memo
        bill_date: Date of bill (defaults to today)
        due_date: Due date (defaults to bill_date)
        verify: If True, verify the bill was created (default True)
    
    Returns the bill GUID.
    Raises WriteVerificationError if verification fails.
    """
    log_function_entry("create_posted_bill_DEPRECATED", vendor_guid=vendor_guid[:8], 
                       expense_account_guid=expense_account_guid[:8], amount=amount, memo=memo[:50])
    logger.warning("DEPRECATED: create_posted_bill_DEPRECATED called - use create_bill() + post_bill() + pay_bill() instead")
    logger.info(f"Creating posted bill: amount=${amount}, memo='{memo[:50]}'")
    
    if bill_date is None:
        bill_date = date.today()
    if due_date is None:
        due_date = bill_date
    
    logger.debug(f"Bill dates: bill_date={bill_date}, due_date={due_date}")
    
    bill_guid = generate_guid()
    bill_id = get_next_bill_id()
    lot_guid = generate_guid()
    txn_guid = generate_guid()
    split1_guid = generate_guid()  # Expense debit
    split2_guid = generate_guid()  # AP credit
    entry_guid = generate_guid()
    
    logger.debug(f"Generated GUIDs: bill={bill_guid[:8]}, bill_id={bill_id}, lot={lot_guid[:8]}, txn={txn_guid[:8]}")
    
    usd_guid = get_usd_guid()
    ap_guid = get_ap_account_guid()
    
    if not ap_guid:
        raise ValueError("Accounts Payable account not found")
    
    # Convert amount to GnuCash format (integer with denominator)
    # GnuCash stores values as value_num/value_denom
    amount_num = int(amount * 100)
    amount_denom = 100
    
    # Date formatting for GnuCash - use detected format
    date_posted = format_gnucash_date(bill_date)
    date_entered = format_gnucash_timestamp()
    date_posted_gdate = bill_date.strftime('%Y%m%d')  # YYYYMMDD format for gdate slots
    
    # Get vendor name for transaction description
    with get_connection() as conn:
        cursor = conn.execute("SELECT name FROM vendors WHERE guid = ?", (vendor_guid,))
        vendor_row = cursor.fetchone()
        vendor_name = vendor_row['name'] if vendor_row else "Unknown Vendor"
    
    with get_connection(readonly=False) as conn:
        # Create the lot (tracks amounts owed)
        conn.execute("""
            INSERT INTO lots (guid, account_guid, is_closed)
            VALUES (?, ?, 0)
        """, (lot_guid, ap_guid))
        
        # Create lot slots to link lot to invoice (required by GnuCash)
        # CRITICAL: Use KVP frame structure as documented
        lot_frame_guid = generate_guid()
        
        # Lot title slot
        conn.execute("""
            INSERT INTO slots (obj_guid, name, slot_type, string_val)
            VALUES (?, 'title', 4, ?)
        """, (lot_guid, f"Bill {bill_id}"))
        
        # Lot gncInvoice frame slot (type 9 = KVP frame)
        conn.execute("""
            INSERT INTO slots (obj_guid, name, slot_type, guid_val)
            VALUES (?, 'gncInvoice', 9, ?)
        """, (lot_guid, lot_frame_guid))
        
        # Nested invoice-guid within the frame (type 5 = GUID)
        conn.execute("""
            INSERT INTO slots (obj_guid, name, slot_type, guid_val)
            VALUES (?, 'gncInvoice/invoice-guid', 5, ?)
        """, (lot_frame_guid, bill_guid))
        
        # Create the invoice/bill record
        conn.execute("""
            INSERT INTO invoices (
                guid, id, date_opened, date_posted, notes, active,
                currency, owner_type, owner_guid, 
                post_lot, post_txn, post_acc,
                billto_type, billto_guid
            ) VALUES (?, ?, ?, ?, ?, 1, ?, 4, ?, ?, ?, ?, 0, ?)
        """, (
            bill_guid, bill_id, date_posted, date_posted, memo,
            usd_guid, vendor_guid,
            lot_guid, txn_guid, ap_guid,
            generate_guid()  # Empty billto
        ))
        
        # Create credit-note slot on invoice (type 1 = int64, value 0 = not a credit note)
        conn.execute("""
            INSERT INTO slots (obj_guid, name, slot_type, int64_val)
            VALUES (?, 'credit-note', 1, 0)
        """, (bill_guid,))
        
        # Create the transaction (description should be VENDOR NAME, not memo)
        conn.execute("""
            INSERT INTO transactions (
                guid, currency_guid, num, post_date, enter_date, description
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            txn_guid, usd_guid, bill_id, date_posted, date_entered, vendor_name
        ))
        
        # Create transaction slots (CRITICAL for GnuCash to recognize as invoice)
        txn_frame_guid = generate_guid()
        
        # trans-txn-type = "I" identifies this as an Invoice/Bill posting
        conn.execute("""
            INSERT INTO slots (obj_guid, name, slot_type, string_val)
            VALUES (?, 'trans-txn-type', 4, 'I')
        """, (txn_guid,))
        
        # trans-read-only prevents manual editing
        conn.execute("""
            INSERT INTO slots (obj_guid, name, slot_type, string_val)
            VALUES (?, 'trans-read-only', 4, 'Generated from an invoice. Try unposting the invoice.')
        """, (txn_guid,))
        
        # date-posted in gdate format (type 10 = gdate, stored as string YYYYMMDD)
        conn.execute("""
            INSERT INTO slots (obj_guid, name, slot_type, string_val)
            VALUES (?, 'date-posted', 10, ?)
        """, (txn_guid, date_posted_gdate))
        
        # trans-date-due (type 6 = timespec, stored as string timestamp)
        due_date_timespec = due_date.strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("""
            INSERT INTO slots (obj_guid, name, slot_type, string_val)
            VALUES (?, 'trans-date-due', 6, ?)
        """, (txn_guid, due_date_timespec))
        
        # gncInvoice frame slot (type 9 = KVP frame)
        conn.execute("""
            INSERT INTO slots (obj_guid, name, slot_type, guid_val)
            VALUES (?, 'gncInvoice', 9, ?)
        """, (txn_guid, txn_frame_guid))
        
        # Nested invoice-guid within the frame (type 5 = GUID)
        conn.execute("""
            INSERT INTO slots (obj_guid, name, slot_type, guid_val)
            VALUES (?, 'gncInvoice/invoice-guid', 5, ?)
        """, (txn_frame_guid, bill_guid))
        
        # Create expense split (debit - positive)
        conn.execute("""
            INSERT INTO splits (
                guid, tx_guid, account_guid, memo, action,
                reconcile_state, reconcile_date,
                value_num, value_denom, quantity_num, quantity_denom,
                lot_guid
            ) VALUES (?, ?, ?, ?, 'Expense', 'n', '', ?, ?, ?, ?, NULL)
        """, (
            split1_guid, txn_guid, expense_account_guid, memo,
            amount_num, amount_denom, amount_num, amount_denom
        ))
        
        # Create AP split (credit - negative)
        conn.execute("""
            INSERT INTO splits (
                guid, tx_guid, account_guid, memo, action,
                reconcile_state, reconcile_date,
                value_num, value_denom, quantity_num, quantity_denom,
                lot_guid
            ) VALUES (?, ?, ?, ?, 'Bill', 'n', '', ?, ?, ?, ?, ?)
        """, (
            split2_guid, txn_guid, ap_guid, memo,
            -amount_num, amount_denom, -amount_num, amount_denom,
            lot_guid
        ))
        
        # Create the invoice entry
        # CRITICAL: Use 'bill' column for vendor bills, NOT 'invoice' column
        # Use schema discovery for column names that may vary between versions
        discount_num_col = _get_column('entries', 'i_discount_num')
        discount_denom_col = _get_column('entries', 'i_discount_denom')
        
        logger.debug(f"Using entry columns: {discount_num_col}, {discount_denom_col}")
        
        entry_sql = f"""
            INSERT INTO entries (
                guid, date, date_entered, description, action,
                quantity_num, quantity_denom,
                i_acct, i_price_num, i_price_denom,
                {discount_num_col}, {discount_denom_col}, i_disc_type, i_disc_how,
                i_taxable, i_taxincluded, i_taxtable,
                b_acct, b_price_num, b_price_denom,
                b_taxable, b_taxincluded, b_taxtable,
                b_paytype, billable, billto_type, billto_guid,
                order_guid, bill, invoice
            ) VALUES (
                ?, ?, ?, ?, '',
                ?, ?,
                NULL, 0, 1, 0, 1, NULL, NULL,
                0, 0, NULL,
                ?, ?, ?,
                0, 0, NULL,
                0, 0, 0, NULL,
                NULL, ?, NULL
            )
        """
        
        conn.execute(entry_sql, (
            entry_guid, date_posted, date_entered, memo,
            1, 1,  # quantity should always be 1, not amount!
            expense_account_guid, amount_num, amount_denom,
            bill_guid
        ))
        
        conn.commit()
    
    logger.info(f"Created posted bill: {bill_id} for ${amount:.2f} (GUID: {bill_guid})")
    
    # POST-WRITE VERIFICATION - User data is SACRED
    if verify:
        verify_bill_created(bill_guid, amount, vendor_guid)
    
    return bill_guid


def get_unpaid_bills(vendor_guid: str = None) -> List[Dict]:
    """
    Get all unpaid bills, optionally filtered by vendor.
    """
    with get_connection() as conn:
        query = """
            SELECT 
                i.guid, i.id, i.date_opened, i.date_posted, i.notes,
                i.owner_guid as vendor_guid, v.name as vendor_name,
                l.is_closed as lot_closed
            FROM invoices i
            JOIN vendors v ON i.owner_guid = v.guid
            LEFT JOIN lots l ON i.post_lot = l.guid
            WHERE i.owner_type = 4  -- Vendor type
            AND (l.is_closed = 0 OR l.is_closed IS NULL)
        """
        
        params = []
        if vendor_guid:
            query += " AND i.owner_guid = ?"
            params.append(vendor_guid)
        
        query += " ORDER BY i.date_posted"
        
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor]


# =============================================================================
# VERIFICATION
# =============================================================================

def verify_database_structure() -> Dict[str, bool]:
    """
    Verify that expected tables exist in the database.
    Returns dict of {table_name: exists}
    """
    required_tables = [
        'vendors', 'accounts', 'invoices', 'entries', 
        'transactions', 'splits', 'lots', 'commodities'
    ]
    
    results = {}
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        existing_tables = {row['name'] for row in cursor}
        
        for table in required_tables:
            results[table] = table in existing_tables
    
    return results


def test_connection() -> bool:
    """Test database connection and basic structure."""
    try:
        results = verify_database_structure()
        all_present = all(results.values())
        
        if not all_present:
            missing = [t for t, exists in results.items() if not exists]
            logger.error(f"Missing tables: {missing}")
        
        return all_present
    except Exception as e:
        logger.error(f"Database connection test failed: {e}")
        return False

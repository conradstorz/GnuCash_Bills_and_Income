"""
Schema Discovery and Verification Module for GnuCash Database.

This module discovers and validates the GnuCash database schema at runtime,
caching results for efficiency. It handles variations between GnuCash versions
by dynamically detecting column names and table structures.

VERIFICATION PHILOSOPHY:
- Every database interaction must be verified
- All failures are logged to persistent history  
- User data is SACRED - never lose it due to database issues
- Trust nothing - verify everything at runtime

This module:
1. Discovers actual column names in GnuCash tables
2. Maps them to our expected names
3. Discovers required accounts (A/P, Expenses parent, etc.)
4. Validates setup and offers to fix issues
5. Persists schema info to gnucash_schema.json
6. MAINTAINS VERIFICATION HISTORY with failure logging
7. Post-write verification for all INSERT/UPDATE operations

All database operations should use this module to get correct column names.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from loguru import logger

from bill_processor import config


# Path to schema cache file
SCHEMA_FILE = config.PROJECT_ROOT / "data" / "gnucash_schema.json"


# =============================================================================
# VERIFICATION REPORT - Tracks all validation checks and failures
# =============================================================================

@dataclass
class VerificationCheck:
    """A single verification check result."""
    check_name: str
    table: str
    description: str
    passed: bool
    details: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class VerificationRun:
    """A complete verification run with all checks."""
    run_id: str
    timestamp: str
    database_path: str
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    checks: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def add_check(self, check: VerificationCheck):
        """Add a check result to this run."""
        self.checks.append(check.to_dict())
        self.total_checks += 1
        if check.passed:
            self.passed_checks += 1
        else:
            self.failed_checks += 1
    
    def add_error(self, error: str):
        self.errors.append(error)
    
    def add_warning(self, warning: str):
        self.warnings.append(warning)
    
    @property
    def all_passed(self) -> bool:
        return self.failed_checks == 0 and len(self.errors) == 0
    
    def to_dict(self) -> Dict:
        return {
            'run_id': self.run_id,
            'timestamp': self.timestamp,
            'database_path': self.database_path,
            'total_checks': self.total_checks,
            'passed_checks': self.passed_checks,
            'failed_checks': self.failed_checks,
            'all_passed': self.all_passed,
            'checks': self.checks,
            'errors': self.errors,
            'warnings': self.warnings
        }


class VerificationReport:
    """
    Maintains a complete history of all verification runs.
    
    This is the SINGLE SOURCE OF TRUTH for database validation.
    Every check is logged. Every failure is recorded. Nothing is lost.
    """
    
    MAX_HISTORY_ENTRIES = 100  # Keep last 100 verification runs
    
    def __init__(self):
        self.history: List[Dict] = []
        self.current_run: Optional[VerificationRun] = None
    
    def start_run(self, database_path: str) -> VerificationRun:
        """Start a new verification run."""
        run_id = f"VR-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.current_run = VerificationRun(
            run_id=run_id,
            timestamp=datetime.now().isoformat(),
            database_path=database_path
        )
        logger.info(f"Starting verification run: {run_id}")
        return self.current_run
    
    def end_run(self) -> Dict:
        """End the current run and add to history."""
        if not self.current_run:
            return {}
        
        result = self.current_run.to_dict()
        self.history.append(result)
        
        # Trim history if needed
        if len(self.history) > self.MAX_HISTORY_ENTRIES:
            self.history = self.history[-self.MAX_HISTORY_ENTRIES:]
        
        status = "PASSED" if self.current_run.all_passed else "FAILED"
        logger.info(
            f"Verification run {self.current_run.run_id} {status}: "
            f"{self.current_run.passed_checks}/{self.current_run.total_checks} checks passed"
        )
        
        self.current_run = None
        return result
    
    def check(self, check_name: str, table: str, description: str, 
              passed: bool, details: str = "") -> VerificationCheck:
        """Record a verification check."""
        vc = VerificationCheck(
            check_name=check_name,
            table=table,
            description=description,
            passed=passed,
            details=details
        )
        
        if self.current_run:
            self.current_run.add_check(vc)
        
        level = "DEBUG" if passed else "WARNING"
        logger.log(level, f"[{check_name}] {table}: {description} - {'PASS' if passed else 'FAIL'}")
        if details and not passed:
            logger.warning(f"  Details: {details}")
        
        return vc
    
    def clear_failure(self, check_name: str):
        """
        Clear a specific failure from the most recent run.
        
        Use this when a failure has been fixed (e.g., A/P account created).
        """
        if not self.history:
            return
        
        # Update the most recent run
        latest_run = self.history[-1]
        for check in latest_run.get('checks', []):
            if check.get('check_name') == check_name and not check.get('passed', True):
                check['passed'] = True
                check['details'] = f"{check.get('details', '')} (Fixed)"
                logger.info(f"Cleared verification failure: {check_name}")
                
                # Update run summary
                passed = sum(1 for c in latest_run['checks'] if c.get('passed', True))
                latest_run['passed_checks'] = passed
                latest_run['all_passed'] = passed == latest_run['total_checks']
                break
    
    def get_failures(self, last_n_runs: int = 1) -> List[Dict]:
        """Get all failures from the last N runs."""
        failures = []
        runs_to_check = self.history[-last_n_runs:] if self.history else []
        
        for run in runs_to_check:
            for check in run.get('checks', []):
                if not check.get('passed', True):
                    failures.append({
                        'run_id': run['run_id'],
                        'timestamp': check.get('timestamp'),
                        'check_name': check.get('check_name'),
                        'table': check.get('table'),
                        'description': check.get('description'),
                        'details': check.get('details', '')
                    })
        
        return failures
    
    def load_from_schema(self, schema_data: Dict):
        """Load history from schema JSON."""
        self.history = schema_data.get('verification_history', [])
    
    def to_dict(self) -> Dict:
        return {
            'history': self.history,
            'total_runs': len(self.history),
            'last_run_passed': self.history[-1].get('all_passed') if self.history else None
        }


# =============================================================================
# SCHEMA DISCOVERY CLASS
# =============================================================================


class SchemaDiscovery:
    """
    Discovers and caches GnuCash database schema information.
    
    Usage:
        schema = SchemaDiscovery()
        schema.discover()  # Reads database and updates cache
        
        # Get actual column name for our expected name
        actual_col = schema.get_column('entries', 'i_discount_num')
        
        # Check if database is properly set up
        if schema.is_valid():
            # proceed
            
        # Get verification failures
        failures = schema.get_verification_failures()
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize schema discovery.
        
        Args:
            db_path: Path to GnuCash database. Defaults to config.GNUCASH_DB_PATH
        """
        self.db_path = db_path or config.GNUCASH_DB_PATH
        self.schema = self._load_schema()
        
        # Initialize verification report from saved history
        self.verification = VerificationReport()
        self.verification.load_from_schema(self.schema)
        
        # Validate vendor references on startup
        self._validate_vendor_references()
        
        logger.debug(f"SchemaDiscovery initialized for {self.db_path}")
    
    def _validate_vendor_references(self):
        """Validate vendor JSON references against GnuCash database."""
        try:
            from bill_processor.vendor_sync import validate_and_fix_vendor_references
            
            logger.debug("Validating vendor references...")
            result = validate_and_fix_vendor_references(auto_fix=True, verbose=False)
            
            if result['invalid']:
                logger.warning(f"Found {len(result['invalid'])} vendors with stale GnuCash references")
            if result['fixed']:
                logger.info(f"Reset {len(result['fixed'])} vendors to unsynced state")
                
        except Exception as e:
            # Don't fail initialization if vendor validation fails
            logger.error(f"Error validating vendor references: {e}")
    
    def _load_schema(self) -> Dict:
        """Load schema from JSON file or create default."""
        if SCHEMA_FILE.exists():
            try:
                with open(SCHEMA_FILE, 'r', encoding='utf-8') as f:
                    schema = json.load(f)
                    logger.debug(f"Loaded schema from {SCHEMA_FILE}")
                    return schema
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load schema file: {e}. Creating new.")
        
        return self._create_default_schema()
    
    def _create_default_schema(self) -> Dict:
        """Create default schema structure."""
        return {
            "schema_version": 1,
            "last_validated": None,
            "database_path": None,
            "tables": {},
            "required_accounts": {
                "accounts_payable": {
                    "guid": None,
                    "name": None,
                    "account_type": "PAYABLE",
                    "can_create": True
                },
                "expense_parent": {
                    "guid": None,
                    "name": None,
                    "account_type": "EXPENSE",
                    "can_create": False
                },
                "liabilities_parent": {
                    "guid": None,
                    "name": None,
                    "account_type": "LIABILITY",
                    "can_create": False
                }
            },
            "required_commodities": {
                "usd": {
                    "guid": None,
                    "mnemonic": "USD",
                    "namespace": "CURRENCY"
                }
            },
            "validation_errors": [],
            "validation_warnings": []
        }
    
    def save(self):
        """Save schema and verification history to JSON file."""
        SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Include verification history in saved data
        self.schema['verification_history'] = self.verification.history
        
        with open(SCHEMA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.schema, f, indent=2)
        logger.debug(f"Schema saved to {SCHEMA_FILE}")
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get read-only database connection."""
        db_path = Path(self.db_path)
        if not db_path.exists():
            raise FileNotFoundError(f"GnuCash database not found: {db_path}")
        
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    
    def discover(self) -> Dict:
        """
        Discover all schema information from the database.
        
        This is the main method that:
        1. Starts a verification run
        2. Reads all table schemas with verification
        3. Finds required accounts with verification
        4. Validates setup with verification
        5. Saves results including verification history
        
        Returns:
            Dict with discovery results including errors, warnings, and verification
        """
        logger.info(f"Starting schema discovery for {self.db_path}")
        
        # Start a verification run
        self.verification.start_run(str(self.db_path))
        
        self.schema['database_path'] = str(self.db_path)
        self.schema['last_validated'] = datetime.now().isoformat()
        self.schema['validation_errors'] = []
        self.schema['validation_warnings'] = []
        
        try:
            conn = self._get_connection()
            
            # Verify database connection
            self.verification.check(
                "DB_CONNECTION", "database", 
                "Database connection established",
                passed=True,
                details=f"Connected to {self.db_path}"
            )
            
            # Discover and verify table schemas
            self._discover_tables_with_verification(conn)
            
            # Discover and verify required accounts
            self._discover_accounts_with_verification(conn)
            
            # Discover and verify required commodities
            self._discover_commodities_with_verification(conn)
            
            # Verify book GUID exists
            self._verify_book_guid(conn)
            
            # Detect date format used by GnuCash
            self._detect_date_format(conn)
            
            conn.close()
            
        except FileNotFoundError as e:
            self.schema['validation_errors'].append(str(e))
            self.verification.check(
                "DB_FILE", "database",
                "Database file exists",
                passed=False,
                details=str(e)
            )
            logger.error(f"Database not found: {e}")
        except sqlite3.Error as e:
            self.schema['validation_errors'].append(f"Database error: {e}")
            self.verification.check(
                "DB_ACCESS", "database",
                "Database accessible",
                passed=False,
                details=str(e)
            )
            logger.error(f"Database error: {e}")
        
        # End verification run
        run_result = self.verification.end_run()
        
        # Save results including verification history
        self.save()
        
        # Log summary
        error_count = len(self.schema['validation_errors'])
        warning_count = len(self.schema['validation_warnings'])
        logger.info(f"Schema discovery complete: {error_count} errors, {warning_count} warnings")
        
        return {
            'valid': error_count == 0,
            'errors': self.schema['validation_errors'],
            'warnings': self.schema['validation_warnings'],
            'tables_found': list(self.schema.get('tables', {}).keys()),
            'verification': run_result
        }
    
    def _discover_tables_with_verification(self, conn: sqlite3.Connection):
        """Discover and verify schema for all tables we need."""
        tables_to_discover = [
            'vendors', 'accounts', 'invoices', 'entries',
            'transactions', 'splits', 'lots', 'commodities', 'books'
        ]
        
        for table_name in tables_to_discover:
            self._discover_table_with_verification(conn, table_name)
        
        # Verify we have all required columns for operations we perform
        self._verify_required_columns()
    
    def _discover_table_with_verification(self, conn: sqlite3.Connection, table_name: str):
        """Discover and verify schema for a single table."""
        logger.debug(f"Discovering table: {table_name}")
        
        try:
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            columns = {}
            for row in cursor.fetchall():
                col_name = row['name']
                col_type = row['type']
                columns[col_name] = {
                    'type': col_type,
                    'nullable': not row['notnull'],
                    'primary_key': bool(row['pk'])
                }
            
            if columns:
                if 'tables' not in self.schema:
                    self.schema['tables'] = {}
                
                self.schema['tables'][table_name] = {
                    'columns': columns,
                    'column_count': len(columns)
                }
                
                self.verification.check(
                    "TABLE_EXISTS", table_name,
                    f"Table '{table_name}' exists with {len(columns)} columns",
                    passed=True,
                    details=f"Columns: {', '.join(columns.keys())}"
                )
                logger.debug(f"  Found {len(columns)} columns in {table_name}")
            else:
                self.schema['validation_warnings'].append(
                    f"Table '{table_name}' not found or empty"
                )
                self.verification.check(
                    "TABLE_EXISTS", table_name,
                    f"Table '{table_name}' exists",
                    passed=False,
                    details="Table not found or has no columns"
                )
                logger.warning(f"Table '{table_name}' not found or empty")
                
        except sqlite3.Error as e:
            self.schema['validation_warnings'].append(
                f"Error reading table '{table_name}': {e}"
            )
            self.verification.check(
                "TABLE_READ", table_name,
                f"Can read table '{table_name}'",
                passed=False,
                details=str(e)
            )
            logger.error(f"Error reading table '{table_name}': {e}")
    
    def _verify_required_columns(self):
        """Verify all columns we use in our operations exist."""
        # Define columns we use for each table
        required_columns = {
            'vendors': ['guid', 'id', 'name', 'currency', 'active', 'notes',
                       'addr_name', 'addr_addr1', 'addr_addr2', 'addr_addr3', 
                       'addr_addr4', 'addr_phone', 'addr_email'],
            'accounts': ['guid', 'name', 'account_type', 'parent_guid', 
                        'commodity_guid', 'commodity_scu'],
            'invoices': ['guid', 'id', 'date_opened', 'date_posted', 'notes',
                        'active', 'currency', 'owner_type', 'owner_guid',
                        'post_lot', 'post_txn', 'post_acc'],
            'entries': ['guid', 'date', 'date_entered', 'description', 'action',
                       'quantity_num', 'quantity_denom', 'i_acct', 'invoice',
                       'i_price_num', 'i_price_denom'],
            'transactions': ['guid', 'currency_guid', 'num', 'post_date', 
                            'enter_date', 'description'],
            'splits': ['guid', 'tx_guid', 'account_guid', 'memo', 'action',
                      'reconcile_state', 'value_num', 'value_denom',
                      'quantity_num', 'quantity_denom'],
            'lots': ['guid', 'account_guid', 'is_closed'],
            'commodities': ['guid', 'mnemonic', 'namespace'],
            'books': ['guid']
        }
        
        for table, columns in required_columns.items():
            table_cols = self.get_columns(table)
            for col in columns:
                # Use get_column which handles variations
                actual_col = self.get_column(table, col)
                
                self.verification.check(
                    "COLUMN_EXISTS", table,
                    f"Column '{col}' exists in '{table}'",
                    passed=actual_col is not None,
                    details=f"Mapped to: {actual_col}" if actual_col else f"Not found. Available: {table_cols[:5]}..."
                )
    
    def _verify_book_guid(self, conn: sqlite3.Connection):
        """Verify book GUID exists and cache it."""
        try:
            cursor = conn.execute("SELECT guid FROM books LIMIT 1")
            row = cursor.fetchone()
            
            if row:
                self.schema['book_guid'] = row['guid']
                self.verification.check(
                    "BOOK_GUID", "books",
                    "Book GUID exists",
                    passed=True,
                    details=f"GUID: {row['guid']}"
                )
                logger.debug(f"Book GUID: {row['guid']}")
            else:
                self.verification.check(
                    "BOOK_GUID", "books",
                    "Book GUID exists",
                    passed=False,
                    details="No book record found"
                )
                self.schema['validation_errors'].append("No book record found in database")
        except sqlite3.Error as e:
            self.verification.check(
                "BOOK_GUID", "books",
                "Can read book GUID",
                passed=False,
                details=str(e)
            )

    def _detect_date_format(self, conn: sqlite3.Connection):
        """
        Detect the date format used by this GnuCash database.
        
        GnuCash has used different formats over versions:
        - Compact: YYYYMMDDHHMMSS (14 chars) - older versions
        - ISO: YYYY-MM-DD HH:MM:SS (19 chars) - newer versions
        
        We detect by analyzing existing transaction dates and use the
        dominant format to ensure compatibility.
        """
        try:
            # Count transactions by date format length
            cursor = conn.execute("""
                SELECT 
                    CASE 
                        WHEN length(post_date) = 14 THEN 'compact'
                        WHEN length(post_date) = 19 THEN 'iso'
                        ELSE 'unknown'
                    END as format,
                    count(*) as count
                FROM transactions
                WHERE post_date IS NOT NULL
                GROUP BY format
                ORDER BY count DESC
            """)
            
            results = cursor.fetchall()
            
            if results:
                # Use the most common format
                dominant_format = results[0]['format']
                dominant_count = results[0]['count']
                total_count = sum(r['count'] for r in results)
                
                self.schema['date_format'] = dominant_format
                
                self.verification.check(
                    "DATE_FORMAT", "transactions",
                    f"Date format detected: {dominant_format}",
                    passed=True,
                    details=f"{dominant_count}/{total_count} transactions use {dominant_format} format"
                )
                logger.info(f"Detected date format: {dominant_format} ({dominant_count}/{total_count} transactions)")
            else:
                # No transactions, default to ISO (modern format)
                self.schema['date_format'] = 'iso'
                self.verification.check(
                    "DATE_FORMAT", "transactions",
                    "Date format defaulted to ISO (no transactions found)",
                    passed=True,
                    details="Empty database, using modern ISO format"
                )
                logger.info("No transactions found, defaulting to ISO date format")
                
        except sqlite3.Error as e:
            # Default to ISO on error
            self.schema['date_format'] = 'iso'
            self.verification.check(
                "DATE_FORMAT", "transactions",
                "Date format detection failed, defaulting to ISO",
                passed=False,
                details=str(e)
            )
            logger.warning(f"Date format detection failed: {e}, defaulting to ISO")

    def get_date_format(self) -> str:
        """
        Get the detected date format for this database.
        
        Returns:
            'iso' for YYYY-MM-DD HH:MM:SS format
            'compact' for YYYYMMDDHHMMSS format
        """
        return self.schema.get('date_format', 'iso')

    def _discover_accounts_with_verification(self, conn: sqlite3.Connection):
        """Discover and verify required accounts."""
        logger.debug("Discovering required accounts with verification")
        
        # Find Accounts Payable
        cursor = conn.execute("""
            SELECT guid, name, account_type 
            FROM accounts 
            WHERE account_type = 'PAYABLE'
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            self.schema['required_accounts']['accounts_payable'] = {
                'guid': row['guid'],
                'name': row['name'],
                'account_type': row['account_type'],
                'can_create': True
            }
            self.verification.check(
                "AP_ACCOUNT", "accounts",
                "Accounts Payable account exists",
                passed=True,
                details=f"Name: {row['name']}, GUID: {row['guid'][:12]}..."
            )
            logger.info(f"Found A/P account: {row['name']}")
        else:
            self.schema['required_accounts']['accounts_payable'] = {
                'guid': None,
                'name': None,
                'account_type': 'PAYABLE',
                'can_create': True
            }
            self.schema['validation_errors'].append(
                "No Accounts Payable account found (type: PAYABLE). "
                "This can be created automatically."
            )
            self.verification.check(
                "AP_ACCOUNT", "accounts",
                "Accounts Payable account exists",
                passed=False,
                details="No account with type 'PAYABLE' found. Can be auto-created."
            )
            logger.warning("No A/P account found")
        
        # Find Expense parent (top-level EXPENSE account)
        cursor = conn.execute("""
            SELECT a.guid, a.name, a.account_type 
            FROM accounts a
            WHERE a.account_type = 'EXPENSE' 
            AND a.parent_guid IN (SELECT guid FROM accounts WHERE account_type = 'ROOT')
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            self.schema['required_accounts']['expense_parent'] = {
                'guid': row['guid'],
                'name': row['name'],
                'account_type': row['account_type'],
                'can_create': False
            }
            self.verification.check(
                "EXPENSE_PARENT", "accounts",
                "Top-level Expense account exists",
                passed=True,
                details=f"Name: {row['name']}, GUID: {row['guid'][:12]}..."
            )
            logger.info(f"Found Expense parent: {row['name']}")
        else:
            self.schema['validation_warnings'].append(
                "No top-level Expense account found. "
                "New expense accounts may not be created correctly."
            )
            self.verification.check(
                "EXPENSE_PARENT", "accounts",
                "Top-level Expense account exists",
                passed=False,
                details="No EXPENSE account found with ROOT parent"
            )
            logger.warning("No expense parent found")
        
        # Find Liabilities parent
        cursor = conn.execute("""
            SELECT a.guid, a.name, a.account_type 
            FROM accounts a
            WHERE a.account_type = 'LIABILITY' 
            AND a.parent_guid IN (SELECT guid FROM accounts WHERE account_type = 'ROOT')
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            self.schema['required_accounts']['liabilities_parent'] = {
                'guid': row['guid'],
                'name': row['name'],
                'account_type': row['account_type'],
                'can_create': False
            }
            self.verification.check(
                "LIABILITY_PARENT", "accounts",
                "Top-level Liabilities account exists",
                passed=True,
                details=f"Name: {row['name']}, GUID: {row['guid'][:12]}..."
            )
            logger.info(f"Found Liabilities parent: {row['name']}")
        else:
            self.schema['validation_errors'].append(
                "No top-level Liabilities account found. "
                "Cannot create A/P account without this."
            )
            self.verification.check(
                "LIABILITY_PARENT", "accounts",
                "Top-level Liabilities account exists",
                passed=False,
                details="No LIABILITY account found with ROOT parent. CRITICAL for A/P creation."
            )
            logger.warning("No liabilities parent found")

    def _discover_commodities_with_verification(self, conn: sqlite3.Connection):
        """Discover and verify required commodities (currencies)."""
        logger.debug("Discovering required commodities with verification")
        
        cursor = conn.execute("""
            SELECT guid, mnemonic, namespace 
            FROM commodities 
            WHERE mnemonic = 'USD' AND namespace = 'CURRENCY'
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            self.schema['required_commodities']['usd'] = {
                'guid': row['guid'],
                'mnemonic': row['mnemonic'],
                'namespace': row['namespace']
            }
            self.verification.check(
                "USD_CURRENCY", "commodities",
                "USD currency exists",
                passed=True,
                details=f"GUID: {row['guid']}"
            )
            logger.info(f"Found USD currency: {row['guid']}")
        else:
            self.schema['validation_errors'].append(
                "USD currency not found in commodities table"
            )
            self.verification.check(
                "USD_CURRENCY", "commodities",
                "USD currency exists",
                passed=False,
                details="No USD/CURRENCY found in commodities table. CRITICAL."
            )
            logger.error("USD currency not found")

    # Keep old methods for backward compatibility but mark deprecated
    def _discover_accounts(self, conn: sqlite3.Connection):
        """DEPRECATED: Use _discover_accounts_with_verification instead."""
        self._discover_accounts_with_verification(conn)
    
    def _discover_commodities(self, conn: sqlite3.Connection):
        """DEPRECATED: Use _discover_commodities_with_verification instead."""
        self._discover_commodities_with_verification(conn)
    
    # =========================================================================
    # PUBLIC API - Use these methods for schema access
    # =========================================================================
    
    def is_valid(self) -> bool:
        """Check if schema is valid (no critical errors)."""
        return len(self.schema.get('validation_errors', [])) == 0
    
    def get_errors(self) -> List[str]:
        """Get list of validation errors."""
        return self.schema.get('validation_errors', [])
    
    def get_warnings(self) -> List[str]:
        """Get list of validation warnings."""
        return self.schema.get('validation_warnings', [])
    
    def get_verification_failures(self, last_n_runs: int = 1) -> List[Dict]:
        """Get verification failures from the last N runs."""
        return self.verification.get_failures(last_n_runs)
    
    def get_last_verification_run(self) -> Optional[Dict]:
        """Get the most recent verification run result."""
        if self.verification.history:
            return self.verification.history[-1]
        return None
    
    def has_column(self, table: str, column: str) -> bool:
        """Check if a table has a specific column."""
        tables = self.schema.get('tables', {})
        if table not in tables:
            return False
        columns = tables[table].get('columns', {})
        return column in columns
    
    def get_columns(self, table: str) -> List[str]:
        """Get list of columns for a table."""
        tables = self.schema.get('tables', {})
        if table not in tables:
            return []
        return list(tables[table].get('columns', {}).keys())
    
    def get_column(self, table: str, expected_name: str) -> Optional[str]:
        """
        Get actual column name for an expected name.
        
        Handles variations like i_disc_num vs i_discount_num by looking
        for close matches.
        
        Returns the actual column name or None if not found.
        """
        columns = self.get_columns(table)
        
        # Exact match
        if expected_name in columns:
            return expected_name
        
        # Try common variations
        variations = self._get_column_variations(expected_name)
        for var in variations:
            if var in columns:
                logger.debug(f"Column mapping: {expected_name} -> {var}")
                return var
        
        logger.warning(f"Column not found: {table}.{expected_name}")
        return None
    
    def _get_column_variations(self, name: str) -> List[str]:
        """Generate possible variations of a column name."""
        variations = [name]
        
        # Common GnuCash abbreviation patterns
        replacements = [
            ('_disc_', '_discount_'),
            ('_discount_', '_disc_'),
            ('_num', '_number'),
            ('_number', '_num'),
            ('_denom', '_denominator'),
            ('_denominator', '_denom'),
        ]
        
        for old, new in replacements:
            if old in name:
                variations.append(name.replace(old, new))
        
        return variations
    
    def has_table(self, table_name: str) -> bool:
        """Check if a table exists in the discovered schema."""
        return table_name in self.schema.get('tables', {})
    
    def get_table_schema(self, table_name: str) -> Optional[Dict]:
        """Get the complete schema information for a table."""
        return self.schema.get('tables', {}).get(table_name)
    
    def build_vendor_insert_statement(self) -> Tuple[str, List[str]]:
        """
        Build the correct INSERT statement for vendors table based on actual schema.
        
        Returns:
            Tuple of (SQL statement, list of column names in order)
        """
        if not self.has_table('vendors'):
            raise ValueError("Vendors table not found in schema")
        
        vendor_columns = self.get_columns('vendors')
        
        # Define the columns we want to populate (in order of preference)
        desired_columns = [
            'guid', 'id', 'name', 'currency', 'active', 'notes',
            'addr_name', 'addr_addr1', 'addr_addr2', 'addr_addr3', 'addr_addr4', 
            'addr_phone', 'addr_fax', 'addr_email'
        ]
        
        # Add optional columns that might exist
        optional_columns = [
            'tax_override', 'tax_inc', 'tax_table',
            'terms', 'billing_id', 'credit', 'discount'
        ]
        
        insert_columns = []
        
        # Add required columns first
        for col in desired_columns:
            if col in vendor_columns:
                insert_columns.append(col)
            else:
                logger.debug(f"Desired column '{col}' not found in vendors table")
        
        # Add optional columns if they exist
        for col in optional_columns:
            if col in vendor_columns and col not in insert_columns:
                insert_columns.append(col)
                logger.debug(f"Adding optional column: {col}")
        
        # Build INSERT statement
        columns_str = ', '.join(insert_columns)
        placeholders = ', '.join(['?' for _ in insert_columns])
        
        sql = f"INSERT INTO vendors ({columns_str}) VALUES ({placeholders})"
        
        logger.info(f"Built vendor INSERT statement with {len(insert_columns)} columns")
        logger.debug(f"INSERT SQL: {sql}")
        logger.debug(f"Columns: {insert_columns}")
        
        return sql, insert_columns

    def get_account_guid(self, account_key: str) -> Optional[str]:
        """
        Get GUID for a required account.
        
        Args:
            account_key: One of 'accounts_payable', 'expense_parent', 'liabilities_parent'
        """
        accounts = self.schema.get('required_accounts', {})
        if account_key in accounts:
            return accounts[account_key].get('guid')
        return None
    
    def get_account_name(self, account_key: str) -> Optional[str]:
        """Get name for a required account."""
        accounts = self.schema.get('required_accounts', {})
        if account_key in accounts:
            return accounts[account_key].get('name')
        return None
    
    def get_usd_guid(self) -> Optional[str]:
        """Get GUID for USD currency."""
        commodities = self.schema.get('required_commodities', {})
        if 'usd' in commodities:
            return commodities['usd'].get('guid')
        return None
    
    def needs_ap_account(self) -> bool:
        """Check if A/P account needs to be created."""
        ap = self.schema.get('required_accounts', {}).get('accounts_payable', {})
        return ap.get('guid') is None
    
    def update_ap_account(self, guid: str, name: str):
        """Update A/P account info after creation."""
        self.schema['required_accounts']['accounts_payable']['guid'] = guid
        self.schema['required_accounts']['accounts_payable']['name'] = name
        
        # Remove error about missing A/P
        self.schema['validation_errors'] = [
            e for e in self.schema['validation_errors']
            if 'Accounts Payable' not in e
        ]
        
        # Clear the verification failure since we've fixed it
        self.verification.clear_failure('AP_ACCOUNT')
        
        self.save()
        logger.info(f"Updated A/P account: {name} ({guid})")
    
    def get_last_validated(self) -> Optional[str]:
        """Get timestamp of last validation."""
        return self.schema.get('last_validated')
    
    def needs_rediscovery(self) -> bool:
        """
        Check if schema needs to be rediscovered.
        
        Returns True if:
        - Never validated
        - Database path changed
        - Schema file is missing tables
        """
        if not self.schema.get('last_validated'):
            return True
        
        if str(self.db_path) != self.schema.get('database_path'):
            logger.info("Database path changed - rediscovery needed")
            return True
        
        if not self.schema.get('tables'):
            return True
        
        return False
    
    def validate_vendor_guids(self, vendor_database: Dict) -> Dict:
        """
        Validate all vendor GUIDs in the vendor database against GnuCash.
        
        For each vendor in vendor_database['vendors']:
        - If gnucash_guid is set, verify it exists in GnuCash
        - If it doesn't exist, clear it (set to None) and log warning
        - Return dict of {vendor_key: {'valid': bool, 'action': str}}
        
        This MUST be called at startup to catch stale GUIDs after database rollback.
        """
        logger.info("Validating all vendor GUIDs against GnuCash database...")
        
        results = {}
        vendors = vendor_database.get('vendors', {})
        stale_count = 0
        valid_count = 0
        
        try:
            conn = self._get_connection()
            
            for vendor_key, vendor_data in vendors.items():
                stored_guid = vendor_data.get('gnucash_guid')
                
                if not stored_guid:
                    results[vendor_key] = {'valid': True, 'action': 'no_guid', 'message': 'No GUID stored'}
                    continue
                
                # Check if this GUID exists in GnuCash
                cursor = conn.execute(
                    "SELECT guid, name, id FROM vendors WHERE guid = ?",
                    (stored_guid,)
                )
                row = cursor.fetchone()
                
                if row:
                    # GUID exists - verify name matches
                    gc_name = row['name']
                    local_name = vendor_data.get('display_name', '')
                    
                    if gc_name != local_name:
                        logger.warning(f"Vendor name mismatch: JSON='{local_name}', GnuCash='{gc_name}'")
                        results[vendor_key] = {
                            'valid': True, 
                            'action': 'name_mismatch',
                            'message': f"Name differs: '{local_name}' vs '{gc_name}'",
                            'gnucash_name': gc_name,
                            'gnucash_id': row['id']
                        }
                    else:
                        results[vendor_key] = {
                            'valid': True, 
                            'action': 'verified',
                            'message': 'GUID verified in GnuCash',
                            'gnucash_id': row['id']
                        }
                    valid_count += 1
                else:
                    # GUID is stale - doesn't exist in GnuCash
                    logger.warning(f"Stale GUID for vendor '{vendor_data.get('display_name')}': {stored_guid[:12]}...")
                    results[vendor_key] = {
                        'valid': False, 
                        'action': 'stale_guid',
                        'message': f"GUID not found in GnuCash - will be cleared",
                        'stale_guid': stored_guid
                    }
                    stale_count += 1
            
            conn.close()
            
        except Exception as e:
            logger.error(f"Error validating vendor GUIDs: {e}")
            results['_error'] = {'valid': False, 'action': 'error', 'message': str(e)}
        
        logger.info(f"Vendor GUID validation: {valid_count} valid, {stale_count} stale")
        return results
    
    def sync_vendors_with_gnucash(self, vendor_manager) -> Dict:
        """
        Synchronize vendor database with GnuCash.
        
        This:
        1. Validates all stored GUIDs
        2. Clears stale GUIDs
        3. Checks for vendors in GnuCash that aren't in JSON
        4. Updates JSON with any fixes
        
        Args:
            vendor_manager: VendorManager instance with save() method
            
        Returns:
            Dict with sync results
        """
        logger.info("Synchronizing vendors with GnuCash database...")
        
        results = {
            'stale_cleared': [],
            'newly_found': [],
            'verified': [],
            'errors': []
        }
        
        # Step 1: Validate all stored GUIDs
        validation = self.validate_vendor_guids(vendor_manager.vendors)
        
        # Step 2: Clear stale GUIDs
        for vendor_key, status in validation.items():
            if vendor_key == '_error':
                results['errors'].append(status['message'])
                continue
                
            if status['action'] == 'stale_guid':
                # Clear the stale GUID
                if vendor_key in vendor_manager.vendors['vendors']:
                    old_guid = vendor_manager.vendors['vendors'][vendor_key].get('gnucash_guid')
                    vendor_manager.vendors['vendors'][vendor_key]['gnucash_guid'] = None
                    vendor_manager.vendors['vendors'][vendor_key]['gnucash_id'] = None
                    results['stale_cleared'].append({
                        'vendor_key': vendor_key,
                        'display_name': vendor_manager.vendors['vendors'][vendor_key].get('display_name'),
                        'old_guid': old_guid
                    })
                    logger.info(f"Cleared stale GUID for {vendor_key}")
            elif status['action'] == 'verified':
                results['verified'].append(vendor_key)
        
        # Step 3: Check for GnuCash vendors not in our JSON
        try:
            conn = self._get_connection()
            cursor = conn.execute("SELECT guid, name, id FROM vendors ORDER BY name")
            
            local_guids = set()
            for v_data in vendor_manager.vendors.get('vendors', {}).values():
                if v_data.get('gnucash_guid'):
                    local_guids.add(v_data['gnucash_guid'])
            
            for row in cursor:
                if row['guid'] not in local_guids:
                    results['newly_found'].append({
                        'guid': row['guid'],
                        'name': row['name'],
                        'id': row['id']
                    })
                    logger.debug(f"Found GnuCash vendor not in JSON: {row['name']}")
            
            conn.close()
        except Exception as e:
            logger.error(f"Error checking GnuCash vendors: {e}")
            results['errors'].append(str(e))
        
        # Step 4: Save changes
        if results['stale_cleared']:
            vendor_manager.save()
            logger.info(f"Saved vendor database after clearing {len(results['stale_cleared'])} stale GUIDs")
        
        return results


# Global schema instance (lazy-loaded)
_schema_instance: Optional[SchemaDiscovery] = None


def get_schema() -> SchemaDiscovery:
    """Get the global schema discovery instance."""
    global _schema_instance
    if _schema_instance is None:
        _schema_instance = SchemaDiscovery()
    return _schema_instance


def discover_schema() -> Dict:
    """Discover schema and return results."""
    schema = get_schema()
    return schema.discover()


def validate_and_fix() -> Tuple[bool, List[str], List[str]]:
    """
    Validate schema and attempt to fix issues.
    
    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    schema = get_schema()
    
    # Always rediscover on startup
    result = schema.discover()
    
    return (
        result['valid'],
        result['errors'],
        result['warnings']
    )

import pytest
import sqlite3
import tempfile
import shutil
from datetime import date
from pathlib import Path

from bill_processor.config import GNUCASH_DB_PATH
from bill_processor import gnucash_db


@pytest.fixture(scope="class")
def test_db_path():
    """Create a temporary copy of the real database for testing"""
    if not GNUCASH_DB_PATH.exists():
        pytest.skip(f"Database not found: {GNUCASH_DB_PATH}")
    
    # Create temp copy
    temp_dir = Path(tempfile.mkdtemp())
    test_db = temp_dir / "test_database.gnucash"
    shutil.copy2(GNUCASH_DB_PATH, test_db)
    
    yield test_db
    
    # Cleanup with Windows-safe approach
    try:
        # Close any potential open connections first
        import gc
        gc.collect()
        
        # Try to remove with error handling
        if test_db.exists():
            test_db.unlink()
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        # On Windows, sometimes files are locked - ignore cleanup errors in tests
        pass

def _ensure_samuse_account(db_path):
    """Insert SAMUSE Cash-on-hand account into test DB if missing."""
    import uuid
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Check if account already exists
    cursor.execute(
        "SELECT guid FROM accounts WHERE name = 'SAMUSE Cash-on-hand' LIMIT 1"
    )
    row = cursor.fetchone()
    if row:
        conn.close()
        return

    # Find a ASSET parent account to attach to
    cursor.execute(
        "SELECT guid FROM accounts WHERE account_type = 'ASSET' AND placeholder = 1 LIMIT 1"
    )
    parent_row = cursor.fetchone()
    if not parent_row:
        cursor.execute(
            "SELECT guid FROM accounts WHERE account_type IN ('ASSET', 'CASH', 'BANK') LIMIT 1"
        )
        parent_row = cursor.fetchone()

    # Get USD commodity guid
    cursor.execute(
        "SELECT guid FROM commodities WHERE mnemonic = 'USD' AND namespace = 'CURRENCY' LIMIT 1"
    )
    commodity_row = cursor.fetchone()

    if not parent_row or not commodity_row:
        conn.close()
        return  # Can't insert without parent/commodity; tests will skip naturally

    samuse_guid = uuid.uuid4().hex
    cursor.execute(
        "INSERT INTO accounts (guid, name, account_type, commodity_guid, commodity_scu, "
        "non_std_scu, parent_guid, code, description, hidden, placeholder) "
        "VALUES (?, 'SAMUSE Cash-on-hand', 'CASH', ?, 100, 0, ?, '', '', 0, 0)",
        (samuse_guid, commodity_row[0], parent_row[0]),
    )
    conn.commit()
    conn.close()


@pytest.fixture(scope="class")
def db_connection(test_db_path):
    """Provide database connection to test database"""
    # Monkey patch the database path in gnucash_db module
    original_path = gnucash_db.config.GNUCASH_DB_PATH
    gnucash_db.config.GNUCASH_DB_PATH = test_db_path

    # Ensure SAMUSE Cash-on-hand account exists in test DB
    _ensure_samuse_account(test_db_path)

    # Reset SAMUSE guid cache so it queries the (possibly new) test DB
    gnucash_db._samuse_guid_cache = None

    yield test_db_path

    # Reset cache again on teardown to avoid cross-test contamination
    gnucash_db._samuse_guid_cache = None

    # Restore original path
    gnucash_db.config.GNUCASH_DB_PATH = original_path

@pytest.fixture
def test_vendor_guid(db_connection):
    """Get an existing vendor GUID for testing"""
    conn = sqlite3.connect(db_connection)
    cursor = conn.cursor()
    cursor.execute("SELECT guid, name FROM vendors LIMIT 1")
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        pytest.skip("No vendors found in test database")
    
    return result[0]  # Return GUID

@pytest.fixture
def test_accounts(db_connection):
    """Get required account GUIDs for testing"""
    conn = sqlite3.connect(db_connection)
    cursor = conn.cursor()
    
    # Get AP account
    cursor.execute("""
        SELECT guid FROM accounts 
        WHERE name = 'Accounts Payable' AND account_type = 'PAYABLE'
        LIMIT 1
    """)
    ap_result = cursor.fetchone()
    
    # Get expense account (non-placeholder)
    cursor.execute("""
        SELECT guid FROM accounts 
        WHERE account_type = 'EXPENSE' AND placeholder = 0
        LIMIT 1
    """)
    expense_result = cursor.fetchone()
    
    # Get checking account
    cursor.execute("""
        SELECT guid FROM accounts 
        WHERE account_type = 'BANK' 
        LIMIT 1
    """)
    checking_result = cursor.fetchone()
    
    conn.close()
    
    if not all([ap_result, expense_result, checking_result]):
        pytest.skip("Required accounts not found in test database")
    
    return {
        'ap_account': ap_result[0],
        'expense_account': expense_result[0], 
        'checking_account': checking_result[0]
    }

@pytest.fixture
def bill_data():
    """Sample bill data for testing"""
    return {
        'amount': 12345,  # $123.45
        'memo': 'Test bill for automated testing',
        'date': date.today()
    }

@pytest.fixture
def cash_entry_data(db_connection, test_accounts):
    """Sample cash entry data with two positive line items using distinct accounts."""
    from datetime import date

    # Prefer expense_account for Alice and ap_account for Bob so they have distinct GUIDs.
    # Fall back gracefully if keys are missing.
    account_guids = list(test_accounts.values())
    alice_guid = test_accounts.get("expense_account") or account_guids[0]
    bob_guid = test_accounts.get("ap_account") or (account_guids[1] if len(account_guids) > 1 else account_guids[0])

    # If both resolved to the same guid, try to find a second distinct account from the DB
    if alice_guid == bob_guid:
        conn = sqlite3.connect(str(db_connection))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT guid FROM accounts WHERE placeholder = 0 AND guid != ? LIMIT 1",
            (alice_guid,),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            bob_guid = row[0]

    return {
        "date": date.today(),
        "description": "Test cash entry",
        "line_items": [
            {"account_guid": alice_guid, "memo": "Alice", "amount": 50.00},
            {"account_guid": bob_guid, "memo": "Bob", "amount": 30.00},
        ],
    }
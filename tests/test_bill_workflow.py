import pytest
import sqlite3
from loguru import logger
from bill_processor import gnucash_db


class TestBillWorkflow:
    """Test the three-step bill workflow: create_bill -> post_bill -> pay_bill"""

    def test_create_bill_success(self, db_connection, test_vendor_guid, test_accounts, bill_data):
        """Test create_bill() creates unposted bill and entry"""
        
        # Call the function
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date']
        )
        
        # Verify bill was created
        conn = sqlite3.connect(db_connection)
        cursor = conn.cursor()
        
        # Check invoice table
        cursor.execute("""
            SELECT id, date_opened, date_posted, notes, active, owner_guid, 
                   post_txn, post_lot, post_acc
            FROM invoices WHERE guid = ?
        """, (bill_guid,))
        
        invoice = cursor.fetchone()
        assert invoice is not None, "Invoice not created"
        assert invoice[1] == bill_data['date'].strftime('%Y-%m-%d %H:%M:%S'), "Wrong date_opened"
        assert invoice[2] == '' or invoice[2] is None, "date_posted should be empty/NULL (unposted)"
        assert invoice[3] == bill_data['memo'], "Wrong notes/memo"
        assert invoice[4] == 1, "Invoice should be active"
        assert invoice[5] == test_vendor_guid, "Wrong vendor GUID"
        assert invoice[6] == '' or invoice[6] is None, "post_txn should be empty/NULL (unposted)"
        assert invoice[7] == '' or invoice[7] is None, "post_lot should be empty/NULL (unposted)" 
        assert invoice[8] == '' or invoice[8] is None, "post_acc should be empty/NULL (unposted)"
        
        # Check entry table
        cursor.execute("""
            SELECT description, quantity_num, quantity_denom, 
                   b_acct, b_price_num, b_price_denom, bill, invoice
            FROM entries WHERE bill = ?
        """, (bill_guid,))
        
        entry = cursor.fetchone()
        assert entry is not None, "Entry not created"
        assert entry[0] == bill_data['memo'], "Wrong entry description"
        # GnuCash stores entries as: quantity=1 (1 unit) × b_price (dollar amount)
        # See research/snapshots/diff_bill_created_empty_to_bill_with_entry.json
        assert entry[1] == 1, "quantity_num should be 1 (one unit)"
        assert entry[2] == 1, "quantity_denom should be 1"
        assert entry[3] == test_accounts['expense_account'], "Wrong bill expense account (b_acct)"
        assert entry[4] == bill_data['amount'] * 100, "b_price_num should be amount in cents"
        assert entry[5] == 100, "Wrong b_price_denom"
        assert entry[6] == bill_guid, "Entry should use 'bill' column"
        assert entry[7] is None, "Entry should NOT use 'invoice' column"
        
        conn.close()

    def test_post_bill_success(self, db_connection, test_vendor_guid, test_accounts, bill_data):
        """Test post_bill() creates transaction, lot, and splits"""
        
        # First create an unposted bill
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date']
        )
        
        # Now post it
        lot_guid = gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account']
        )
        
        conn = sqlite3.connect(db_connection)
        cursor = conn.cursor()
        
        # Verify invoice was updated with posting info
        cursor.execute("""
            SELECT date_posted, post_txn, post_lot, post_acc
            FROM invoices WHERE guid = ?
        """, (bill_guid,))
        
        invoice = cursor.fetchone()
        assert invoice[0] == bill_data['date'].strftime('%Y-%m-%d %H:%M:%S'), "date_posted not set"
        assert invoice[1] is not None, "post_txn should be set"
        assert invoice[2] == lot_guid, "post_lot should match returned lot_guid"
        assert invoice[3] == test_accounts['ap_account'], "post_acc should be AP account"
        
        post_txn_guid = invoice[1]
        
        # Verify lot was created
        cursor.execute("""
            SELECT account_guid, is_closed FROM lots WHERE guid = ?
        """, (lot_guid,))
        
        lot = cursor.fetchone()
        assert lot is not None, "Lot not created"
        assert lot[0] == test_accounts['ap_account'], "Lot should be linked to AP account"
        assert lot[1] == 0, "Lot should not be closed yet (unpaid)"
        
        # Verify transaction was created
        cursor.execute("""
            SELECT currency_guid, post_date, description
            FROM transactions WHERE guid = ?
        """, (post_txn_guid,))
        
        txn = cursor.fetchone()
        assert txn is not None, "Transaction not created"
        assert txn[1] == bill_data['date'].strftime('%Y-%m-%d %H:%M:%S'), "Wrong transaction date"
        
        # Verify splits were created
        cursor.execute("""
            SELECT account_guid, value_num, value_denom, lot_guid, memo, action
            FROM splits WHERE tx_guid = ?
            ORDER BY value_num DESC
        """, (post_txn_guid,))
        
        splits = cursor.fetchall()
        assert len(splits) == 2, "Should have exactly 2 splits"
        
        # Expense split (debit, positive)
        expense_split = splits[0]
        assert expense_split[0] == test_accounts['expense_account'], "First split should be expense"
        assert expense_split[1] == bill_data['amount'] * 100, "Wrong expense amount (should be in cents)"
        assert expense_split[2] == 100, "Wrong denominator"
        assert expense_split[3] == '' or expense_split[3] is None, "Expense split should not have lot_guid"
        assert expense_split[4] == '' or expense_split[4] == bill_data['memo'], "Memo should be empty or match bill memo"
        assert expense_split[5] == 'Bill', "Wrong action"
        
        # AP split (credit, negative)  
        ap_split = splits[1]
        assert ap_split[0] == test_accounts['ap_account'], "Second split should be AP"
        assert ap_split[1] == -bill_data['amount'] * 100, "AP split should be negative (in cents)"
        assert ap_split[2] == 100, "Wrong denominator"
        assert ap_split[3] == lot_guid, "AP split should have lot_guid"
        assert ap_split[4] == '' or ap_split[4] == bill_data['memo'], "Memo should be empty or match bill memo"
        assert ap_split[5] == 'Bill', "Wrong action"
        
        conn.close()

    def test_pay_bill_success(self, db_connection, test_vendor_guid, test_accounts, bill_data):
        """Test pay_bill() creates payment transaction and closes lot"""
        
        # Create and post a bill first
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date']
        )
        
        lot_guid = gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account']  
        )
        
        # Now pay it
        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            payment_date=bill_data['date'],
            checking_account_guid=test_accounts['checking_account'],
            memo=bill_data['memo']
        )
        
        conn = sqlite3.connect(db_connection)
        cursor = conn.cursor()
        
        # Verify original lot is now closed
        cursor.execute("""
            SELECT is_closed FROM lots WHERE guid = ?
        """, (lot_guid,))
        
        lot = cursor.fetchone()
        assert lot[0] == -1, "Original lot should be closed (-1)"
        
        # Verify payment transaction was created
        cursor.execute("""
            SELECT currency_guid, post_date, description  
            FROM transactions WHERE guid = ?
        """, (payment_txn_guid,))
        
        payment_txn = cursor.fetchone()
        assert payment_txn is not None, "Payment transaction not created"
        assert payment_txn[1] == bill_data['date'].strftime('%Y-%m-%d %H:%M:%S'), "Wrong payment date"
        
        # Verify payment splits
        cursor.execute("""
            SELECT account_guid, value_num, value_denom, lot_guid, memo
            FROM splits WHERE tx_guid = ?
            ORDER BY value_num DESC  
        """, (payment_txn_guid,))
        
        payment_splits = cursor.fetchall()
        assert len(payment_splits) == 2, "Payment should have exactly 2 splits"
        
        # AP split (debit, positive - reduces AP balance)
        ap_payment_split = payment_splits[0] 
        assert ap_payment_split[0] == test_accounts['ap_account'], "First split should be AP"
        assert ap_payment_split[1] == bill_data['amount'] * 100, "Wrong AP payment amount (should be in cents)"
        assert ap_payment_split[2] == 100, "Wrong denominator"
        assert ap_payment_split[3] == lot_guid, "AP split should link to original lot"
        assert ap_payment_split[4] == '' or ap_payment_split[4] == bill_data['memo'], "Memo should be empty or match bill memo"
        
        # Checking split (credit, negative - reduces checking balance)
        checking_split = payment_splits[1]
        assert checking_split[0] == test_accounts['checking_account'], "Second split should be checking"
        assert checking_split[1] == -bill_data['amount'] * 100, "Checking split should be negative (in cents)"
        assert checking_split[2] == 100, "Wrong denominator" 
        assert checking_split[3] == '' or checking_split[3] is None, "Checking split should not have lot_guid"
        assert checking_split[4] == '' or checking_split[4] == bill_data['memo'], "Memo should be empty or match bill memo"
        
        # Verify payment transaction has notes slot with memo
        cursor.execute("""
            SELECT string_val FROM slots 
            WHERE obj_guid = ? AND name = 'notes'
        """, (payment_txn_guid,))
        
        notes_slot = cursor.fetchone()
        assert notes_slot is not None, "Missing notes slot on payment transaction"
        assert notes_slot[0] == bill_data['memo'], "Notes should contain original memo"
        
        # Verify payment transaction type
        cursor.execute("""
            SELECT string_val FROM slots 
            WHERE obj_guid = ? AND name = 'trans-txn-type'
        """, (payment_txn_guid,))
        
        txn_type_slot = cursor.fetchone()
        assert txn_type_slot is not None, "Missing trans-txn-type slot"
        # Verify payment transaction type (optional check)
        cursor.execute("""
            SELECT string_val FROM slots 
            WHERE obj_guid = ? AND name = 'trans-txn-type'
        """, (payment_txn_guid,))
        
        txn_type_slot = cursor.fetchone()
        if txn_type_slot:
            assert txn_type_slot[0] == 'P', "Payment transaction type should be 'P'"

        # Verify gncOwner slot added to bill lot (required for check printing address lookup)
        cursor.execute("""
            SELECT s2.guid_val FROM slots s1
            JOIN slots s2 ON s2.obj_guid = s1.guid_val AND s2.name = 'gncOwner/owner-guid'
            WHERE s1.obj_guid = ? AND s1.name = 'gncOwner'
        """, (lot_guid,))
        owner_row = cursor.fetchone()
        assert owner_row is not None, "Bill lot missing gncOwner slot after payment"
        assert owner_row[0] == test_vendor_guid, "Bill lot gncOwner/owner-guid should match vendor"

        # Verify gncOwner slot added to payment transaction (required for check printing)
        # GnuCash check dialog resolves vendor address via gncOwner on the transaction itself
        cursor.execute("""
            SELECT s2.guid_val FROM slots s1
            JOIN slots s2 ON s2.obj_guid = s1.guid_val AND s2.name = 'gncOwner/owner-guid'
            WHERE s1.obj_guid = ? AND s1.name = 'gncOwner'
        """, (payment_txn_guid,))
        txn_owner_row = cursor.fetchone()
        assert txn_owner_row is not None, "Payment transaction missing gncOwner slot (needed for check printing)"
        assert txn_owner_row[0] == test_vendor_guid, "Payment transaction gncOwner/owner-guid should match vendor"

        conn.close()

    def test_full_workflow_integration(self, db_connection, test_vendor_guid, test_accounts, bill_data):
        """Test complete workflow: create -> post -> pay"""
        
        # Step 1: Create bill
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date']
        )
        
        assert bill_guid is not None, "create_bill should return bill GUID"
        
        # Step 2: Post bill  
        lot_guid = gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account']
        )
        
        assert lot_guid is not None, "post_bill should return lot GUID"
        
        # Step 3: Pay bill
        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            payment_date=bill_data['date'],
            checking_account_guid=test_accounts['checking_account'],
            memo=bill_data['memo']
        )
        
        assert payment_txn_guid is not None, "pay_bill should return payment transaction GUID"
        
        # Verify complete workflow in database
        conn = sqlite3.connect(db_connection)
        cursor = conn.cursor()
        
        # Check that bill is fully processed
        cursor.execute("""
            SELECT date_posted, post_txn, post_lot, post_acc 
            FROM invoices WHERE guid = ?
        """, (bill_guid,))
        
        invoice = cursor.fetchone()
        assert invoice[0] != '', "Bill should be posted"
        assert invoice[1] is not None, "Bill should have post_txn"
        assert invoice[2] == lot_guid, "Bill should have correct lot"
        assert invoice[3] == test_accounts['ap_account'], "Bill should have correct AP account"
        
        # Check that lot is closed
        cursor.execute("""
            SELECT is_closed FROM lots WHERE guid = ?
        """, (lot_guid,))
        
        lot = cursor.fetchone()
        assert lot[0] == -1, "Lot should be closed after payment"
        
        conn.close()

    def test_create_bill_edge_cases(self, db_connection, test_vendor_guid, test_accounts, bill_data):
        """Test create_bill() edge cases and boundary conditions"""
        
        # Test with zero amount
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=0,
            memo="Zero amount test",
            bill_date=bill_data['date']
        )
        assert bill_guid is not None, "Should allow zero amount bills"
        
        # Test with very large amount
        bill_guid2 = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=999999.99,
            memo="Large amount test",
            bill_date=bill_data['date']
        )
        assert bill_guid2 is not None, "Should allow large amount bills"
        
        # Test with empty memo
        bill_guid3 = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=100,
            memo="",
            bill_date=bill_data['date']
        )
        assert bill_guid3 is not None, "Should allow empty memo"

    def test_post_bill_error_cases(self, db_connection, test_accounts, bill_data):
        """Test post_bill() error handling"""
        
        # Test with invalid bill GUID
        with pytest.raises(Exception):
            gnucash_db.post_bill(
                bill_guid="invalid-bill-guid",
                post_date=bill_data['date'],
                ap_account_guid=test_accounts['ap_account']
            )

    def test_pay_bill_error_cases(self, db_connection, test_accounts, bill_data):
        """Test pay_bill() error handling"""
        
        # Test with invalid bill GUID  
        with pytest.raises(Exception):
            gnucash_db.pay_bill(
                bill_guid="invalid-bill-guid",
                payment_date=bill_data['date'],
                checking_account_guid=test_accounts['checking_account'],
                memo=bill_data['memo']
            )

    def test_pay_bill_unposted_bill_raises_value_error(self, test_vendor_guid, test_accounts, bill_data):
        """pay_bill() should reject bills that have not been posted."""
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date'],
        )

        with pytest.raises(ValueError, match="not posted"):
            gnucash_db.pay_bill(
                bill_guid=bill_guid,
                payment_date=bill_data['date'],
                checking_account_guid=test_accounts['checking_account'],
            )

    def test_pay_bill_already_paid_raises_value_error(self, test_vendor_guid, test_accounts, bill_data):
        """pay_bill() should reject paying the same bill twice."""
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date'],
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account'],
        )
        gnucash_db.pay_bill(
            bill_guid=bill_guid,
            payment_date=bill_data['date'],
            checking_account_guid=test_accounts['checking_account'],
            memo=bill_data['memo'],
        )

        with pytest.raises(ValueError, match="already paid"):
            gnucash_db.pay_bill(
                bill_guid=bill_guid,
                payment_date=bill_data['date'],
                checking_account_guid=test_accounts['checking_account'],
                memo=bill_data['memo'],
            )

    def test_pay_bill_uses_invoice_notes_when_memo_missing(self, db_connection, test_vendor_guid, test_accounts, bill_data):
        """If no memo is passed, pay_bill() should store invoice notes in transaction notes."""
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date'],
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account'],
        )

        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            payment_date=bill_data['date'],
            checking_account_guid=test_accounts['checking_account'],
            memo=None,
        )

        conn = sqlite3.connect(db_connection)
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT string_val FROM slots WHERE obj_guid = ? AND name = 'notes'",
            (payment_txn_guid,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == bill_data['memo']

    def test_pay_bill_splits_balance_to_zero(self, db_connection, test_vendor_guid, test_accounts, bill_data):
        """Payment transaction should always be balanced (sum of split values equals zero)."""
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date'],
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account'],
        )
        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            payment_date=bill_data['date'],
            checking_account_guid=test_accounts['checking_account'],
            memo=bill_data['memo'],
        )

        conn = sqlite3.connect(db_connection)
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT SUM(value_num) FROM splits WHERE tx_guid = ?",
            (payment_txn_guid,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 0

    def test_fractional_amount_truncation_is_consistent_across_workflow(self, db_connection, test_vendor_guid, test_accounts, bill_data):
        """Amounts with 3+ decimal places should use the same integer-cent value in all workflow steps."""
        fractional_amount = 123.456
        expected_amount_num = int(fractional_amount * 100)

        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=fractional_amount,
            memo="Fractional precision test",
            bill_date=bill_data['date'],
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account'],
        )
        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            payment_date=bill_data['date'],
            checking_account_guid=test_accounts['checking_account'],
            memo="Fractional precision test",
        )

        conn = sqlite3.connect(db_connection)
        cursor = conn.cursor()
        entry_row = cursor.execute(
            "SELECT b_price_num, b_price_denom FROM entries WHERE bill = ?",
            (bill_guid,),
        ).fetchone()
        split_values = cursor.execute(
            "SELECT value_num FROM splits WHERE tx_guid = ? ORDER BY value_num DESC",
            (payment_txn_guid,),
        ).fetchall()
        conn.close()

        assert entry_row is not None
        assert entry_row[0] == expected_amount_num
        assert entry_row[1] == 100
        assert len(split_values) == 2
        assert split_values[0][0] == expected_amount_num
        assert split_values[1][0] == -expected_amount_num

    @pytest.mark.manual
    def test_gnucash_ui_verification(self, db_connection, test_vendor_guid, test_accounts, bill_data):
        """Manual test: Create a bill and verify it appears correctly in GnuCash UI"""
        
        # Create, post, and pay a bill
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo="MANUAL_TEST_BILL - Please verify in GnuCash",
            bill_date=bill_data['date']
        )
        
        lot_guid = gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account']
        )
        
        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            payment_date=bill_data['date'], 
            checking_account_guid=test_accounts['checking_account'],
            memo="MANUAL_TEST_BILL - Please verify in GnuCash"
        )
        
        # Get vendor name for instructions
        conn = sqlite3.connect(db_connection)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM vendors WHERE guid = ?", (test_vendor_guid,))
        vendor_name = cursor.fetchone()[0]
        
        cursor.execute("SELECT id FROM invoices WHERE guid = ?", (bill_guid,))
        bill_id = cursor.fetchone()[0]
        
        conn.close()
        
        logger.info(f"\n{'='*60}")
        logger.info("MANUAL VERIFICATION REQUIRED")
        logger.info(f"{'='*60}")
        logger.info(f"A test bill has been created in the database copy at:")
        logger.info(f"  {db_connection}")
        logger.info("")
        logger.info("Bill details:")
        logger.info(f"  Vendor: {vendor_name}")
        logger.info(f"  Bill ID: {bill_id}")
        logger.info(f"  Amount: ${bill_data['amount']/100:.2f}")
        logger.info("  Memo: MANUAL_TEST_BILL - Please verify in GnuCash")
        logger.info("")
        logger.info("To verify:")
        logger.info("1. Copy this test database over your real database (BACKUP FIRST!)")
        logger.info("2. Open GnuCash")
        logger.info("3. Check Business → Vendor → Process Payment")
        logger.info("4. Verify the bill appears as PAID")
        logger.info("5. Check that vendor address shows on payment")
        logger.info("6. Verify memo appears in check register")
        logger.info(f"{'='*60}")
        
        # This test always "passes" - it's just for manual verification
        assert True


    def test_pay_bill_stores_check_number(self, db_connection, test_vendor_guid, test_accounts, bill_data):
        """check_number is written to transactions.num on the payment transaction."""
        import sqlite3
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date'],
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account'],
        )
        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            checking_account_guid=test_accounts['checking_account'],
            payment_date=bill_data['date'],
            check_number="1042",
        )
        conn = sqlite3.connect(str(db_connection))
        row = conn.execute(
            "SELECT num FROM transactions WHERE guid = ?", (payment_txn_guid,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "1042"


class TestWorkflowAccountTypeIntegrity:
    """
    Verify that every account used in the 3-step workflow has the correct
    GnuCash account_type in the database.

    These tests catch the class of misconfiguration where an INCOME or EXPENSE
    account GUID is stored as the AP account.  Such a misconfiguration produces
    no runtime errors but silently breaks GnuCash check-printing because GnuCash
    only resolves the vendor address via a PAYABLE-type account.
    """

    def _run_full_workflow(self, test_vendor_guid, test_accounts, bill_data):
        """Run create -> post -> pay and return (bill_guid, lot_guid, payment_txn_guid)."""
        bill_guid = gnucash_db.create_bill(
            vendor_guid=test_vendor_guid,
            expense_account_guid=test_accounts['expense_account'],
            amount=bill_data['amount'],
            memo=bill_data['memo'],
            bill_date=bill_data['date'],
        )
        lot_guid = gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_data['date'],
            ap_account_guid=test_accounts['ap_account'],
        )
        payment_txn_guid = gnucash_db.pay_bill(
            bill_guid=bill_guid,
            payment_date=bill_data['date'],
            checking_account_guid=test_accounts['checking_account'],
            memo=bill_data['memo'],
        )
        return bill_guid, lot_guid, payment_txn_guid

    def test_lot_is_linked_to_payable_account(
        self, db_connection, test_vendor_guid, test_accounts, bill_data
    ):
        """post_bill() must create the lot under a PAYABLE account, not INCOME/EXPENSE."""
        _, lot_guid, _ = self._run_full_workflow(test_vendor_guid, test_accounts, bill_data)

        conn = sqlite3.connect(str(db_connection))
        row = conn.execute(
            "SELECT a.account_type FROM lots l "
            "JOIN accounts a ON a.guid = l.account_guid WHERE l.guid = ?",
            (lot_guid,),
        ).fetchone()
        conn.close()

        assert row is not None, "Lot not found in database"
        assert row[0] == 'PAYABLE', (
            f"Lot account_type is '{row[0]}' — should be 'PAYABLE'. "
            "ap_account_guid in settings is pointing to the wrong account."
        )

    def test_posting_transaction_ap_split_uses_payable_account(
        self, db_connection, test_vendor_guid, test_accounts, bill_data
    ):
        """Step 2 (post_bill): the AP (credit) split must be in a PAYABLE account."""
        bill_guid, _, _ = self._run_full_workflow(test_vendor_guid, test_accounts, bill_data)

        conn = sqlite3.connect(str(db_connection))
        post_txn_guid = conn.execute(
            "SELECT post_txn FROM invoices WHERE guid = ?", (bill_guid,)
        ).fetchone()[0]
        row = conn.execute(
            "SELECT a.account_type FROM splits sp "
            "JOIN accounts a ON a.guid = sp.account_guid "
            "WHERE sp.tx_guid = ? AND sp.value_num < 0",
            (post_txn_guid,),
        ).fetchone()
        conn.close()

        assert row is not None, "AP (credit) split not found in posting transaction"
        assert row[0] == 'PAYABLE', (
            f"Posting transaction AP split account_type is '{row[0]}' — should be 'PAYABLE'. "
            "The ap_account_guid setting is pointing to the wrong account."
        )

    def test_posting_transaction_expense_split_uses_expense_account(
        self, db_connection, test_vendor_guid, test_accounts, bill_data
    ):
        """Step 2 (post_bill): the expense (debit) split must be in an EXPENSE account.

        The expense account is e.g. 'Commissions Paid'.  It must be type EXPENSE.
        """
        bill_guid, _, _ = self._run_full_workflow(test_vendor_guid, test_accounts, bill_data)

        conn = sqlite3.connect(str(db_connection))
        post_txn_guid = conn.execute(
            "SELECT post_txn FROM invoices WHERE guid = ?", (bill_guid,)
        ).fetchone()[0]
        row = conn.execute(
            "SELECT a.account_type, a.name FROM splits sp "
            "JOIN accounts a ON a.guid = sp.account_guid "
            "WHERE sp.tx_guid = ? AND sp.value_num > 0",
            (post_txn_guid,),
        ).fetchone()
        conn.close()

        assert row is not None, "Expense (debit) split not found in posting transaction"
        assert row[0] == 'EXPENSE', (
            f"Posting transaction expense split uses account '{row[1]}' (type='{row[0]}') "
            "— should be 'EXPENSE'. "
            "The expense_account_guid (e.g. Commissions Paid) setting is pointing to the wrong account."
        )

    def test_payment_transaction_ap_split_uses_payable_account(
        self, db_connection, test_vendor_guid, test_accounts, bill_data
    ):
        """Step 3 (pay_bill): the AP (debit) split must be in a PAYABLE account.

        This is the most critical check for check printing.  GnuCash resolves
        the vendor address by walking the AP split to its PAYABLE account.
        If the account type is INCOME or EXPENSE, the vendor address is blank.
        pay_bill() derives this account from invoice.post_acc, so a wrong
        ap_account_guid in post_bill() cascades here automatically.
        """
        _, _, payment_txn_guid = self._run_full_workflow(test_vendor_guid, test_accounts, bill_data)

        conn = sqlite3.connect(str(db_connection))
        row = conn.execute(
            "SELECT a.account_type, a.name FROM splits sp "
            "JOIN accounts a ON a.guid = sp.account_guid "
            "WHERE sp.tx_guid = ? AND sp.value_num > 0",
            (payment_txn_guid,),
        ).fetchone()
        conn.close()

        assert row is not None, "AP (debit) split not found in payment transaction"
        assert row[0] == 'PAYABLE', (
            f"Payment transaction AP split uses account '{row[1]}' (type='{row[0]}') "
            "— should be 'PAYABLE'. "
            "GnuCash check printing will show a blank vendor address if this is not PAYABLE."
        )

    def test_payment_transaction_checking_split_uses_bank_account(
        self, db_connection, test_vendor_guid, test_accounts, bill_data
    ):
        """Step 3 (pay_bill): the checking (credit) split must be in a BANK account."""
        _, _, payment_txn_guid = self._run_full_workflow(test_vendor_guid, test_accounts, bill_data)

        conn = sqlite3.connect(str(db_connection))
        row = conn.execute(
            "SELECT a.account_type, a.name FROM splits sp "
            "JOIN accounts a ON a.guid = sp.account_guid "
            "WHERE sp.tx_guid = ? AND sp.value_num < 0",
            (payment_txn_guid,),
        ).fetchone()
        conn.close()

        assert row is not None, "Checking (credit) split not found in payment transaction"
        assert row[0] == 'BANK', (
            f"Payment checking split uses account '{row[1]}' (type='{row[0]}') — should be 'BANK'."
        )

    def test_invoice_post_acc_is_payable_account(
        self, db_connection, test_vendor_guid, test_accounts, bill_data
    ):
        """invoices.post_acc must reference a PAYABLE account.

        pay_bill() reads the AP account from invoice.post_acc — if that field
        was written with an INCOME account GUID, the payment will be
        miscategorised and check printing will not find the vendor address.
        """
        bill_guid, _, _ = self._run_full_workflow(test_vendor_guid, test_accounts, bill_data)

        conn = sqlite3.connect(str(db_connection))
        row = conn.execute(
            "SELECT a.account_type, a.name FROM invoices i "
            "JOIN accounts a ON a.guid = i.post_acc WHERE i.guid = ?",
            (bill_guid,),
        ).fetchone()
        conn.close()

        assert row is not None, "Invoice post_acc account not found"
        assert row[0] == 'PAYABLE', (
            f"Invoice post_acc references account '{row[1]}' (type='{row[0]}') "
            "— should be 'PAYABLE'."
        )


class TestEffectivePayee:
    """Unit tests for the check-payee fallback rule (gnucash_db._effective_payee)."""

    def test_addr_name_used_when_present(self):
        assert gnucash_db._effective_payee("Bullet County Sheriff", "Bullet County Taxes KY") \
            == "Bullet County Sheriff"

    def test_falls_back_to_name_when_addr_name_empty(self):
        assert gnucash_db._effective_payee("", "Acme Co") == "Acme Co"

    def test_falls_back_to_name_when_addr_name_none(self):
        assert gnucash_db._effective_payee(None, "Acme Co") == "Acme Co"

    def test_falls_back_to_name_when_addr_name_whitespace(self):
        assert gnucash_db._effective_payee("   ", "Acme Co") == "Acme Co"

    def test_addr_name_is_trimmed(self):
        assert gnucash_db._effective_payee("  Real Payee LLC  ", "Acme Co") == "Real Payee LLC"

    def test_name_none_yields_empty_string(self):
        assert gnucash_db._effective_payee(None, None) == ""


if __name__ == "__main__":
    # Run with: python -m pytest tests/test_bill_workflow.py -v
    # Run manual tests: python -m pytest tests/test_bill_workflow.py -v -m manual
    pytest.main([__file__, "-v"])
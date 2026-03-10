import pytest
import sqlite3
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
        
        print(f"\n{'='*60}")
        print("MANUAL VERIFICATION REQUIRED")
        print(f"{'='*60}")
        print(f"A test bill has been created in the database copy at:")
        print(f"  {db_connection}")
        print(f"")
        print(f"Bill details:")
        print(f"  Vendor: {vendor_name}")
        print(f"  Bill ID: {bill_id}")
        print(f"  Amount: ${bill_data['amount']/100:.2f}")
        print(f"  Memo: MANUAL_TEST_BILL - Please verify in GnuCash")
        print(f"")
        print(f"To verify:")
        print(f"1. Copy this test database over your real database (BACKUP FIRST!)")
        print(f"2. Open GnuCash")
        print(f"3. Check Business → Vendor → Process Payment")
        print(f"4. Verify the bill appears as PAID")
        print(f"5. Check that vendor address shows on payment")
        print(f"6. Verify memo appears in check register")
        print(f"{'='*60}")
        
        # This test always "passes" - it's just for manual verification
        assert True


if __name__ == "__main__":
    # Run with: python -m pytest tests/test_bill_workflow.py -v
    # Run manual tests: python -m pytest tests/test_bill_workflow.py -v -m manual
    pytest.main([__file__, "-v"])
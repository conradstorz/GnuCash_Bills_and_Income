# Columbo - The GnuCash Database Detective 🕵️

<img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python 3.10+"/> <img src="https://img.shields.io/badge/dependencies-piecash-green.svg" alt="Dependencies: piecash"/>

> *"Just one more thing... let me show you what changed in your database."*

A **self-contained**, portable Python script for debugging GnuCash database changes. Drop it into any project and instantly track what your utilities are doing to your GnuCash database.

## 🎯 What It Does

Columbo captures **before** and **after** snapshots of your GnuCash database and tells you **exactly** what changed:

- ✅ **Transactions fixed** (had errors → now valid)
- 🚨 **Transactions broken** (were valid → now have errors)  
- ➕ **Transactions added**
- ➖ **Transactions deleted**
- 📝 **Transactions modified**
- 📊 **Account changes**

Perfect for debugging bill creation utilities, payment processors, or any external tool that modifies GnuCash.

## 🚀 Quick Start

### Installation

1. **Copy `columbo.py` to your project** (it's completely self-contained!)
2. **Install the only dependency:**
   ```bash
   pip install piecash
   ```

### Usage

#### First Run - Capture "Before" State
```bash
python columbo.py path/to/your/book.gnucash
```

Output:
```
📸 No existing snapshot found. Creating BEFORE snapshot...

================================================================================
BEFORE SNAPSHOT CAPTURED
================================================================================
Timestamp:    2026-02-11T15:20:55.252186
Accounts:     171
Transactions: 3208
Errors:       10

✓ Saved to: snapshot_before.json

Next steps:
  1. Make your changes (fix transactions, run utilities, etc.)
  2. Run this script again to see what changed
```

#### Second Run - See What Changed
```bash
# After making changes to the database
python columbo.py path/to/your/book.gnucash
```

Output:
```
================================================================================
COLUMBO'S INVESTIGATION REPORT
Just one more thing... here's what changed in your database
================================================================================

SUMMARY
--------------------------------------------------------------------------------
Accounts:     +0 / -0 / ~0
Transactions: +1 / -1 / ~0
Fixed:        1 transaction(s) 🎉
Broken:       0 transaction(s) 🚨

================================================================================
TRANSACTIONS FIXED (1)
================================================================================

1. Mercurio's Music and Restobar
   RECREATED (old GUID deleted, new GUID created)
   Old GUID: ac743e128eb342909114083ffecd46e6
   New GUID: a6dde67c2f0b414fbf3445ca8399995e

   BEFORE (broken):
     Post Date:  2026-01-27 00:00:00
     Enter Date: 2026-01-28 17:11:32
     Splits:     0
     Error:      splits: Couldn't parse datetime string: ''

   AFTER (fixed):
     Post Date:  2026-01-27 00:00:00
     Enter Date: 2026-02-11 15:27:23
     Splits:     2
     Error:      None
     Split details:
       - SCS Sales Commission: $554.0
       - Accounts Payable: $-554.0
```

## 🔍 Use Cases

### 1. Debug Transaction Fixes
Find out what "unpost and repost" actually does:

```bash
python columbo.py book.gnucash          # Before fix
# (Fix transaction in GnuCash)
python columbo.py book.gnucash          # After fix - see the changes!
```

### 2. Debug External Utilities
Catch bugs in bill creation, payment processing, or import scripts:

```bash
python columbo.py book.gnucash          # Before running utility
python your_bill_creator.py             # Run your utility
python columbo.py book.gnucash          # See what it broke!
```

If you see transactions in the "BROKEN" section, you've found the bug! 🐛

### 3. Track Data Corruption
See exactly which fields are corrupt:

```
BEFORE (broken):
  Post Date:  None
  Splits:     0
  Error:      splits: Couldn't parse datetime string: ''
```

This tells you the utility is creating transactions with missing dates and empty splits.

## 📁 Files Created

- `snapshot_before.json` - Initial state capture
- `snapshot_after.json` - State after changes
- `columbo_report.txt` - Full detailed report

## 🔄 Resetting

To start a new investigation:
```bash
rm snapshot_before.json
python columbo.py book.gnucash
```

## 🎓 Example Workflow

```bash
# Debugging a bill creation utility
cd my_billing_project
cp /path/to/columbo.py .
pip install piecash

# Baseline
python columbo.py ~/gnucash/business.gnucash

# Run your utility
python create_invoices.py

# See what happened
python columbo.py ~/gnucash/business.gnucash
```

Columbo shows:
```
TRANSACTIONS BROKEN (3) 🚨
========================

1. Invoice #1234 (GUID: abc123...)
   WAS WORKING, NOW HAS ERROR: post_date: Couldn't parse datetime string: ''
```

**Aha!** Your `create_invoices.py` is creating transactions with invalid dates. Time to fix that bug!

## 🛠️ What Columbo Captures

For each transaction:
- GUID (unique identifier)
- Description
- Post date
- Enter date  
- Number of splits
- Split details (account, amount, memo)
- Any errors (datetime parsing, missing data, etc.)

For each account:
- GUID
- Full path name
- Type (ASSET, LIABILITY, etc.)
- Currency/commodity
- Parent account

## 💡 Tips

1. **Keep old snapshots** for tracking patterns over time
2. **Run before AND after** every external utility execution
3. **Check the "BROKEN" section** - that's where your bugs are!
4. **Use version control** - commit snapshots to track when issues were introduced
5. **Portable** - Copy columbo.py to any project that touches GnuCash

## 🐛 Common Patterns Columbo Finds

### Empty Dates
```
Error: "post_date: Couldn't parse datetime string: ''"
```
Your utility isn't setting transaction dates properly.

### Zero Splits
```
Splits: 0
Error: "splits: Couldn't parse datetime string: ''"
```
Your utility created a transaction shell but no actual accounting entries.

### Transaction Recreation
```
RECREATED (old GUID deleted, new GUID created)
```
The fix completely deleted and recreated the transaction (like "unpost/repost").

## 📋 Requirements

- Python 3.10+
- piecash (`pip install piecash`)
- Read access to GnuCash SQLite database

## 🚀 Portability

**Columbo is completely self-contained!** 

- ✅ Single file
- ✅ No imports from other project modules
- ✅ Copy to any project directory
- ✅ Works standalone

Perfect for:
- Bill creation utilities
- Payment processors
- Import/export tools
- Database migration scripts
- Any tool that modifies GnuCash

## 📜 License

Same as parent project (see LICENSE file)

## 🙏 Credits

Named after Lieutenant Columbo - the detective who always had "just one more thing" to investigate.

---

**Question**: Why is my utility creating broken transactions?

**Columbo**: *"Just one more thing... let me show you exactly what changed."*

# GnuCash Bill Processor

A tool that automates the bill-to-check workflow in GnuCash.

## The Problem

GnuCash can print checks with the vendor's mailing address positioned for
windowed envelopes, but the only way to trigger that feature is to walk through
the full vendor invoice lifecycle: create a bill, post it, then pay it. There
is no shortcut. For a small business writing dozens of checks a month, this
means repeating the same multi-step process in the GnuCash GUI over and over.

## The Solution

This tool reduces that entire workflow to: type a vendor name and amount, click
**Process**, then print the check in GnuCash. It talks directly to the GnuCash
SQLite database, executing the same three accounting steps (create bill, post
bill, pay bill) in a fraction of a second.

It also handles vendor management, address lookup, cash-on-hand bookkeeping,
and keeps a local vendor database in sync with GnuCash so you only enter
details once.

## Features

- **Bill queue** -- type vendor, amount, memo, and date; queue multiple bills
  and process them all at once or one at a time.
- **Vendor search** -- fuzzy name matching finds the right vendor even with
  typos or abbreviations. If the vendor is new, a creation dialog looks up
  the address automatically.
- **Cash-on-hand entry** -- record cash receipts and bank deposits in the
  same session, on the right-hand panel of the dashboard.
- **Vendor sync** -- keeps a local JSON vendor database in sync with GnuCash.
  At startup the tool pulls current vendor data from the database so edits
  made directly in GnuCash (name corrections, address changes) are picked up
  automatically.
- **Settings page** -- configure processing accounts (A/P, checking, expense),
  cash entry accounts, locality for address lookups, and fuzzy matching
  sensitivity, all from the browser.
- **Address lookup** -- when creating a new vendor, searches Google Places or
  OpenStreetMap for the business address so you don't have to type it.
- **Check number tracking** -- optionally record the check number on each
  payment for reconciliation.

## Requirements

- **Python 3.11 or later**
- **GnuCash** with a SQLite-format database (File > Save As > sqlite3)
- **Windows 10/11** (the desktop launcher and file picker use Windows-specific
  features; the core tool runs on any OS with minor adjustments)
- **uv** package manager (install from https://docs.astral.sh/uv/)

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url>
cd GnuCash_bills_and_collections

# 2. Install dependencies
uv sync

# 3. Run the installer (finds your GnuCash database, generates a launcher)
uv run python install.py

# 4. Start the web dashboard
uv run uvicorn bill_processor.web.app:app --port 7432
# Or double-click the generated "GnuCash Bills" shortcut on your desktop
```

Open your browser to **http://localhost:7432** and you are ready to go. See
[GETTING_STARTED.md](GETTING_STARTED.md) for a detailed walkthrough of your
first session, and [USER_GUIDE.md](USER_GUIDE.md) for the full feature
reference.

## Project Layout

```
GnuCash_bills_and_collections/
  config.py              # System constants (account types, formats)
  settings_manager.py    # User-configurable settings (persisted to JSON)
  gnucash_db.py          # Direct SQLite access to GnuCash database
  vendor_manager.py      # Vendor lookup and JSON database
  vendor_sync.py         # Bidirectional sync between JSON and GnuCash
  address_lookup.py      # Google Places / OpenStreetMap address search
  utils.py               # Name normalization, fuzzy matching, date parsing
  main.py                # CLI entry point
  install.py             # First-time setup script
  columbo.py             # Database snapshot/diff debugging tool (standalone)
  web/
    app.py               # FastAPI web application
    queue_io.py           # Bill queue file I/O
    cash_io.py            # Memo history for cash entry autocomplete
    static/               # CSS, JavaScript, HTMX
    templates/            # Jinja2 HTML templates
  data/
    vendor_database.json  # Local vendor cache (gitignored)
    user_settings.json    # User preferences (gitignored)
    bills_to_process.txt  # Current bill queue (gitignored)
  tests/                  # pytest test suite
  docs/                   # Design specs and implementation plans
```

## How It Works

The GnuCash database is a standard SQLite file. This tool opens it, reads the
chart of accounts and vendor list, and writes the same rows that GnuCash
itself would create when you use the invoice workflow in the GUI. The
three-step process:

1. **Create bill** -- inserts an invoice record and an entry line with the
   vendor, amount, expense account, and memo.
2. **Post bill** -- creates a lot and a transaction, moving the amount into
   Accounts Payable. This is what makes the bill appear as "posted" in
   GnuCash.
3. **Pay bill** -- creates a payment transaction from the checking account,
   clears the A/P balance, and records the check number if provided.

After processing, open GnuCash and the bill is already posted and paid. Use
GnuCash's **File > Print Check** to print the check with the vendor address
in place.

## Testing

```bash
# Run the full test suite
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_bill_workflow.py -v

# With coverage
uv run pytest --cov=bill_processor tests/
```

## Further Reading

- [GETTING_STARTED.md](GETTING_STARTED.md) -- first-time setup walkthrough
- [USER_GUIDE.md](USER_GUIDE.md) -- complete feature reference
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) -- common problems and solutions
- [COLUMBO_README.md](COLUMBO_README.md) -- the database debugging tool

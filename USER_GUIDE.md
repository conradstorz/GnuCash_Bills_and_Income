# User Guide

Complete reference for the GnuCash Bill Processor web dashboard.

## Dashboard Overview

The dashboard is a split-screen layout:

- **Left panel** -- bill queue, bill entry form, and recent bills table.
- **Right panel** -- cash-on-hand entry and bank deposit form.

A sync status bar at the top shows the last vendor sync time and a button
to trigger a manual sync.

## Bill Workflow

### Entering a Bill

The bill entry form has five fields:

| Field | Required | Description |
|-------|----------|-------------|
| Vendor | Yes | Start typing to search. Fuzzy matching finds vendors even with typos or abbreviations. |
| Amount | Yes | Dollar amount of the check (minimum $0.01). |
| Memo | No | Free-text note stored on the bill in GnuCash. |
| Date | Yes | Defaults to today. Any past or future date is accepted. |
| Check # | No | Check number for reconciliation in GnuCash. |

Click **Add to Queue** to add the bill. It appears in the queue section
above the form. You can queue as many bills as you like before processing.

### Vendor Search

As you type in the Vendor field, the tool searches your vendor database
using fuzzy matching. Results appear in a dropdown ranked by match quality.

- **Exact and close matches** appear immediately.
- **Partial matches** (abbreviations, typos) appear with lower confidence.
- If no match is found, a **"Create new vendor"** option appears.

### Creating a New Vendor

When you select "Create new vendor" from the dropdown (or when no matches
are found), a dialog opens with:

- **Display Name** -- pre-filled with what you typed. Edit if needed.
- **Address fields** -- street address, city, state, ZIP, phone.
- **Address candidates** -- the tool automatically searches Google Places
  (if configured) or OpenStreetMap for the business address. Click a
  candidate to fill in the address fields.

Click **Create Vendor** to save. The vendor is added to both the local
JSON database and the GnuCash database immediately.

The address is important -- GnuCash uses it to position the mailing
address on printed checks for windowed envelopes.

### Editing a Queued Bill

Click a queued bill to edit its fields inline. Changes are saved when you
click away or press Enter.

### Deleting a Queued Bill

Each queued bill has a delete button (X) to remove it from the queue.

### Processing Bills

Two processing options:

- **Process** (per-bill button) -- processes a single bill.
- **Process All** -- processes every bill in the queue.

Each bill goes through three steps in GnuCash:

1. **Create bill** -- inserts an invoice record and entry line.
2. **Post bill** -- creates the accounting transaction in Accounts Payable.
3. **Pay bill** -- creates the payment from the checking account.

After processing, the bill disappears from the queue and the success
message shows the GnuCash bill ID. Open GnuCash to print the check.

### Recent Bills

Below the entry form, a table shows the most recent bills from GnuCash
with their date, vendor name, and status (open or posted).

## Cash-on-Hand Entry

The right panel handles cash receipts -- money received in cash that needs
to be recorded in your books.

### Adding Cash Entries

1. Set the **Date** at the top of the form.
2. Click **+ Add Row** to add entry lines.
3. Each row has:
   - **Account** -- select from enabled income/asset accounts (configured
     in Settings). A memo field with autocomplete learns from your past
     entries.
   - **Amount** -- dollar amount. Positive = cash in, negative = cash out.

The **SAMUSE Total** at the bottom shows the running total that will be
posted to your cash-on-hand account.

### Bank Deposits

Check the **Bank Deposit** box to record a deposit at the same time:

- **Bank Account** -- select the bank account from the dropdown.
- **Amount** -- the deposit amount (independent of the cash entry total).
- **Date** -- defaults to tomorrow (deposits typically clear the next day).

### Submitting

Click **Submit All** to post the cash entries and deposit to GnuCash.
The memo for each entry is saved to the autocomplete history so it
appears in suggestions next time.

## Settings

Access settings from the **Settings** link at the top of the dashboard.

### Processing Accounts

Click **Processing Accounts** to configure the three GnuCash accounts
used when processing bills:

- **Accounts Payable** -- the liability account for vendor bills.
- **Checking Account** -- the bank account checks are drawn on.
- **Expense Account** -- the default expense account charged.

All three must be selected before bills can be processed. Each section
shows your chart of accounts as radio buttons. Your selection is saved
immediately when you click.

### Cash Entry Accounts

A checkbox grid of income and asset accounts from GnuCash. Check the
accounts you want to appear in the cash entry dropdown. Uncheck accounts
you never use in cash entry to keep the dropdown clean.

### Cash-on-Hand Account

The GnuCash account where cash receipts are recorded. Type to search
with autocomplete from your chart of accounts. The field validates that
the account exists in GnuCash as you type.

### Locality Settings

Your geographic location, used when searching for vendor addresses:

- **City and State** -- your city and two-letter state code.
- **Country** -- two-letter country code (default: US).
- **Latitude and Longitude** -- your coordinates for distance filtering.
- **Search Radius** -- how far (in miles) to search for vendor addresses.

### Fuzzy Matching

Two thresholds that control vendor name matching:

- **Match Threshold** (default 70) -- minimum score (0-100) for a vendor
  to appear in search results. Lower values show more results but with
  less confidence.
- **Ambiguous Threshold** (default 85) -- when multiple vendors score
  above this value, the match is flagged as ambiguous so you can choose
  the right one.

### Reset to Defaults

The **Reset All Settings to Defaults** button restores every setting to
its original value. A confirmation dialog prevents accidental resets.

## Vendor Sync

The tool maintains a local JSON copy of your vendor data for fast lookups.
Synchronization keeps it in step with GnuCash:

- **At startup** -- the server automatically pulls vendor data from GnuCash
  into the JSON database. Changes made directly in GnuCash (name
  corrections, address updates) are picked up.
- **Manual sync** -- click the sync button in the dashboard status bar to
  trigger a sync at any time.

The GnuCash database is always the canonical source. The JSON file is a
cache for performance and offline access.

## Keyboard Shortcuts

- **Tab** -- move between form fields.
- **Enter** -- submit the current form (Add to Queue, Submit All, etc.).
- **Escape** -- close the new vendor dialog.

## Desktop Launcher

The `GnuCash Bills.bat` file (generated by the installer) handles
everything:

1. Checks if the server is already running on port 7432.
2. If running, opens your browser to the dashboard.
3. If not running, starts the server in a separate console window, waits
   for it to be ready, then opens the browser.

The server console window stays open. Close it to stop the server.

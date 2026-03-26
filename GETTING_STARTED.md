# Getting Started

A step-by-step walkthrough of your first session with GnuCash Bill Processor.

## Prerequisites

Before you begin, make sure you have:

- **Python 3.11 or later** installed
- **uv** package manager ([install from here](https://docs.astral.sh/uv/))
- **GnuCash** with your books saved in **SQLite format**
  (File > Save As > sqlite3). The resulting file has a `.gnucash` extension.
- **Windows 10 or 11** (the desktop launcher and file picker use
  Windows-specific features)

## Step 1: Clone and Install Dependencies

```bash
git clone <repo-url>
cd GnuCash_bills_and_collections
uv sync
```

`uv sync` reads `pyproject.toml` and installs everything the project needs
into a local virtual environment. You never need to activate it manually --
all commands go through `uv run`.

## Step 2: Run the Installer

```bash
uv run python install.py
```

The installer does three things:

1. **Finds your GnuCash database.** It searches your Documents folder for
   `.gnucash` files and presents a numbered list sorted by last-modified date.
   Pick the one you use for your books, or press **b** to browse for it
   manually.

2. **Updates the configuration.** The chosen database path is saved to both
   `config.py` (fallback) and `data/user_settings.json` (runtime). You can
   change this later from the Settings page.

3. **Generates a launcher.** On Windows this is `GnuCash Bills.bat`. It
   starts the web server and opens your browser in one click.

The installer will ask if you want to copy the launcher to your Desktop.
Say yes for easy access.

## Step 3: Start the Server

Either double-click the **GnuCash Bills** shortcut on your Desktop, or run:

```bash
uv run uvicorn bill_processor.web.app:app --port 7432
```

Then open your browser to **http://localhost:7432**.

If GnuCash has the database file open, the dashboard will show a "Database
Unavailable" page explaining that the file is locked. Close GnuCash (or
close just that book), then click **Refresh**.

## Step 4: Configure Processing Accounts

Before you can process any bills, you need to tell the tool which GnuCash
accounts to use. Click **Settings** (top of the page), then
**Processing Accounts**.

You will see three sections, each showing your chart of accounts as radio
buttons:

- **Accounts Payable** -- select your A/P account (usually
  `Liabilities:Accounts Payable`).
- **Checking Account** -- select the bank account checks are drawn on.
- **Expense Account** -- select the default expense account for bills
  (for example `Expenses:General` or whichever account you charge most
  bills to).

Click the radio button for each account. Your selection is saved
automatically. Once all three are set, go back to the dashboard -- you will
see the account names displayed below the bill queue and the **Process**
buttons will be enabled.

## Step 5: Enter Your First Bill

On the left side of the dashboard you will see the **Enter a Bill** form:

1. **Vendor** -- start typing the vendor's name. A dropdown appears with
   fuzzy matches from your vendor database. Click to select. If the vendor
   is new, a dialog opens to create one (with automatic address lookup).

2. **Amount** -- enter the dollar amount of the check.

3. **Memo** -- optional note that appears on the bill in GnuCash.

4. **Date** -- defaults to today. Change it if the bill is for a different
   date.

5. **Check #** -- optional. Enter the check number for reconciliation.

Click **Add to Queue**. The bill appears in the queue above the form.

## Step 6: Process the Bill

You have two options:

- **Process** (next to each bill) -- processes that single bill.
- **Process All** (top of the queue) -- processes every bill in the queue
  at once.

Processing creates the bill, posts it, and pays it in GnuCash -- all three
accounting steps happen in under a second. You will see a success message
with the bill ID.

## Step 7: Print the Check in GnuCash

Open GnuCash. The bill is already posted and paid. Navigate to the checking
account register and find the payment transaction. Then:

1. Select the transaction.
2. Go to **File > Print Check**.
3. GnuCash prints the check with the vendor's mailing address positioned
   for a windowed envelope.

This is the entire reason the tool exists -- it automates the multi-step
bill workflow so you can get to the check printing step quickly.

## Step 8: Explore the Rest

- **Cash Entry** (right side of the dashboard) -- record cash receipts and
  bank deposits without leaving the dashboard. See the
  [User Guide](USER_GUIDE.md) for details.

- **Settings** -- configure locality for address lookups, adjust fuzzy
  matching sensitivity, manage cash entry accounts, and more.

- **Vendor Sync** -- the tool automatically syncs vendor data from GnuCash
  at startup. If you edit a vendor's name or address directly in GnuCash,
  the changes will appear next time you start the server.

## What If Something Goes Wrong?

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for solutions to common
problems including database lock errors, port conflicts, address lookup
failures, and vendor matching issues.

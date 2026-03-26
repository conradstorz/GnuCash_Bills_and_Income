# Troubleshooting

Solutions to common problems with GnuCash Bill Processor.

## Database Issues

### "Database Unavailable" on the dashboard

**Cause:** GnuCash has the database file open, which places an exclusive
lock on it.

**Fix:** Close GnuCash (or close the specific book file), then click
**Refresh** on the dashboard. The tool cannot read or write the database
while GnuCash has it open.

GnuCash records locks in a `gnclock` table inside the SQLite database
itself (not an external lock file). If GnuCash or the bill processor
crashes and leaves a stale lock behind, the tool detects and cleans it
automatically -- whenever it acquires the database lock, it first checks
whether the recorded PID is still running and removes the entry if the
process has terminated. No manual intervention is needed for stale locks
on the same machine.

### "Database not found" or wrong database

**Cause:** The configured database path points to a file that was moved,
renamed, or deleted.

**Fix:** On the "Database Unavailable" page, click **Browse for database
file** to select the correct `.gnucash` file. Or re-run the installer:

```bash
uv run python install.py
```

The installer searches your Documents folder and lets you pick the right
file.

### Database path shows a `.gnucash` file but it is not SQLite

**Cause:** GnuCash supports multiple storage formats. This tool only works
with SQLite databases.

**Fix:** In GnuCash, open your book and go to **File > Save As**. Choose
**sqlite3** as the format. Save with a new name if you want to keep the
original format. Then point the tool at the new SQLite file.

## Server and Startup

### Launcher says "Server failed to start" but the server is running

**Cause:** On the first run each day, the server may take a few extra
seconds to start while Python loads dependencies. The launcher checks for
the server after a fixed delay and may declare failure prematurely.

**Fix:** Check the server console window -- if it shows the uvicorn
startup message, the server is fine. Open http://localhost:7432 manually.
The launcher window can be closed.

### Port 7432 is already in use

**Cause:** Another instance of the server is already running, or another
application is using port 7432.

**Fix:** If a previous server instance is still running, close its console
window. If another application uses port 7432, start the server on a
different port:

```bash
uv run uvicorn bill_processor.web.app:app --port 8000
```

Then access the dashboard at http://localhost:8000.

### Server starts but browser shows a blank page

**Cause:** The browser opened before the server finished starting.

**Fix:** Wait a few seconds and refresh the page. The server typically
starts in 2-3 seconds.

## Bill Processing

### "Processing accounts not configured" error

**Cause:** One or more of the three required accounts (A/P, checking,
expense) has not been selected.

**Fix:** Go to **Settings > Processing Accounts** and select an account
in each of the three sections. All three must be set before bills can be
processed.

### Bill processes successfully but does not appear in GnuCash

**Cause:** GnuCash caches data in memory. If GnuCash was open when the
bill was processed, it will not see the new records until you reload.

**Fix:** Close and reopen the book in GnuCash (File > Close, then
File > Open Recent). Or close GnuCash entirely and reopen. The bill,
posting, and payment transactions will all appear.

**Important:** Do not have GnuCash open while processing bills. The
database lock will prevent the tool from writing.

### Wrong expense account on a bill

**Cause:** All bills use the default expense account configured in
Settings > Processing Accounts.

**Fix:** If a particular bill needs a different expense account, process
it with the current setting, then change the expense account in GnuCash
directly (edit the transaction in the register). For future bills that
consistently go to a different account, change the expense account in
Settings before processing.

## Vendor Issues

### Vendor search returns no results

**Cause:** The fuzzy matching threshold may be too high, or the vendor
name in the database may be very different from what you typed.

**Fix:**
- Try typing more of the vendor name.
- Try the official business name instead of an abbreviation.
- Lower the **Match Threshold** in **Settings > Fuzzy Matching**
  (default is 70; try 50 for looser matching).
- Check that the vendor exists in your database: open GnuCash and look
  under Business > Vendor > Find Vendor.

### New vendor created without an address

**Cause:** The address lookup did not find the business, or the address
fields were left empty when creating the vendor.

**Fix:** Edit the vendor directly in GnuCash:
1. Go to **Business > Vendor > Find Vendor**.
2. Open the vendor record.
3. Fill in the address fields (Address Line 1 for street, Address Line 2
   for city, state, ZIP).
4. Save. The corrected address will sync to the tool at next startup.

### Vendor name was corrected in GnuCash but the old name still shows

**Cause:** The local vendor database has not synced yet.

**Fix:** Click the **Sync** button in the dashboard status bar, or
restart the server. Vendor sync runs automatically at startup.

## Address Lookup

### Address lookup returns no candidates

**Cause:** The business may not be listed on Google Places or
OpenStreetMap, or the search terms did not match.

**Fix:**
- Try a more specific or more general business name.
- Check your **Locality Settings** -- if the city/state is wrong, the
  search area will be wrong.
- Increase the **Search Radius** in Settings (default 30 miles).
- Enter the address manually in the vendor creation dialog.

### Address lookup is slow

**Cause:** The tool queries external services (Google Places API or
OpenStreetMap Nominatim). Response time depends on the service and your
internet connection.

**Fix:** Google Places is faster and more accurate but requires an API
key. Without a key, the tool falls back to OpenStreetMap which has rate
limits (1 request per second). See `GOOGLE_API_SETUP.md` to configure
the Google Places API key.

## Cash Entry

### "No accounts available" in cash entry dropdown

**Cause:** No income/asset accounts are enabled in settings.

**Fix:** Go to **Settings > Cash Entry Accounts** and check the accounts
you want to use for cash entries.

### Cash entry total is wrong

**Cause:** The SAMUSE Total is a running sum of all rows. It updates as
you type.

**Fix:** Check each row's amount. Positive values add to the total,
negative values subtract. The SAMUSE account receives the balancing entry
(opposite sign of the total).

## Installation

### `uv sync` fails with dependency errors

**Fix:** Make sure you have Python 3.11 or later:

```bash
python --version
```

If your Python is older, install a newer version and try again.

### `uv run python install.py` cannot find `.gnucash` files

**Cause:** The installer only searches the Documents folder by default.

**Fix:** When prompted, press **b** to browse and navigate to wherever
your GnuCash file is stored.

### Installer shows "Could not find PROJECT_ROOT in config.py"

**Cause:** `config.py` has been modified in a way the installer does not
expect.

**Fix:** Check that `config.py` contains a line like
`PROJECT_ROOT = Path(...)`. If the file is damaged, restore it from git:

```bash
git checkout config.py
uv run python install.py
```

## Logs

The tool writes detailed logs to `logs/bill_processor.log`. When
reporting a problem, check the log for error messages and stack traces.
The log includes timestamps, log levels, and the source file and line
number for each message.

Console output shows INFO-level messages and above. The log file captures
everything down to DEBUG level.

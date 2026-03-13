"""
FastAPI web application for GnuCash Bill Processor.
Serves a state-aware dashboard for managing vendor bills.
"""
import html
import json
import os
import subprocess
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger

from bill_processor import gnucash_db
from bill_processor import config
from bill_processor.settings_manager import settings
import bill_processor.address_lookup as addr_lookup
from bill_processor.utils import parse_input_line, fuzzy_match_vendor, strip_vendor_name
from bill_processor.vendor_manager import VendorManager
from bill_processor.vendor_sync import VendorSyncUtility
from bill_processor.web import queue_io

BASE_DIR = Path(__file__).parent
# Path to config.py — patched in tests for POST /db/set-path
CONFIG_FILE_PATH = Path(__file__).parent.parent / "config.py"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="GnuCash Bill Processor")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

VENDOR_SEARCH_MIN_SCORE = 40  # Lower threshold for dropdown suggestions


def _get_enabled_cash_accounts() -> list:
    """Get cash accounts that are enabled in settings."""
    all_accounts = gnucash_db.get_cash_accounts()
    enabled_guids = settings.get("enabled_cash_account_guids", [])
    
    # If no enabled list exists, enable all by default
    if not enabled_guids:
        enabled_guids = [acct["guid"] for acct in all_accounts]
        settings.set("enabled_cash_account_guids", enabled_guids)
    
    # Filter to only enabled accounts
    return [acct for acct in all_accounts if acct["guid"] in enabled_guids]


def _get_sync_status() -> dict:
    """Return vendor sync status: counts and whether sync is needed."""
    try:
        vm = VendorManager()
        json_guids = {
            v.get("gnucash_guid")
            for v in vm.vendors.get("vendors", {}).values()
            if v.get("gnucash_guid")
        }
        gc_vendors = gnucash_db.get_all_vendors()
        gc_guids = {v["guid"] for v in gc_vendors}
        needs_sync = not json_guids.issubset(gc_guids) or not gc_guids.issubset(json_guids)
        return {
            "json_count": len(vm.vendors.get("vendors", {})),
            "gc_count": len(gc_vendors),
            "needs_sync": needs_sync,
        }
    except Exception as e:
        logger.warning(f"Could not check sync status: {e}")
        return {"json_count": 0, "gc_count": 0, "needs_sync": False, "error": str(e)}


@app.get("/status")
def get_status():
    """Return current system state as JSON (used by HTMX polling)."""
    queue = queue_io.read_queue()
    sync = _get_sync_status()
    return {
        "vendor_sync": sync,
        "queued_bills": len(queue),
        "db_ok": gnucash_db.test_connection(),
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Render the main dashboard."""
    # --- DB health check (must be first) ---
    health = gnucash_db.check_db_health()
    if health["status"] != "ok":
        return templates.TemplateResponse(
            request, "db_unavailable.html", {"health": health}
        )

    queue = queue_io.read_queue()
    sync = _get_sync_status()
    try:
        recent = gnucash_db.get_unpaid_bills()[:10]
    except Exception as e:
        logger.warning(f"Could not load recent bills: {e}")
        recent = []
    return templates.TemplateResponse(request, "dashboard.html", {
        "queue": queue,
        "sync": sync,
        "recent_bills": recent,
        "today": date.today().isoformat(),
        "tomorrow": (date.today() + timedelta(days=1)).isoformat(),
        "last_error": None,
        "error": None,
        "cash_accounts": _get_enabled_cash_accounts(),
        "bank_accounts": gnucash_db.get_checking_accounts(),
    })


@app.post("/bills/queue", response_class=HTMLResponse)
def add_to_queue(
    request: Request,
    vendor_name: str = Form(...),
    amount: float = Form(...),
    memo: str = Form(""),
    bill_date: str = Form(""),
):
    """Add a bill to the queue and return refreshed bill entry form."""
    if not vendor_name.strip():
        return HTMLResponse('<p class="error-msg">Vendor name is required.</p>', status_code=200)
    if amount <= 0:
        return HTMLResponse('<p class="error-msg">Amount must be greater than zero.</p>', status_code=200)
    try:
        parsed_date = date.fromisoformat(bill_date) if bill_date else date.today()
    except ValueError:
        parsed_date = date.today()
    queue_io.add_bill(vendor_name, amount, memo, parsed_date)
    return templates.TemplateResponse(request, "bill_entry.html", {
        "today": date.today().isoformat(),
        "success": f"Added {vendor_name} ${amount:.2f} to queue",
    })


@app.delete("/bills/queue/{index}", response_class=HTMLResponse)
def remove_from_queue(request: Request, index: int):
    """Remove a bill from the queue by file-line index."""
    ok = queue_io.remove_bill(index)
    queue = queue_io.read_queue()
    return templates.TemplateResponse(request, "partials/queued_bills.html", {
        "queue": queue,
        "last_error": None if ok else f"Could not remove bill at index {index}",
    })


def _process_one_bill(bill: dict) -> dict:
    """
    Run create/post/pay for a single queued bill dict.
    Returns {"ok": True} or {"ok": False, "error": str}.
    """
    vm = VendorManager()
    vendor_data, match_type = vm.find_vendor(bill["vendor_name"])
    if not vendor_data:
        return {"ok": False, "error": f"Vendor not found: {bill['vendor_name']}"}

    vendor_guid = vendor_data.get("gnucash_guid")
    if not vendor_guid:
        gc_vendor = gnucash_db.find_vendor_by_name(vendor_data.get("display_name", ""))
        if not gc_vendor:
            return {"ok": False, "error": f"No GnuCash record for vendor: {vendor_data.get('display_name')}"}
        vendor_guid = gc_vendor["guid"]

    # Get expense account GUID — check both possible field names in vendor_data
    expense_guid = vendor_data.get("expense_account_guid") or vendor_data.get("expense_account")
    # expense_account may hold a name string rather than a GUID; treat short strings as names
    if expense_guid and len(str(expense_guid)) != 32:
        expense_guid = None
    if not expense_guid:
        return {"ok": False, "error": f"No expense account GUID for vendor: {vendor_data.get('display_name')}"}

    checking_accounts = gnucash_db.get_checking_accounts()
    if not checking_accounts:
        return {"ok": False, "error": "No checking account found in GnuCash"}
    checking_guid = checking_accounts[0]["guid"]

    bill_date = bill["date"]
    try:
        bill_guid = gnucash_db.create_bill(
            vendor_guid=vendor_guid,
            expense_account_guid=expense_guid,
            amount=bill["amount"],
            memo=bill.get("memo", ""),
            bill_date=bill_date,
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill_date,
            due_date=bill_date,
        )
        gnucash_db.pay_bill(
            bill_guid=bill_guid,
            checking_account_guid=checking_guid,
            payment_date=bill_date,
            memo=bill.get("memo", ""),
        )
        logger.info(f"Processed bill: {bill['vendor_name']} ${bill['amount']:.2f}")
        return {"ok": True}
    except Exception as e:
        logger.error(
            f"Failed to process bill {bill['vendor_name']}: {e}. "
            f"Bill may have been partially created in GnuCash — check for duplicates before retrying."
        )
        return {"ok": False, "error": f"{e} (bill may be partially created in GnuCash — check before retrying)"}


@app.post("/bills/queue/process", response_class=HTMLResponse)
def process_all(request: Request):
    """Process all queued bills through GnuCash."""
    queue = queue_io.read_queue()
    errors = []
    # Sort descending by file-line index so removals don't shift earlier indices
    for bill in sorted(queue, key=lambda b: b["_index"], reverse=True):
        result = _process_one_bill(bill)
        if result["ok"]:
            queue_io.remove_bill(bill["_index"])
        else:
            errors.append(f"{bill['vendor_name']}: {result['error']}")
    remaining = queue_io.read_queue()
    return templates.TemplateResponse(request, "partials/queued_bills.html", {
        "queue": remaining,
        "last_error": "; ".join(errors) if errors else None,
    })


@app.post("/bills/queue/{index}/process", response_class=HTMLResponse)
def process_one(request: Request, index: int):
    """Process a single queued bill through GnuCash."""
    queue = queue_io.read_queue()
    # Find the bill with this file-line index
    bill = next((b for b in queue if b["_index"] == index), None)
    if not bill:
        return templates.TemplateResponse(request, "partials/queued_bills.html", {
            "queue": queue,
            "last_error": f"Bill at index {index} not found in queue",
        })
    result = _process_one_bill(bill)
    if result["ok"]:
        queue_io.remove_bill(index)
    remaining = queue_io.read_queue()
    return templates.TemplateResponse(request, "partials/queued_bills.html", {
        "queue": remaining,
        "last_error": None if result["ok"] else result["error"],
    })


@app.patch("/bills/queue/{index}", response_class=HTMLResponse)
def edit_queue_item(
    request: Request,
    index: int,
    vendor_name: str = Form(...),
    amount: float = Form(...),
    memo: str = Form(""),
    bill_date: str = Form(""),
):
    """Update a queued bill and return refreshed queue card."""
    if not vendor_name.strip():
        return HTMLResponse('<p class="error-msg">Vendor name is required.</p>', status_code=200)
    if amount <= 0:
        return HTMLResponse('<p class="error-msg">Amount must be greater than zero.</p>', status_code=200)
    try:
        parsed_date = date.fromisoformat(bill_date) if bill_date else date.today()
    except ValueError:
        parsed_date = date.today()
    ok = queue_io.update_bill(index, vendor_name, amount, memo, parsed_date)
    queue = queue_io.read_queue()
    return templates.TemplateResponse(request, "partials/queued_bills.html", {
        "queue": queue,
        "last_error": None if ok else f"Could not update bill at index {index}",
    })


@app.get("/vendors/search", response_class=HTMLResponse)
def vendor_search(request: Request, vendor_name: str = ""):
    """Return HTML dropdown fragment of fuzzy-matched vendors."""
    if not vendor_name or len(vendor_name.strip()) < 2:
        return HTMLResponse("")

    try:
        vm = VendorManager()
        _, _, candidates = fuzzy_match_vendor(
            vendor_name.strip(), vm.vendors.get("vendors", {})
        )
    except Exception as e:
        logger.warning(f"Vendor search failed for '{vendor_name}': {e}")
        return HTMLResponse("")

    seen = set()
    results = []
    for key, score in candidates:
        if score >= VENDOR_SEARCH_MIN_SCORE and key not in seen:
            seen.add(key)
            vdata = vm.vendors["vendors"].get(key, {})
            results.append({
                "key": key,
                "display_name": vdata.get("display_name", key),
                "score": score,
            })

    return templates.TemplateResponse(request, "partials/vendor_dropdown.html", {
        "results": results[:6],
        "query": vendor_name.strip(),
    })


@app.get("/vendors/new-form", response_class=HTMLResponse)
def new_vendor_form(request: Request, name: str = ""):
    """Return the new vendor inline creation form."""
    return templates.TemplateResponse(request, "partials/new_vendor_form.html", {
        "vendor_name": name,
        "display_name": name,
        "addr_line1": "",
        "addr_line2": "",
        "addr_city": "",
        "addr_state": "",
        "addr_zip": "",
        "addr_phone": "",
        "message": "",
    })


@app.post("/vendors/lookup-address", response_class=HTMLResponse)
def lookup_address(request: Request, vendor_name: str = Form(""), display_name: str = Form("")):
    """Look up address candidates and return a picker fragment."""
    search_name = display_name.strip() or vendor_name.strip()
    candidates = []
    message = ""
    try:
        candidates = addr_lookup.lookup_google_places(search_name, return_all=True) or []
        if not candidates:
            candidates = addr_lookup.lookup_openstreetmap(search_name, return_all=True) or []
        if not candidates:
            message = "No results found — enter address manually"
    except Exception as e:
        logger.warning(f"Address lookup failed for '{search_name}': {e}")
        message = "Address lookup unavailable — enter manually"

    return templates.TemplateResponse(request, "partials/address_candidates.html", {
        "candidates": candidates,
        "message": message,
    })


@app.post("/vendors/create", response_class=HTMLResponse)
def create_vendor_route(
    request: Request,
    vendor_name: str = Form(""),
    display_name: str = Form(""),
    addr_line1: str = Form(""),
    addr_line2: str = Form(""),
    addr_city: str = Form(""),
    addr_state: str = Form(""),
    addr_zip: str = Form(""),
    addr_phone: str = Form(""),
):
    """Create vendor in GnuCash + JSON cache, return confirmation fragment."""
    display_name = display_name.strip() or vendor_name.strip()
    if not display_name:
        return HTMLResponse('<p class="error-msg">Vendor name is required.</p>')

    try:
        guid = gnucash_db.create_vendor(
            name=display_name,
            addr_name=display_name,
            addr_addr1=addr_line1,
            addr_addr2=addr_line2,
            addr_city=addr_city,
            addr_state=addr_state,
            addr_zip=addr_zip,
            addr_phone=addr_phone,
        )
        # Cache in JSON vendor database
        vm = VendorManager()
        key = strip_vendor_name(display_name)
        vm.vendors["vendors"][key] = {
            "display_name": display_name,
            "gnucash_guid": guid,
            "addr_line1": addr_line1,
            "addr_line2": addr_line2,
            "addr_city": addr_city,
            "addr_state": addr_state,
            "addr_zip": addr_zip,
            "addr_phone": addr_phone,
        }
        vm.save()
        logger.info(f"Created vendor '{display_name}' with GUID {guid}")
        # Return JS to update the vendor input field, plus a success message
        return HTMLResponse(
            f'<div class="success-msg">&#10003; Created vendor: {html.escape(display_name)}</div>'
            f'<script>document.getElementById("vendor-input").value = {json.dumps(display_name)};</script>'
        )
    except Exception as e:
        logger.error(f"Failed to create vendor '{display_name}': {e}")
        return HTMLResponse(f'<p class="error-msg">Failed to create vendor: {e}</p>')


@app.post("/vendors/sync", response_class=HTMLResponse)
def sync_vendors(request: Request):
    """Run bidirectional vendor sync and return updated status card."""
    error = None
    try:
        util = VendorSyncUtility()
        util.sync_all_vendors()
    except Exception as e:
        error = str(e)
        logger.error(f"Vendor sync failed: {e}")
    sync = _get_sync_status()
    return templates.TemplateResponse(request, "partials/sync_status.html", {
        "sync": sync,
        "error": error,
    })


@app.get("/partials/sync-status", response_class=HTMLResponse)
def get_sync_status_partial(request: Request):
    """Return the sync status card (for HTMX polling)."""
    sync = _get_sync_status()
    return templates.TemplateResponse(request, "partials/sync_status.html", {
        "sync": sync,
        "error": None,  # Polling auto-clears stale action errors — intentional
    })


@app.get("/partials/queued-bills", response_class=HTMLResponse)
def get_queued_bills_partial(request: Request):
    """Return the queued bills card (for HTMX polling)."""
    queue = queue_io.read_queue()
    return templates.TemplateResponse(request, "partials/queued_bills.html", {
        "queue": queue,
        "last_error": None,  # Polling auto-clears stale action errors — intentional
    })


# ---------------------------------------------------------------------------
# Cash-on-hand entry routes
# ---------------------------------------------------------------------------

@app.get("/cash/add-row")
async def cash_add_row(request: Request):
    """Return a blank line item row for the cash entry table."""
    cash_accounts = _get_enabled_cash_accounts()
    return templates.TemplateResponse(request, "partials/cash_row.html", {
        "cash_accounts": cash_accounts,
    })


@app.get("/clients/datalist")
async def clients_datalist(request: Request):
    """Return a populated <datalist> element for client autocomplete."""
    from bill_processor.web.cash_io import read_clients
    clients = read_clients()
    options = "".join(f'<option value="{c}">' for c in clients)
    datalist_html = f'<datalist id="client-list">{options}</datalist>'
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=datalist_html)


@app.get("/clients/search")
async def clients_search(memo: str = ""):
    """Return autocomplete suggestions as JSON."""
    from bill_processor.web.cash_io import search_clients
    return search_clients(memo)


@app.get("/accounts/asset")
async def accounts_asset_list():
    """Return list of all asset account names for autocomplete."""
    from bill_processor import gnucash_db
    accounts = gnucash_db.get_asset_accounts()
    return {"accounts": [acc["name"] for acc in accounts]}


@app.get("/accounts/all")
async def accounts_all_list():
    """Return list of all account names for autocomplete."""
    from bill_processor import gnucash_db
    accounts = gnucash_db.get_all_accounts()
    return {"accounts": [acc["name"] for acc in accounts]}


@app.get("/accounts/validate")
async def accounts_validate(request: Request, name: str = ""):
    """Validate if an account name exists in GnuCash and return HTML feedback."""
    if not name or not name.strip():
        return templates.TemplateResponse(
            request,
            "partials/account_validation.html",
            {"valid": False, "message": "Enter an account name"}
        )
    
    from bill_processor import gnucash_db
    account = gnucash_db.get_account_by_name(name.strip())
    
    if account:
        return templates.TemplateResponse(
            request,
            "partials/account_validation.html",
            {"valid": True, "message": "Account found"}
        )
    else:
        return templates.TemplateResponse(
            request,
            "partials/account_validation.html",
            {"valid": False, "message": "Account not found"}
        )


@app.get("/accounts/datalist")
async def accounts_datalist():
    """Return a populated <datalist> element for account name autocomplete."""
    from bill_processor import gnucash_db
    from fastapi.responses import HTMLResponse
    accounts = gnucash_db.get_all_accounts()
    options = "".join(f'<option value="{acc["name"]}">' for acc in accounts)
    datalist_html = f'<datalist id="account-list">{options}</datalist>'
    return HTMLResponse(content=datalist_html)


@app.post("/cash/submit")
async def cash_submit(request: Request):
    """Process the cash entry form: create batch transaction + optional deposit."""
    from datetime import date as date_type, timedelta
    from fastapi.responses import HTMLResponse

    form = await request.form()

    # Parse repeated form fields (one per row)
    account_guids = form.getlist("account_guid")
    memos = form.getlist("memo")
    amounts_raw = form.getlist("amount")

    # Build line_items — skip rows where any field is blank
    line_items = []
    for guid, memo_val, amount_str in zip(account_guids, memos, amounts_raw):
        guid = guid.strip()
        memo_val = memo_val.strip()
        amount_str = amount_str.strip()
        if guid and memo_val and amount_str:
            try:
                line_items.append({
                    "account_guid": guid,
                    "memo": memo_val,
                    "amount": float(amount_str),
                })
            except ValueError:
                pass

    def _render_panel(error=None, success=None):
        today = date_type.today()
        return templates.TemplateResponse(
            request,
            "partials/cash_entry.html",
            {
                "cash_accounts": _get_enabled_cash_accounts(),
                "bank_accounts": gnucash_db.get_checking_accounts(),
                "today": today.isoformat(),
                "tomorrow": (today + timedelta(days=1)).isoformat(),
                "error": error,
                "success": success,
            },
        )

    if not line_items:
        return _render_panel(error="At least one complete line item is required.")

    entry_date_str = (form.get("entry_date") or "").strip()
    try:
        entry_date = date_type.fromisoformat(entry_date_str)
    except ValueError:
        entry_date = date_type.today()

    # Create batch transaction
    try:
        gnucash_db.create_cash_entry(
            entry_date=entry_date,
            line_items=line_items,
            description="Cash receipt",
        )
    except Exception as exc:
        return _render_panel(error=str(exc))

    # Optional deposit transaction
    deposit_error = None
    deposit_amount_str = (form.get("deposit_amount") or "").strip()
    deposit_account_guid = (form.get("deposit_account_guid") or "").strip()
    deposit_date_str = (form.get("deposit_date") or "").strip()

    if deposit_account_guid and deposit_amount_str:
        try:
            deposit_amount = float(deposit_amount_str)
            try:
                deposit_date = date_type.fromisoformat(deposit_date_str)
            except ValueError:
                deposit_date = date_type.today() + timedelta(days=1)
            gnucash_db.create_cash_deposit(
                deposit_date=deposit_date,
                bank_account_guid=deposit_account_guid,
                amount=deposit_amount,
            )
        except Exception as exc:
            deposit_error = str(exc)

    total = sum(item["amount"] for item in line_items)
    success_msg = f"Posted ${total:.2f} to SAMUSE Cash-on-hand."
    if deposit_amount_str and deposit_account_guid:
        if deposit_error:
            success_msg += f" (Deposit failed: {deposit_error})"
        else:
            success_msg += f" Deposit of ${float(deposit_amount_str):.2f} recorded."

    return _render_panel(success=success_msg)


# ---------------------------------------------------------------------------
# DB configuration routes
# ---------------------------------------------------------------------------

@app.get("/db/browse")
async def db_browse():
    """Open a native Windows file picker and return the selected path."""
    try:
        result = subprocess.run(
            [
                sys.executable, "-c",
                "import tkinter as tk; from tkinter import filedialog; "
                "root = tk.Tk(); root.withdraw(); "
                "root.wm_attributes('-topmost', 1); "
                "path = filedialog.askopenfilename("
                "    title='Select GnuCash database file',"
                "    filetypes=[('GnuCash files', '*.gnucash'), ('All files', '*.*')]"
                "); print(path)"
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        path = result.stdout.strip()
    except Exception:
        path = ""
    return {"path": path}


@app.post("/db/set-path")
async def db_set_path(request: Request):
    """Write a new GNUCASH_DB_PATH to config.py and reload config."""
    import re
    import importlib
    from fastapi.responses import RedirectResponse
    from bill_processor import config as cfg

    form = await request.form()
    new_path = (form.get("new_path") or "").strip()

    def _error(msg: str):
        health = gnucash_db.check_db_health()
        return templates.TemplateResponse(
            request, "db_unavailable.html",
            {"health": health, "path_error": msg}
        )

    if not new_path:
        return _error("No path provided.")

    if not new_path.lower().endswith(".gnucash"):
        return _error("File must have a .gnucash extension.")

    if not Path(new_path).exists():
        return _error(f"File not found: {new_path}")

    # Update config.py in place
    config_text = CONFIG_FILE_PATH.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(GNUCASH_DB_PATH\s*=\s*Path\(r?)["\'].*?["\'](\))',
        lambda m: f'{m.group(1)}r"{new_path}"{m.group(2)}',
        config_text,
    )
    if count == 0:
        return _error("Could not update config.py — GNUCASH_DB_PATH line not found.")

    CONFIG_FILE_PATH.write_text(new_text, encoding="utf-8")

    # Reload config so the running server picks up the change immediately
    importlib.reload(cfg)

    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Settings routes
# ---------------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Render the settings page."""
    # Get all available cash accounts from GnuCash
    all_cash_accounts = gnucash_db.get_cash_accounts()
    
    # Get currently enabled cash account GUIDs
    enabled_guids = settings.get("enabled_cash_account_guids", [])
    if not enabled_guids:
        # If not set, enable all accounts by default
        enabled_guids = [acct["guid"] for acct in all_cash_accounts]
        settings.set("enabled_cash_account_guids", enabled_guids)
    
    # Mark which accounts are enabled
    for acct in all_cash_accounts:
        acct["enabled"] = acct["guid"] in enabled_guids
    
    return templates.TemplateResponse(request, "settings.html", {
        "settings": settings,
        "cash_accounts": all_cash_accounts,
        "current_cash_on_hand": settings.get("cash_on_hand_account_name"),
        "success": None,
        "error": None,
    })


@app.post("/settings/cash-accounts", response_class=HTMLResponse)
async def update_cash_accounts(request: Request):
    """Update which cash accounts are enabled for cash entry dropdown."""
    form = await request.form()
    
    # Get list of checked account GUIDs
    enabled_guids = form.getlist("enabled_accounts")
    
    if not enabled_guids:
        # If none selected, show error
        all_cash_accounts = gnucash_db.get_cash_accounts()
        for acct in all_cash_accounts:
            acct["enabled"] = False
        
        return templates.TemplateResponse(request, "settings.html", {
            "settings": settings,
            "cash_accounts": all_cash_accounts,
            "current_cash_on_hand": settings.get("cash_on_hand_account_name"),
            "success": None,
            "error": "At least one cash account must be enabled.",
        })
    
    # Save to settings
    settings.set("enabled_cash_account_guids", enabled_guids)
    logger.info(f"Updated enabled cash accounts: {len(enabled_guids)} accounts")
    
    # Redirect back to settings page with success message
    all_cash_accounts = gnucash_db.get_cash_accounts()
    for acct in all_cash_accounts:
        acct["enabled"] = acct["guid"] in enabled_guids
    
    return templates.TemplateResponse(request, "settings.html", {
        "settings": settings,
        "cash_accounts": all_cash_accounts,
        "current_cash_on_hand": settings.get("cash_on_hand_account_name"),
        "success": f"Updated cash account visibility - {len(enabled_guids)} accounts enabled",
        "error": None,
    })


@app.post("/settings/cash-on-hand-account", response_class=HTMLResponse)
async def update_cash_on_hand_account(request: Request):
    """Update the cash-on-hand account setting."""
    form = await request.form()
    new_account_name = (form.get("cash_on_hand_account") or "").strip()
    
    if not new_account_name:
        all_cash_accounts = gnucash_db.get_cash_accounts()
        enabled_guids = settings.get("enabled_cash_account_guids", [])
        for acct in all_cash_accounts:
            acct["enabled"] = acct["guid"] in enabled_guids
        
        return templates.TemplateResponse(request, "settings.html", {
            "settings": settings,
            "cash_accounts": all_cash_accounts,
            "current_cash_on_hand": settings.get("cash_on_hand_account_name"),
            "success": None,
            "error": "Cash-on-hand account name cannot be empty.",
        })
    
    # Update setting
    settings.set("cash_on_hand_account_name", new_account_name)
    logger.info(f"Updated cash-on-hand account to: {new_account_name}")
    
    # Redirect back with success message
    all_cash_accounts = gnucash_db.get_cash_accounts()
    enabled_guids = settings.get("enabled_cash_account_guids", [])
    for acct in all_cash_accounts:
        acct["enabled"] = acct["guid"] in enabled_guids
    
    return templates.TemplateResponse(request, "settings.html", {
        "settings": settings,
        "cash_accounts": all_cash_accounts,
        "current_cash_on_hand": new_account_name,
        "success": f"Cash-on-hand account updated to: {new_account_name}",
        "error": None,
    })


@app.post("/settings/locality", response_class=HTMLResponse)
async def update_locality_settings(request: Request):
    """Update locality settings."""
    form = await request.form()
    
    city = (form.get("locality_city") or "").strip()
    state = (form.get("locality_state") or "").strip()
    country = (form.get("locality_country") or "").strip()
    
    try:
        latitude = float(form.get("home_latitude") or 0)
        longitude = float(form.get("home_longitude") or 0)
        search_radius = int(form.get("search_radius_miles") or 30)
    except (ValueError, TypeError):
        all_cash_accounts = gnucash_db.get_cash_accounts()
        enabled_guids = settings.get("enabled_cash_account_guids", [])
        for acct in all_cash_accounts:
            acct["enabled"] = acct["guid"] in enabled_guids
        
        return templates.TemplateResponse(request, "settings.html", {
            "settings": settings,
            "cash_accounts": all_cash_accounts,
            "current_cash_on_hand": settings.get("cash_on_hand_account_name"),
            "success": None,
            "error": "Invalid numeric values for coordinates or search radius.",
        })
    
    # Update locality
    settings.update_locality(city, state, country, latitude, longitude, search_radius)
    logger.info(f"Updated locality settings: {city}, {state}")
    
    all_cash_accounts = gnucash_db.get_cash_accounts()
    enabled_guids = settings.get("enabled_cash_account_guids", [])
    for acct in all_cash_accounts:
        acct["enabled"] = acct["guid"] in enabled_guids
    
    return templates.TemplateResponse(request, "settings.html", {
        "settings": settings,
        "cash_accounts": all_cash_accounts,
        "current_cash_on_hand": settings.get("cash_on_hand_account_name"),
        "success": f"Locality updated: {city}, {state} ({search_radius} mile radius)",
        "error": None,
    })


@app.post("/settings/fuzzy-matching", response_class=HTMLResponse)
async def update_fuzzy_matching(request: Request):
    """Update fuzzy matching thresholds."""
    form = await request.form()
    
    try:
        threshold = int(form.get("fuzzy_match_threshold") or 70)
        ambiguous = int(form.get("fuzzy_ambiguous_threshold") or 85)
    except (ValueError, TypeError):
        all_cash_accounts = gnucash_db.get_cash_accounts()
        enabled_guids = settings.get("enabled_cash_account_guids", [])
        for acct in all_cash_accounts:
            acct["enabled"] = acct["guid"] in enabled_guids
        
        return templates.TemplateResponse(request, "settings.html", {
            "settings": settings,
            "cash_accounts": all_cash_accounts,
            "current_cash_on_hand": settings.get("cash_on_hand_account_name"),
            "success": None,
            "error": "Invalid numeric values for fuzzy matching thresholds.",
        })
    
    # Validate ranges
    if not 0 <= threshold <= 100 or not 0 <= ambiguous <= 100:
        all_cash_accounts = gnucash_db.get_cash_accounts()
        enabled_guids = settings.get("enabled_cash_account_guids", [])
        for acct in all_cash_accounts:
            acct["enabled"] = acct["guid"] in enabled_guids
        
        return templates.TemplateResponse(request, "settings.html", {
            "settings": settings,
            "cash_accounts": all_cash_accounts,
            "current_cash_on_hand": settings.get("cash_on_hand_account_name"),
            "success": None,
            "error": "Thresholds must be between 0 and 100.",
        })
    
    settings.update(
        fuzzy_match_threshold=threshold,
        fuzzy_ambiguous_threshold=ambiguous
    )
    logger.info(f"Updated fuzzy matching: threshold={threshold}, ambiguous={ambiguous}")
    
    all_cash_accounts = gnucash_db.get_cash_accounts()
    enabled_guids = settings.get("enabled_cash_account_guids", [])
    for acct in all_cash_accounts:
        acct["enabled"] = acct["guid"] in enabled_guids
    
    return templates.TemplateResponse(request, "settings.html", {
        "settings": settings,
        "cash_accounts": all_cash_accounts,
        "current_cash_on_hand": settings.get("cash_on_hand_account_name"),
        "success": f"Fuzzy matching updated: threshold={threshold}, ambiguous={ambiguous}",
        "error": None,
    })


@app.post("/settings/reset")
async def reset_settings(request: Request):
    """Reset all settings to defaults."""
    settings.reset_to_defaults()
    logger.info("Reset all settings to defaults")
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/shutdown")
def shutdown():
    """Stop the server. Uses os._exit for reliable cross-platform termination."""
    def _stop():
        time.sleep(config.SERVER_SHUTDOWN_DELAY_SECONDS)
        os._exit(0)
    threading.Thread(target=_stop, daemon=True).start()
    return {"message": "Server shutting down"}

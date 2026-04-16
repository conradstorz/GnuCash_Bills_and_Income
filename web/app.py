"""FastAPI REST API for GnuCash Bill Processor."""
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

from bill_processor import gnucash_db, logging_setup
from bill_processor.settings_manager import settings
import bill_processor.address_lookup as addr_lookup
from bill_processor.utils import fuzzy_match_vendor
from bill_processor.vendor_manager import VendorManager
from bill_processor.vendor_sync import VendorSyncUtility
from bill_processor.web import queue_io, cash_io

BASE_DIR = Path(__file__).parent
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"

VENDOR_SEARCH_MIN_SCORE = 40


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging_setup.setup_logging(module_name="web")
    logger.info("GnuCash Bills web application starting")
    logger.info(f"Database: {settings.gnucash_db_path}")
    try:
        sync = VendorSyncUtility()
        if sync.discover_schema():
            sync.sync_gnucash_to_json()
            logger.info("Startup vendor sync complete")
        else:
            logger.warning("Startup vendor sync skipped — schema discovery failed")
    except Exception as e:
        logger.warning(f"Startup vendor sync failed: {e}")
    logger.info("Server running on http://127.0.0.1:7432")
    yield


app = FastAPI(title="GnuCash Bill Processor", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Internal helpers (unchanged from previous version)
# ---------------------------------------------------------------------------

def _get_enabled_cash_accounts() -> list:
    all_accounts = gnucash_db.get_cash_accounts()
    enabled_guids = settings.get("enabled_cash_account_guids", [])
    if not enabled_guids:
        enabled_guids = [acct["guid"] for acct in all_accounts]
        settings.set("enabled_cash_account_guids", enabled_guids)
    return [acct for acct in all_accounts if acct["guid"] in enabled_guids]


def _get_sync_status() -> dict:
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


def _account_name(guid):
    if not guid:
        return None
    acct = gnucash_db.get_account_by_guid(guid)
    return acct["name"] if acct else None


def _process_one_bill(bill: dict) -> dict:
    """Process a single bill: create → post → pay in GnuCash.

    Returns {"ok": True} on success or {"ok": False, "error": "..."} on failure.
    """
    ap_guid = settings.ap_account_guid
    checking_guid = settings.checking_account_guid
    if not ap_guid or not checking_guid:
        return {
            "ok": False,
            "error": "Processing accounts not configured — visit Settings > Processing Accounts",
        }
    ap_account = gnucash_db.get_account_by_guid(ap_guid)
    checking_account = gnucash_db.get_account_by_guid(checking_guid)
    if not ap_account or not checking_account:
        return {
            "ok": False,
            "error": "Configured account not found in GnuCash — update Settings > Processing Accounts",
        }
    logger.info("Using A/P account: {} ({})", ap_account["name"], ap_guid[:8])
    logger.info("Using checking account: {} ({})", checking_account["name"], checking_guid[:8])

    vm = VendorManager()
    vendor, match_type = vm.find_vendor(bill["vendor_name"])
    if vendor is None:
        return {"ok": False, "error": f"Vendor not found: {bill['vendor_name']}"}

    expense_account_guid = settings.expense_account_guid
    if not expense_account_guid:
        return {
            "ok": False,
            "error": "No expense account configured — set one in Processing Accounts settings",
        }
    try:
        bill_guid = gnucash_db.create_bill(
            vendor_guid=vendor["gnucash_guid"],
            expense_account_guid=expense_account_guid,
            amount=bill["amount"],
            memo=bill.get("memo", ""),
            bill_date=bill["date"],
        )
        gnucash_db.post_bill(
            bill_guid=bill_guid,
            post_date=bill["date"],
            ap_account_guid=ap_guid,
        )
        gnucash_db.pay_bill(
            bill_guid=bill_guid,
            payment_date=bill["date"],
            checking_account_guid=checking_guid,
            check_number=bill.get("check_number", ""),
        )
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _serialize_bill(bill: dict) -> dict:
    """Convert a queue_io bill dict to a JSON-serializable form."""
    return {
        "index": bill["_index"],
        "vendor_name": bill["vendor_name"],
        "amount": bill["amount"],
        "memo": bill.get("memo", ""),
        "date": bill["date"].isoformat() if hasattr(bill["date"], "isoformat") else str(bill["date"]),
        "check_number": bill.get("check_number", ""),
    }


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BillIn(BaseModel):
    vendor_name: str
    amount: float
    memo: str = ""
    bill_date: str = ""
    check_number: str = ""


class CashEntryRow(BaseModel):
    account_guid: str
    memo: str
    amount: float


class CashSubmitIn(BaseModel):
    entry_date: str
    entries: list[CashEntryRow]
    deposit_account_guid: Optional[str] = None
    deposit_amount: Optional[float] = None
    deposit_date: Optional[str] = None


class DepositIn(BaseModel):
    account_guid: str
    amount: float
    entry_date: str
    memo: str = ""


class VendorIn(BaseModel):
    vendor_name: str
    display_name: str = ""
    addr_line1: str = ""
    addr_city: str = ""
    addr_state: str = ""
    addr_zip: str = ""


class VendorUpdate(BaseModel):
    display_name: Optional[str] = None
    addr_line1: Optional[str] = None
    addr_city: Optional[str] = None
    addr_state: Optional[str] = None
    addr_zip: Optional[str] = None
    aliases: Optional[list[str]] = None


class SettingsUpdate(BaseModel):
    ap_account_guid: Optional[str] = None
    checking_account_guid: Optional[str] = None
    expense_account_guid: Optional[str] = None
    cash_on_hand_account_name: Optional[str] = None
    locality_city: Optional[str] = None
    locality_state: Optional[str] = None
    home_latitude: Optional[float] = None
    home_longitude: Optional[float] = None
    search_radius_miles: Optional[float] = None
    fuzzy_match_threshold: Optional[int] = None
    fuzzy_ambiguous_threshold: Optional[int] = None
    enabled_cash_account_guids: Optional[list[str]] = None
    gnucash_db_path: Optional[str] = None


class AddressLookupIn(BaseModel):
    display_name: str = ""
    vendor_name: str = ""
    addr_city: str = ""
    addr_zip: str = ""


# ---------------------------------------------------------------------------
# API Routes: Status & Health
# ---------------------------------------------------------------------------

@app.get("/api/status")
def get_status():
    queue = queue_io.read_queue()
    sync = _get_sync_status()
    return {
        "vendor_sync": sync,
        "queued_bills": len(queue),
        "db_ok": gnucash_db.test_connection(),
    }


@app.get("/api/db/health")
def get_db_health():
    return gnucash_db.check_db_health()


@app.post("/api/db/path")
def set_db_path(body: dict):
    path_str = body.get("path", "")
    path = Path(path_str)
    if not path.exists() or not path.suffix == ".gnucash":
        raise HTTPException(status_code=400, detail="Invalid .gnucash file path")
    settings.gnucash_db_path = path
    return {"ok": True}


@app.get("/api/db/browse")
def browse_db():
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import tkinter as tk; from tkinter import filedialog; "
             "root = tk.Tk(); root.withdraw(); "
             "p = filedialog.askopenfilename(filetypes=[('GnuCash', '*.gnucash')]); "
             "print(p)"],
            capture_output=True, text=True, timeout=60,
        )
        path = result.stdout.strip()
        return {"path": path}
    except Exception as e:
        return {"path": "", "error": str(e)}


# ---------------------------------------------------------------------------
# API Routes: Bills Queue
# ---------------------------------------------------------------------------

@app.get("/api/bills")
def get_bills():
    queue = queue_io.read_queue()
    return [_serialize_bill(b) for b in queue]


@app.post("/api/bills", status_code=201)
def add_bill(bill: BillIn):
    if not bill.vendor_name.strip():
        raise HTTPException(status_code=422, detail="Vendor name is required")
    if bill.amount <= 0:
        raise HTTPException(status_code=422, detail="Amount must be greater than zero")
    try:
        parsed_date = date.fromisoformat(bill.bill_date) if bill.bill_date else date.today()
    except ValueError:
        parsed_date = date.today()
    queue_io.add_bill(bill.vendor_name, bill.amount, bill.memo, parsed_date, bill.check_number)
    return {"ok": True}


@app.put("/api/bills/{index}")
def update_bill(index: int, bill: BillIn):
    if not bill.vendor_name.strip():
        raise HTTPException(status_code=422, detail="Vendor name is required")
    if bill.amount <= 0:
        raise HTTPException(status_code=422, detail="Amount must be greater than zero")
    try:
        parsed_date = date.fromisoformat(bill.bill_date) if bill.bill_date else date.today()
    except ValueError:
        parsed_date = date.today()
    ok = queue_io.update_bill(index, bill.vendor_name, bill.amount, bill.memo, parsed_date, bill.check_number)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Bill at index {index} not found")
    return {"ok": True}


@app.delete("/api/bills/{index}")
def delete_bill(index: int):
    ok = queue_io.remove_bill(index)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Bill at index {index} not found")
    return {"ok": True}


@app.post("/api/bills/{index}/post")
def post_one_bill(index: int):
    queue = queue_io.read_queue()
    bill = next((b for b in queue if b["_index"] == index), None)
    if not bill:
        raise HTTPException(status_code=404, detail=f"Bill at index {index} not found")
    result = _process_one_bill(bill)
    if result["ok"]:
        queue_io.remove_bill(index)
    return result


@app.post("/api/bills/post-all")
def post_all_bills():
    queue = queue_io.read_queue()
    succeeded = []
    failed = []
    for bill in sorted(queue, key=lambda b: b["_index"], reverse=True):
        result = _process_one_bill(bill)
        if result["ok"]:
            queue_io.remove_bill(bill["_index"])
            succeeded.append(bill["vendor_name"])
        else:
            failed.append({"vendor_name": bill["vendor_name"], "error": result["error"]})
    return {"ok": len(failed) == 0, "succeeded": succeeded, "failed": failed}


# ---------------------------------------------------------------------------
# API Routes: Vendors
# ---------------------------------------------------------------------------

@app.get("/api/vendors")
def get_vendors():
    vm = VendorManager()
    vendors = vm.vendors.get("vendors", {})
    aliases = vm.vendors.get("aliases", {})
    gc_guids = {v["guid"] for v in gnucash_db.get_all_vendors()}
    result = []
    for key, v in vendors.items():
        vendor_aliases = [a for a, k in aliases.items() if k == key]
        result.append({
            "key": key,
            "display_name": v.get("display_name", key),
            "gnucash_guid": v.get("gnucash_guid", ""),
            "synced": v.get("gnucash_guid", "") in gc_guids,
            "aliases": vendor_aliases,
            "addr_line1": v.get("addr_line1", ""),
            "addr_city": v.get("addr_city", ""),
            "addr_state": v.get("addr_state", ""),
            "addr_zip": v.get("addr_zip", ""),
        })
    return sorted(result, key=lambda v: v["display_name"].lower())


@app.post("/api/vendors", status_code=201)
def create_vendor(body: VendorIn):
    from bill_processor.utils import strip_vendor_name
    display = (body.display_name or body.vendor_name).strip()
    if not display:
        raise HTTPException(status_code=422, detail="Vendor name is required")
    city_state_zip = ", ".join(filter(None, [body.addr_city, " ".join(filter(None, [body.addr_state, body.addr_zip]))]))
    try:
        guid = gnucash_db.create_vendor(
            name=display,
            addr_name=display,
            addr_addr1=body.addr_line1,
            addr_addr2=city_state_zip,
        )
        vm = VendorManager()
        key = strip_vendor_name(display)
        vm.vendors["vendors"][key] = {
            "display_name": display,
            "gnucash_guid": guid,
            "addr_line1": body.addr_line1,
            "addr_city": body.addr_city,
            "addr_state": body.addr_state,
            "addr_zip": body.addr_zip,
        }
        vm.save()
        return {"ok": True, "key": key, "guid": guid}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.put("/api/vendors/{key}")
def update_vendor(key: str, body: VendorUpdate):
    vm = VendorManager()
    vendors = vm.vendors.get("vendors", {})
    if key not in vendors:
        raise HTTPException(status_code=404, detail=f"Vendor '{key}' not found")
    v = vendors[key]
    if body.display_name is not None:
        v["display_name"] = body.display_name
    for field in ("addr_line1", "addr_city", "addr_state", "addr_zip"):
        val = getattr(body, field)
        if val is not None:
            v[field] = val
    if body.aliases is not None:
        existing_aliases = vm.vendors.get("aliases", {})
        # Remove old aliases for this key
        vm.vendors["aliases"] = {a: k for a, k in existing_aliases.items() if k != key}
        # Add new ones
        for alias in body.aliases:
            vm.vendors["aliases"][alias.lower()] = key
    vm.save()
    return {"ok": True}


@app.post("/api/vendors/sync-all")
def sync_all_vendors():
    try:
        sync = VendorSyncUtility()
        if not sync.discover_schema():
            return {"ok": False, "error": "Schema discovery failed"}
        sync.sync_gnucash_to_json()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/vendors/{key}/sync")
def sync_one_vendor(key: str):
    try:
        sync = VendorSyncUtility()
        if not sync.discover_schema():
            return {"ok": False, "error": "Schema discovery failed"}
        sync.sync_gnucash_to_json()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/vendors/search")
def vendor_search(q: str = ""):
    if not q.strip():
        return {"results": []}
    vm = VendorManager()
    vendors = vm.vendors.get("vendors", {})
    # fuzzy_match_vendor returns (best_key, best_score, close_matches)
    # close_matches is a list of (vendor_key, score) tuples
    best_key, best_score, close_matches = fuzzy_match_vendor(
        q, vm.vendors, threshold=VENDOR_SEARCH_MIN_SCORE
    )
    results = []
    seen = set()
    for vendor_key, score in close_matches:
        if vendor_key not in seen and vendor_key in vendors:
            seen.add(vendor_key)
            results.append({
                "key": vendor_key,
                "display_name": vendors[vendor_key].get("display_name", vendor_key),
            })
    # Include best match if not already in results
    if best_key and best_key not in seen and best_key in vendors:
        results.insert(0, {
            "key": best_key,
            "display_name": vendors[best_key].get("display_name", best_key),
        })
    return {"results": results}


@app.post("/api/vendors/lookup-address")
def lookup_address(body: AddressLookupIn):
    name = body.display_name or body.vendor_name
    parts = [p for p in [name, body.addr_city, body.addr_zip] if p]
    query = " ".join(parts)
    candidates = addr_lookup.lookup_google_places(query) or addr_lookup.lookup_openstreetmap(query)
    return {"candidates": candidates, "message": f"Found {len(candidates)} result(s)"}


@app.get("/api/vendors/search-candidates")
def vendor_search_candidates(name: str = "", city: str = "", zip: str = ""):
    parts = [p for p in [name, city, zip] if p.strip()]
    if not parts:
        return {"candidates": []}
    query = " ".join(parts)
    raw = addr_lookup.lookup_google_places(query, return_all=True) or \
          addr_lookup.lookup_openstreetmap(query, return_all=True)
    if not raw:
        return {"candidates": []}
    return {
        "candidates": [
            {
                "display_name": r.get("name", ""),
                "addr_line1": r.get("addr_line1", ""),
                "addr_city": r.get("city", ""),
                "addr_state": r.get("state", ""),
                "addr_zip": r.get("zip", ""),
            }
            for r in raw
        ]
    }


# ---------------------------------------------------------------------------
# API Routes: Accounts & Memos
# ---------------------------------------------------------------------------

@app.get("/api/accounts")
def get_all_accounts():
    return gnucash_db.get_cash_accounts()


@app.get("/api/accounts/cash")
def get_cash_accounts():
    return _get_enabled_cash_accounts()


@app.get("/api/accounts/validate")
def validate_account(name: str = ""):
    if not name.strip():
        return {"valid": False, "guid": None}
    accounts = gnucash_db.get_cash_accounts()
    match = next((a for a in accounts if a["name"].lower() == name.strip().lower()), None)
    return {"valid": match is not None, "guid": match["guid"] if match else None}


@app.get("/api/memos")
def get_memos(q: str = ""):
    suggestions = cash_io.get_memo_suggestions(q)
    return {"suggestions": suggestions}


# ---------------------------------------------------------------------------
# API Routes: Cash Entry
# ---------------------------------------------------------------------------

@app.post("/api/cash/submit")
def cash_submit(body: CashSubmitIn):
    if not body.entries:
        raise HTTPException(status_code=422, detail="At least one line item is required")
    try:
        entry_date = date.fromisoformat(body.entry_date)
    except ValueError:
        entry_date = date.today()

    result = {}
    try:
        account_guids = [e.account_guid for e in body.entries]
        memos = [e.memo for e in body.entries]
        amounts = [e.amount for e in body.entries]
        batch_guid = gnucash_db.create_cash_entry(
            entry_date=entry_date,
            account_guids=account_guids,
            memos=memos,
            amounts=amounts,
        )
        for memo in memos:
            if memo.strip():
                cash_io.save_memo_to_history(memo)
        total = sum(amounts)
        result["batch"] = {"ok": True, "guid": batch_guid, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if body.deposit_account_guid and body.deposit_amount:
        try:
            dep_date = date.fromisoformat(body.deposit_date) if body.deposit_date else entry_date
            dep_guid = gnucash_db.create_cash_deposit(
                deposit_date=dep_date,
                bank_account_guid=body.deposit_account_guid,
                amount=body.deposit_amount,
            )
            result["deposit"] = {"ok": True, "guid": dep_guid}
        except Exception as e:
            result["deposit"] = {"ok": False, "error": str(e)}

    return result


@app.post("/api/cash/deposit")
def cash_deposit(body: DepositIn):
    try:
        entry_date = date.fromisoformat(body.entry_date)
    except ValueError:
        entry_date = date.today()
    try:
        guid = gnucash_db.create_cash_deposit(
            deposit_date=entry_date,
            bank_account_guid=body.account_guid,
            amount=body.amount,
        )
        return {"ok": True, "guid": guid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API Routes: Settings
# ---------------------------------------------------------------------------

@app.get("/api/settings")
def get_settings():
    return {
        "ap_account_guid": settings.ap_account_guid,
        "ap_account_name": _account_name(settings.ap_account_guid),
        "checking_account_guid": settings.checking_account_guid,
        "checking_account_name": _account_name(settings.checking_account_guid),
        "expense_account_guid": settings.expense_account_guid,
        "expense_account_name": _account_name(settings.expense_account_guid),
        "cash_on_hand_account_name": settings.get("cash_on_hand_account_name"),
        "locality_city": settings.locality_city,
        "locality_state": settings.locality_state,
        "home_latitude": settings.get("home_latitude"),
        "home_longitude": settings.get("home_longitude"),
        "search_radius_miles": settings.get("search_radius_miles"),
        "fuzzy_match_threshold": settings.fuzzy_match_threshold,
        "fuzzy_ambiguous_threshold": settings.get("fuzzy_ambiguous_threshold"),
        "enabled_cash_account_guids": settings.get("enabled_cash_account_guids", []),
        "gnucash_db_path": str(settings.gnucash_db_path),
        "processing_accounts_configured": settings.processing_accounts_configured,
    }


@app.put("/api/settings")
def update_settings(body: SettingsUpdate):
    changed = body.model_dump(exclude_none=True)
    for key, value in changed.items():
        if key == "gnucash_db_path":
            settings.gnucash_db_path = Path(value)
        else:
            settings.set(key, value)
    return {"ok": True}


# ---------------------------------------------------------------------------
# API Routes: Shutdown
# ---------------------------------------------------------------------------

@app.post("/api/shutdown")
def shutdown():
    def _stop():
        time.sleep(0.3)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_stop, daemon=True).start()
    return {"ok": True, "message": "Server shutting down"}


# ---------------------------------------------------------------------------
# SPA fallback — must be last
# ---------------------------------------------------------------------------

@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    # Serve static assets from dist/ if they exist as actual files
    candidate = FRONTEND_DIST / full_path
    if candidate.exists() and candidate.is_file():
        return FileResponse(str(candidate))
    # Fall back to index.html for all other paths (React Router handles routing)
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse(
        {"error": "Frontend not built. Run: cd frontend && npm run build"},
        status_code=503,
    )

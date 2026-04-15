# React Frontend Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the HTMX + Jinja2 web interface with a React + Vite SPA backed by a clean FastAPI REST API, keeping `gnucash_db.py` and all data-layer code untouched.

**Architecture:** FastAPI serves `/api/*` JSON endpoints and falls back to serving `frontend/dist/index.html` for all other routes. The React SPA uses React Router for navigation, React Query for server state, and shadcn/ui for components. `_process_one_bill()` and other internal helpers in `web/app.py` are preserved unchanged.

**Tech Stack:** Python/FastAPI (backend), React 18 + Vite + TypeScript + shadcn/ui + React Query + React Router (frontend)

> **Note:** Phase 1 (Tasks 1–6) is independently shippable — it produces a fully-tested JSON API with no frontend dependency. Phase 2 (Tasks 7–15) builds the React app on top.

---

## File Map

**Modified:**
- `web/app.py` — strip all Jinja2/HTMX routes; add `/api/*` JSON routes; add SPA fallback
- `tests/test_web_app.py` — rewrite route tests for JSON; keep `TestFormatBillLine` and `TestProcessOneBill` unchanged
- `tests/test_cash_web.py` — rewrite for JSON responses; remove HTMX-specific tests
- `.gitignore` — add `frontend/dist/` and `frontend/node_modules/`
- `GnuCash Bills.bat` — update health-check URL; add `npm run build` step

**Created:**
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/index.html`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/components/Layout.tsx`
- `frontend/src/components/Sidebar.tsx`
- `frontend/src/components/DbUnavailable.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/api/bills.ts`
- `frontend/src/api/cash.ts`
- `frontend/src/api/vendors.ts`
- `frontend/src/api/accounts.ts`
- `frontend/src/api/settings.ts`
- `frontend/src/pages/BillsQueue.tsx`
- `frontend/src/pages/CashEntry.tsx`
- `frontend/src/pages/Vendors.tsx`
- `frontend/src/pages/Settings.tsx`

**Deleted:**
- `web/templates/` (entire directory)
- `bill_entry_gui.py`
- `vendor_manager_gui.py`

---

## Phase 1: REST API

### Task 1: Commit current uncommitted changes

**Files:**
- Modify: `gnucash_db.py` (already modified, needs commit)
- Modify: `tests/test_get_cash_accounts.py` (already modified, needs commit)

- [ ] **Step 1: Verify tests pass**

```
uv run pytest tests/test_get_cash_accounts.py -v
```
Expected: all tests pass including `test_returns_bank_accounts` and `test_queries_income_asset_cash_and_bank_types`.

- [ ] **Step 2: Commit**

```bash
git add gnucash_db.py tests/test_get_cash_accounts.py
git commit -m "feat: expand get_cash_accounts to include BANK and CASH account types"
```

---

### Task 2: Update .gitignore

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add frontend build artifacts**

Append to `.gitignore`:
```
# React frontend build artifacts
frontend/dist/
frontend/node_modules/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: ignore frontend build artifacts"
```

---

### Task 3: Rewrite web/app.py as REST API

**Files:**
- Modify: `web/app.py`

- [ ] **Step 1: Write the new app.py**

Replace the entire contents of `web/app.py` with:

```python
"""FastAPI REST API for GnuCash Bill Processor."""
import os
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

from bill_processor import gnucash_db, config, logging_setup
from bill_processor.settings_manager import settings
import bill_processor.address_lookup as addr_lookup
from bill_processor.utils import parse_input_line, fuzzy_match_vendor
from bill_processor.vendor_manager import VendorManager
from bill_processor.vendor_sync import VendorSyncUtility
from bill_processor.web import queue_io, cash_io

BASE_DIR = Path(__file__).parent
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
CONFIG_FILE_PATH = BASE_DIR.parent / "config.py"

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
        return {"ok": False, "error": "Vendor name is required"}
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
    matches = fuzzy_match_vendor(q, vm.vendors, min_score=VENDOR_SEARCH_MIN_SCORE)
    return {"results": [{"key": k, "display_name": v.get("display_name", k)} for k, v in matches]}


@app.post("/api/vendors/lookup-address")
def lookup_address(body: AddressLookupIn):
    name = body.display_name or body.vendor_name
    parts = [p for p in [name, body.addr_city, body.addr_zip] if p]
    query = " ".join(parts)
    candidates = addr_lookup.lookup_google_places(query) or addr_lookup.lookup_openstreetmap(query)
    return {"candidates": candidates, "message": f"Found {len(candidates)} result(s)"}


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
                entry_date=dep_date,
                account_guid=body.deposit_account_guid,
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
            entry_date=entry_date,
            account_guid=body.account_guid,
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
        "cash_on_hand_account_name": settings.cash_on_hand_account_name,
        "locality_city": settings.locality_city,
        "locality_state": settings.locality_state,
        "home_latitude": settings.home_latitude,
        "home_longitude": settings.home_longitude,
        "search_radius_miles": settings.search_radius_miles,
        "fuzzy_match_threshold": settings.fuzzy_match_threshold,
        "fuzzy_ambiguous_threshold": settings.fuzzy_ambiguous_threshold,
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
        os.kill(os.getpid(), 15)
    threading.Thread(target=_stop, daemon=True).start()
    return {"ok": True, "message": "Server shutting down"}


# ---------------------------------------------------------------------------
# SPA fallback — must be last
# ---------------------------------------------------------------------------

if FRONTEND_DIST.exists():
    _assets_dir = FRONTEND_DIST / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse(
        {"error": "Frontend not built. Run: cd frontend && npm run build"},
        status_code=503,
    )
```

- [ ] **Step 2: Verify the app imports without error**

```
uv run python -c "from bill_processor.web.app import app; print('OK')"
```
Expected: `OK`

---

### Task 4: Rewrite test_web_app.py

**Files:**
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Replace the file**

Replace `tests/test_web_app.py` with:

```python
"""Tests for the FastAPI REST API."""
import tempfile
import os
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from bill_processor.web.app import app
    return TestClient(app)


@pytest.fixture
def tmp_queue(tmp_path, monkeypatch):
    queue_file = tmp_path / "bills_to_process.txt"
    queue_file.write_text("")
    from bill_processor import config
    monkeypatch.setattr(config, "BILLS_INPUT_PATH", queue_file)
    return queue_file


@pytest.fixture
def isolated_settings(monkeypatch):
    from bill_processor import settings_manager
    from bill_processor.web import app as web_app
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name
    try:
        fresh = settings_manager.SettingsManager(settings_file=Path(tmp_path))
        monkeypatch.setattr(web_app, "settings", fresh)
        yield fresh
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Status & Health
# ---------------------------------------------------------------------------

def test_status_returns_ok(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "vendor_sync" in data
    assert "queued_bills" in data


def test_db_health_returns_status(client):
    response = client.get("/api/db/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data


# ---------------------------------------------------------------------------
# Bills queue CRUD
# ---------------------------------------------------------------------------

def test_get_bills_returns_list(client, tmp_queue):
    response = client.get("/api/bills")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_add_bill_to_queue(client, tmp_queue):
    response = client.post("/api/bills", json={
        "vendor_name": "Acme Electric",
        "amount": 123.45,
        "memo": "Test bill",
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 201
    assert response.json()["ok"] is True
    assert "Acme Electric" in tmp_queue.read_text()
    assert "123.45" in tmp_queue.read_text()


def test_add_bill_with_check_number(client, tmp_queue):
    response = client.post("/api/bills", json={
        "vendor_name": "Acme Electric",
        "amount": 123.45,
        "memo": "Test bill",
        "bill_date": "2026-03-01",
        "check_number": "1042",
    })
    assert response.status_code == 201
    assert "1042" in tmp_queue.read_text()


def test_add_bill_without_check_number_omits_fifth_field(client, tmp_queue):
    response = client.post("/api/bills", json={
        "vendor_name": "Acme Electric",
        "amount": 123.45,
        "memo": "Test bill",
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 201
    assert tmp_queue.read_text().strip().endswith("2026-03-01")


def test_add_bill_empty_name_returns_422(client, tmp_queue):
    response = client.post("/api/bills", json={
        "vendor_name": "",
        "amount": 100.00,
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 422


def test_delete_bill_from_queue(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
    response = client.delete("/api/bills/0")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert tmp_queue.read_text().strip() == ""


def test_update_bill_in_queue(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
    response = client.put("/api/bills/0", json={
        "vendor_name": "Acme Electric",
        "amount": 200.00,
        "memo": "Updated",
        "bill_date": "2026-03-01",
    })
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "200.0" in tmp_queue.read_text()


def test_update_bill_adds_check_number(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
    response = client.put("/api/bills/0", json={
        "vendor_name": "Acme Electric",
        "amount": 123.45,
        "memo": "test",
        "bill_date": "2026-03-01",
        "check_number": "2001",
    })
    assert response.status_code == 200
    assert "2001" in tmp_queue.read_text()


def test_update_bill_clears_check_number(client, tmp_queue):
    tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01, 1042\n")
    response = client.put("/api/bills/0", json={
        "vendor_name": "Acme Electric",
        "amount": 123.45,
        "memo": "test",
        "bill_date": "2026-03-01",
        "check_number": "",
    })
    assert response.status_code == 200
    content = tmp_queue.read_text().strip()
    assert "1042" not in content
    assert content.endswith("2026-03-01")


# ---------------------------------------------------------------------------
# Bill processing
# ---------------------------------------------------------------------------

def test_create_vendor_empty_name_returns_error(client):
    response = client.post("/api/vendors", json={"vendor_name": "", "display_name": ""})
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "required" in data["error"].lower()


def test_process_single_missing_index_returns_404(client, tmp_queue):
    response = client.post("/api/bills/99/post")
    assert response.status_code == 404


def test_post_all_empty_queue_returns_ok(client, tmp_queue):
    response = client.post("/api/bills/post-all")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["succeeded"] == []
    assert data["failed"] == []


# ---------------------------------------------------------------------------
# TestFormatBillLine — unchanged; tests queue_io helper directly
# ---------------------------------------------------------------------------

class TestFormatBillLine:
    def test_with_check_number_appends_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15), "1042")
        assert result == "Acme Electric, 150.50, memo, 2026-03-15, 1042\n"

    def test_without_check_number_omits_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15))
        assert result == "Acme Electric, 150.50, memo, 2026-03-15\n"

    def test_empty_check_number_omits_fifth_field(self):
        from bill_processor.web.queue_io import _format_bill_line
        result = _format_bill_line("Acme Electric", 150.50, "memo", date(2026, 3, 15), "")
        assert result == "Acme Electric, 150.50, memo, 2026-03-15\n"


# ---------------------------------------------------------------------------
# TestProcessOneBill — unchanged; tests internal helper directly
# ---------------------------------------------------------------------------

class TestProcessOneBill:
    VENDOR_GUID = "a" * 32
    EXPENSE_GUID = "b" * 32
    CHECKING_GUID = "c" * 32
    BILL_GUID = "d" * 32

    def _bill(self, check_number=""):
        return {
            "vendor_name": "Acme Electric",
            "amount": 123.45,
            "memo": "electric bill",
            "date": date(2026, 3, 1),
            "check_number": check_number,
            "_index": 0,
            "_raw": "Acme Electric, 123.45, electric bill, 2026-03-01",
        }

    def _good_vendor(self):
        return {"gnucash_guid": self.VENDOR_GUID, "display_name": "Acme Electric"}

    def _patch_gnucash(self, monkeypatch, web_app):
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setitem(web_app.settings._settings, "expense_account_guid", self.EXPENSE_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "post_bill", lambda **kw: None)
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", lambda **kw: "pay_guid")

    def test_success_returns_ok(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        self._patch_gnucash(monkeypatch, web_app)
        result = web_app._process_one_bill(self._bill())
        assert result == {"ok": True}

    def test_vendor_not_found_returns_error(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (None, "not_found")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "Acme Electric" in result["error"]

    def test_no_expense_account_returns_error(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setitem(web_app.settings._settings, "expense_account_guid", None)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "expense account" in result["error"].lower()

    def test_gnucash_exception_returns_error(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setitem(web_app.settings._settings, "expense_account_guid", self.EXPENSE_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Test Account", "guid": guid})
        def fail(**kw):
            raise ValueError("DB locked")
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", fail)
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "DB locked" in result["error"]

    def test_check_number_forwarded_to_pay_bill(self, monkeypatch):
        from bill_processor.web import app as web_app
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        self._patch_gnucash(monkeypatch, web_app)
        captured = {}
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", lambda **kw: captured.update(kw) or "pay_guid")
        web_app._process_one_bill(self._bill(check_number="1042"))
        assert captured.get("check_number") == "1042"

    def test_uses_configured_ap_account_guid(self, monkeypatch):
        from bill_processor.web import app as web_app
        AP_GUID = "e" * 32
        mock_vm = MagicMock()
        mock_vm.find_vendor.return_value = (self._good_vendor(), "exact")
        monkeypatch.setattr(web_app, "VendorManager", lambda: mock_vm)
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Accounts Payable", "guid": guid})
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", AP_GUID)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        monkeypatch.setitem(web_app.settings._settings, "expense_account_guid", self.EXPENSE_GUID)
        captured = {}
        monkeypatch.setattr(web_app.gnucash_db, "create_bill", lambda **kw: self.BILL_GUID)
        monkeypatch.setattr(web_app.gnucash_db, "post_bill", lambda **kw: captured.update(kw))
        monkeypatch.setattr(web_app.gnucash_db, "pay_bill", lambda **kw: "pay_guid")
        web_app._process_one_bill(self._bill())
        assert captured.get("ap_account_guid") == AP_GUID

    def test_blocks_when_ap_account_not_configured(self, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", None)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", self.CHECKING_GUID)
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "Processing accounts not configured" in result["error"]

    def test_blocks_when_checking_account_not_configured(self, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setitem(web_app.settings._settings, "ap_account_guid", "e" * 32)
        monkeypatch.setitem(web_app.settings._settings, "checking_account_guid", None)
        result = web_app._process_one_bill(self._bill())
        assert result["ok"] is False
        assert "Processing accounts not configured" in result["error"]


# ---------------------------------------------------------------------------
# TestProcessQueueRoutes — queue manipulation logic unchanged; response is JSON
# ---------------------------------------------------------------------------

class TestProcessQueueRoutes:

    def test_process_single_success_removes_bill(self, client, tmp_queue, monkeypatch):
        from bill_processor.web import app as web_app
        tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
        monkeypatch.setattr(web_app, "_process_one_bill", lambda bill: {"ok": True})
        response = client.post("/api/bills/0/post")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert tmp_queue.read_text().strip() == ""

    def test_process_single_failure_keeps_bill(self, client, tmp_queue, monkeypatch):
        from bill_processor.web import app as web_app
        tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
        monkeypatch.setattr(web_app, "_process_one_bill",
                            lambda bill: {"ok": False, "error": "Vendor not found"})
        response = client.post("/api/bills/0/post")
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert "Acme Electric" in tmp_queue.read_text()

    def test_process_single_failure_returns_error_message(self, client, tmp_queue, monkeypatch):
        from bill_processor.web import app as web_app
        tmp_queue.write_text("Acme Electric, 123.45, test, 2026-03-01\n")
        monkeypatch.setattr(web_app, "_process_one_bill",
                            lambda bill: {"ok": False, "error": "DB locked"})
        response = client.post("/api/bills/0/post")
        assert response.status_code == 200
        assert "DB locked" in response.json()["error"]

    def test_process_all_success_clears_queue(self, client, tmp_queue, monkeypatch):
        from bill_processor.web import app as web_app
        tmp_queue.write_text(
            "Acme Electric, 123.45, test, 2026-03-01\n"
            "Bob Plumbing, 200.00, repair, 2026-03-02\n"
        )
        monkeypatch.setattr(web_app, "_process_one_bill", lambda bill: {"ok": True})
        response = client.post("/api/bills/post-all")
        assert response.status_code == 200
        assert tmp_queue.read_text().strip() == ""
        data = response.json()
        assert len(data["succeeded"]) == 2
        assert data["failed"] == []

    def test_process_all_partial_failure_keeps_failed_bills(self, client, tmp_queue, monkeypatch):
        from bill_processor.web import app as web_app
        tmp_queue.write_text(
            "Acme Electric, 123.45, test, 2026-03-01\n"
            "Unknown Vendor, 50.00, misc, 2026-03-02\n"
        )
        def selective(bill):
            return {"ok": True} if bill["vendor_name"] == "Acme Electric" else {"ok": False, "error": "Vendor not found"}
        monkeypatch.setattr(web_app, "_process_one_bill", selective)
        response = client.post("/api/bills/post-all")
        assert response.status_code == 200
        remaining = tmp_queue.read_text()
        assert "Acme Electric" not in remaining
        assert "Unknown Vendor" in remaining
        data = response.json()
        assert "Acme Electric" in data["succeeded"]
        assert any(f["vendor_name"] == "Unknown Vendor" for f in data["failed"])


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class TestSettings:
    AP_GUID = "e" * 32
    CHECKING_GUID = "c" * 32

    def test_get_settings_returns_dict(self, client, isolated_settings):
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert "ap_account_guid" in data
        assert "checking_account_guid" in data

    def test_put_ap_account_guid_persists(self, client, isolated_settings, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "AP", "guid": guid})
        response = client.put("/api/settings", json={"ap_account_guid": self.AP_GUID})
        assert response.status_code == 200
        assert isolated_settings.ap_account_guid == self.AP_GUID

    def test_put_checking_account_guid_persists(self, client, isolated_settings, monkeypatch):
        from bill_processor.web import app as web_app
        monkeypatch.setattr(web_app.gnucash_db, "get_account_by_guid",
                            lambda guid: {"name": "Checking", "guid": guid})
        response = client.put("/api/settings", json={"checking_account_guid": self.CHECKING_GUID})
        assert response.status_code == 200
        assert isolated_settings.checking_account_guid == self.CHECKING_GUID
```

- [ ] **Step 2: Run the tests**

```
uv run pytest tests/test_web_app.py -v
```
Expected: all tests pass. Fix any failures before proceeding.

---

### Task 5: Rewrite test_cash_web.py

**Files:**
- Modify: `tests/test_cash_web.py`

- [ ] **Step 1: Replace the file**

```python
"""Tests for cash API routes in web/app.py."""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from bill_processor.web.app import app

client = TestClient(app)


class TestMemoSearch:
    def test_returns_200(self):
        response = client.get("/api/memos?q=ali")
        assert response.status_code == 200

    def test_empty_query_returns_suggestions_key(self):
        with patch("bill_processor.web.cash_io.get_memo_suggestions", return_value=[]):
            response = client.get("/api/memos?q=")
        assert response.json() == {"suggestions": []}

    def test_returns_matching_memos(self):
        with patch("bill_processor.web.cash_io.get_memo_suggestions", return_value=["Alice", "Albert"]):
            response = client.get("/api/memos?q=al")
        data = response.json()
        assert "Alice" in data["suggestions"] or "Albert" in data["suggestions"]


class TestCashSubmit:
    def test_empty_entries_returns_422(self):
        response = client.post("/api/cash/submit", json={
            "entry_date": "2026-03-09",
            "entries": [],
        })
        assert response.status_code == 422

    def test_valid_submission_returns_batch_result(self):
        with patch("bill_processor.gnucash_db.create_cash_entry", return_value="z" * 32):
            response = client.post("/api/cash/submit", json={
                "entry_date": "2026-03-09",
                "entries": [{"account_guid": "a" * 32, "memo": "Alice", "amount": 100.0}],
            })
        assert response.status_code == 200
        data = response.json()
        assert data["batch"]["ok"] is True
        assert data["batch"]["total"] == 100.0

    def test_locked_db_returns_500(self):
        with patch("bill_processor.gnucash_db.create_cash_entry",
                   side_effect=RuntimeError("GnuCash database is locked")):
            response = client.post("/api/cash/submit", json={
                "entry_date": "2026-03-09",
                "entries": [{"account_guid": "a" * 32, "memo": "Alice", "amount": 100.0}],
            })
        assert response.status_code == 500
        assert "locked" in response.json()["detail"].lower()

    def test_deposit_failure_included_in_response(self):
        with patch("bill_processor.gnucash_db.create_cash_entry", return_value="z" * 32), \
             patch("bill_processor.gnucash_db.create_cash_deposit",
                   side_effect=RuntimeError("DB locked")):
            response = client.post("/api/cash/submit", json={
                "entry_date": "2026-03-09",
                "entries": [{"account_guid": "a" * 32, "memo": "Alice", "amount": 50.0}],
                "deposit_account_guid": "b" * 32,
                "deposit_amount": 30.0,
                "deposit_date": "2026-03-10",
            })
        assert response.status_code == 200
        data = response.json()
        assert data["batch"]["ok"] is True
        assert data["deposit"]["ok"] is False
        assert "locked" in data["deposit"]["error"].lower()

    def test_deposit_success_included_in_response(self):
        with patch("bill_processor.gnucash_db.create_cash_entry", return_value="z" * 32), \
             patch("bill_processor.gnucash_db.create_cash_deposit", return_value="y" * 32):
            response = client.post("/api/cash/submit", json={
                "entry_date": "2026-03-09",
                "entries": [{"account_guid": "a" * 32, "memo": "Alice", "amount": 50.0}],
                "deposit_account_guid": "b" * 32,
                "deposit_amount": 30.0,
                "deposit_date": "2026-03-10",
            })
        assert response.status_code == 200
        data = response.json()
        assert data["batch"]["ok"] is True
        assert data["deposit"]["ok"] is True


class TestAddressLookup:
    def test_returns_candidates_and_message(self):
        response = client.post("/api/vendors/lookup-address", json={"vendor_name": "Acme Electric"})
        assert response.status_code == 200
        data = response.json()
        assert "candidates" in data
        assert "message" in data
        assert isinstance(data["candidates"], list)

    def test_combines_city_and_zip_in_query(self, monkeypatch):
        import bill_processor.web.app as web_app
        captured = []
        monkeypatch.setattr(web_app.addr_lookup, "lookup_google_places",
                            lambda q, **kw: captured.append(q) or [])
        monkeypatch.setattr(web_app.addr_lookup, "lookup_openstreetmap",
                            lambda q, **kw: [])
        client.post("/api/vendors/lookup-address", json={
            "display_name": "Kroger",
            "addr_city": "Cincinnati",
            "addr_zip": "45202",
        })
        assert captured == ["Kroger Cincinnati 45202"]

    def test_skips_empty_refinement_fields(self, monkeypatch):
        import bill_processor.web.app as web_app
        captured = []
        monkeypatch.setattr(web_app.addr_lookup, "lookup_google_places",
                            lambda q, **kw: captured.append(q) or [])
        monkeypatch.setattr(web_app.addr_lookup, "lookup_openstreetmap",
                            lambda q, **kw: [])
        client.post("/api/vendors/lookup-address", json={
            "display_name": "Kroger",
            "addr_city": "",
            "addr_zip": "45202",
        })
        assert captured == ["Kroger 45202"]
```

- [ ] **Step 2: Run the tests**

```
uv run pytest tests/test_cash_web.py -v
```
Expected: all tests pass.

---

### Task 6: Run full test suite and commit API layer

**Files:** none

- [ ] **Step 1: Run all tests**

```
uv run pytest tests/ -v
```
Expected: all tests pass. The only failures allowed are in `test_web_app.py` or `test_cash_web.py` — fix those before continuing. Other test files must not regress.

- [ ] **Step 2: Commit**

```bash
git add web/app.py tests/test_web_app.py tests/test_cash_web.py
git commit -m "refactor: replace HTMX routes with clean JSON REST API under /api/"
```

---

## Phase 2: React Frontend

### Task 7: Scaffold React + Vite + shadcn/ui project

**Files:**
- Create: `frontend/` (entire Vite project)

- [ ] **Step 1: Create the Vite project**

Run from the project root:
```
npm create vite@latest frontend -- --template react-ts
```

- [ ] **Step 2: Install base dependencies**

```
cd frontend
npm install
npm install react-router-dom @tanstack/react-query axios
```

- [ ] **Step 3: Install Tailwind (required by shadcn/ui)**

```
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

- [ ] **Step 4: Configure tailwind.config.js**

Replace `frontend/tailwind.config.js` with:
```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
}
```

- [ ] **Step 5: Add Tailwind to CSS**

Replace `frontend/src/index.css` with:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 6: Init shadcn/ui**

```
npx shadcn@latest init
```
When prompted: style = Default, base color = Slate, CSS variables = yes.

- [ ] **Step 7: Add required shadcn components**

```
npx shadcn@latest add button input table select toast badge dialog
```

- [ ] **Step 8: Configure Vite proxy**

Replace `frontend/vite.config.ts` with:
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      '/api': 'http://localhost:7432',
    },
  },
})
```

- [ ] **Step 9: Verify dev server starts**

In one terminal: `uv run uvicorn bill_processor.web.app:app --port 7432`

In another: `cd frontend && npm run dev`

Expected: Vite dev server starts at http://localhost:5173 with no errors.

- [ ] **Step 10: Commit scaffold**

From the project root:
```bash
git add frontend/
git commit -m "feat: scaffold React + Vite + shadcn/ui frontend"
```

---

### Task 8: Layout, Sidebar, and routing skeleton

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/components/Layout.tsx`
- Create: `frontend/src/components/Sidebar.tsx`
- Create: `frontend/src/components/DbUnavailable.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Create API client**

Create `frontend/src/api/client.ts`:
```ts
import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export default api

export async function apiFetch<T>(url: string): Promise<T> {
  const res = await api.get<T>(url)
  return res.data
}
```

- [ ] **Step 2: Create Sidebar**

Create `frontend/src/components/Sidebar.tsx`:
```tsx
import { NavLink } from 'react-router-dom'

const links = [
  { to: '/bills', label: 'Bills Queue' },
  { to: '/cash', label: 'Cash Entry' },
  { to: '/vendors', label: 'Vendors' },
  { to: '/settings', label: 'Settings' },
]

export default function Sidebar() {
  return (
    <aside className="w-48 min-h-screen bg-slate-900 text-slate-300 flex flex-col">
      <div className="p-4 font-semibold text-white text-sm border-b border-slate-700">
        GnuCash Bills
      </div>
      <nav className="flex flex-col gap-1 p-2 flex-1">
        {links.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `px-3 py-2 rounded text-sm transition-colors ${
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'hover:bg-slate-700 hover:text-white'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
```

- [ ] **Step 3: Create Layout**

Create `frontend/src/components/Layout.tsx`:
```tsx
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'

export default function Layout() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <main className="flex-1 p-6 bg-slate-50 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
```

- [ ] **Step 4: Create DbUnavailable**

Create `frontend/src/components/DbUnavailable.tsx`:
```tsx
interface Props { error: string }

export default function DbUnavailable({ error }: Props) {
  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-50">
      <div className="bg-white border border-red-200 rounded-lg p-8 max-w-md w-full shadow">
        <h2 className="text-lg font-semibold text-red-700 mb-2">Database Unavailable</h2>
        <p className="text-slate-600 text-sm mb-4">{error}</p>
        <div className="flex gap-2">
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
          >
            Retry
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Create stub pages**

Create `frontend/src/pages/BillsQueue.tsx`:
```tsx
export default function BillsQueue() {
  return <div className="text-slate-600">Bills Queue — coming soon</div>
}
```

Create `frontend/src/pages/CashEntry.tsx`:
```tsx
export default function CashEntry() {
  return <div className="text-slate-600">Cash Entry — coming soon</div>
}
```

Create `frontend/src/pages/Vendors.tsx`:
```tsx
export default function Vendors() {
  return <div className="text-slate-600">Vendors — coming soon</div>
}
```

Create `frontend/src/pages/Settings.tsx`:
```tsx
export default function Settings() {
  return <div className="text-slate-600">Settings — coming soon</div>
}
```

- [ ] **Step 6: Wire up App.tsx**

Replace `frontend/src/App.tsx` with:
```tsx
import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Layout from './components/Layout'
import DbUnavailable from './components/DbUnavailable'
import BillsQueue from './pages/BillsQueue'
import CashEntry from './pages/CashEntry'
import Vendors from './pages/Vendors'
import Settings from './pages/Settings'
import api from './api/client'

const queryClient = new QueryClient()

function AppInner() {
  const [dbError, setDbError] = useState<string | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    api.get('/db/health').then(res => {
      if (res.data.status !== 'ok') setDbError(res.data.error || 'Database unavailable')
    }).catch(() => {
      setDbError('Could not reach server')
    }).finally(() => setChecking(false))
  }, [])

  if (checking) return null
  if (dbError) return <DbUnavailable error={dbError} />

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/bills" replace />} />
          <Route path="bills" element={<BillsQueue />} />
          <Route path="cash" element={<CashEntry />} />
          <Route path="vendors" element={<Vendors />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppInner />
    </QueryClientProvider>
  )
}
```

- [ ] **Step 7: Update main.tsx**

Replace `frontend/src/main.tsx` with:
```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

- [ ] **Step 8: Verify navigation works**

Start both servers. Open http://localhost:5173. You should see the sidebar with 4 links. Clicking each should navigate without a full page reload.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/
git commit -m "feat: add Layout, Sidebar, routing skeleton, and DB health check"
```

---

### Task 9: Bills Queue page

**Files:**
- Create: `frontend/src/api/bills.ts`
- Modify: `frontend/src/pages/BillsQueue.tsx`

- [ ] **Step 1: Create bills API module**

Create `frontend/src/api/bills.ts`:
```ts
import api from './client'

export interface Bill {
  index: number
  vendor_name: string
  amount: number
  memo: string
  date: string
  check_number: string
}

export interface BillIn {
  vendor_name: string
  amount: number
  memo?: string
  bill_date?: string
  check_number?: string
}

export const getBills = () => api.get<Bill[]>('/bills').then(r => r.data)
export const addBill = (b: BillIn) => api.post('/bills', b).then(r => r.data)
export const updateBill = (index: number, b: BillIn) => api.put(`/bills/${index}`, b).then(r => r.data)
export const deleteBill = (index: number) => api.delete(`/bills/${index}`).then(r => r.data)
export const postBill = (index: number) => api.post(`/bills/${index}/post`).then(r => r.data)
export const postAllBills = () => api.post('/bills/post-all').then(r => r.data)
```

- [ ] **Step 2: Implement BillsQueue page**

Replace `frontend/src/pages/BillsQueue.tsx` with:
```tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getBills, addBill, updateBill, deleteBill, postBill, type Bill, type BillIn } from '../api/bills'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface RowError { index: number; message: string }

type EditingRow = { mode: 'add' } | { mode: 'edit'; index: number }

const today = () => new Date().toISOString().slice(0, 10)

function BillRow({
  bill,
  onEdit,
  onDelete,
  onPost,
  error,
}: {
  bill: Bill
  onEdit: () => void
  onDelete: () => void
  onPost: () => void
  error?: string
}) {
  return (
    <>
      <tr className="border-b border-slate-100 hover:bg-slate-50">
        <td className="px-3 py-2 text-sm text-slate-800">{bill.vendor_name}</td>
        <td className="px-3 py-2 text-sm text-slate-800 text-right">${bill.amount.toFixed(2)}</td>
        <td className="px-3 py-2 text-sm text-slate-500">{bill.memo}</td>
        <td className="px-3 py-2 text-sm text-slate-500">{bill.date}</td>
        <td className="px-3 py-2 text-sm text-slate-500">{bill.check_number}</td>
        <td className="px-3 py-2">
          <div className="flex gap-1">
            <Button size="sm" variant="default" className="bg-green-600 hover:bg-green-700 text-xs h-7" onClick={onPost}>
              Post
            </Button>
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={onEdit}>
              Edit
            </Button>
            <Button size="sm" variant="ghost" className="text-red-500 text-xs h-7" onClick={onDelete}>
              ✕
            </Button>
          </div>
        </td>
      </tr>
      {error && (
        <tr>
          <td colSpan={6} className="px-3 py-1 text-xs text-red-600 bg-red-50">{error}</td>
        </tr>
      )}
    </>
  )
}

function EditableRow({
  initial,
  onSave,
  onCancel,
  isNew,
}: {
  initial?: Bill
  onSave: (b: BillIn) => void
  onCancel: () => void
  isNew: boolean
}) {
  const [vendor, setVendor] = useState(initial?.vendor_name ?? '')
  const [amount, setAmount] = useState(initial?.amount?.toString() ?? '')
  const [memo, setMemo] = useState(initial?.memo ?? '')
  const [date, setDate] = useState(initial?.date ?? today())
  const [check, setCheck] = useState(initial?.check_number ?? '')

  const handleSave = () => {
    const amt = parseFloat(amount)
    if (!vendor.trim() || isNaN(amt) || amt <= 0) return
    onSave({ vendor_name: vendor, amount: amt, memo, bill_date: date, check_number: check })
  }

  return (
    <tr className="border-b-2 border-blue-400 bg-blue-50">
      <td className="px-2 py-1"><Input className="h-7 text-sm" value={vendor} onChange={e => setVendor(e.target.value)} placeholder="Vendor" autoFocus /></td>
      <td className="px-2 py-1"><Input className="h-7 text-sm text-right" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" /></td>
      <td className="px-2 py-1"><Input className="h-7 text-sm" value={memo} onChange={e => setMemo(e.target.value)} placeholder="Memo" /></td>
      <td className="px-2 py-1"><Input className="h-7 text-sm" type="date" value={date} onChange={e => setDate(e.target.value)} /></td>
      <td className="px-2 py-1"><Input className="h-7 text-sm" value={check} onChange={e => setCheck(e.target.value)} placeholder="Check #" /></td>
      <td className="px-2 py-1">
        <div className="flex gap-1">
          <Button size="sm" className="text-xs h-7" onClick={handleSave}>{isNew ? 'Add' : 'Save'}</Button>
          <Button size="sm" variant="ghost" className="text-xs h-7" onClick={onCancel}>Cancel</Button>
        </div>
      </td>
    </tr>
  )
}

export default function BillsQueue() {
  const qc = useQueryClient()
  const { data: bills = [], isLoading } = useQuery({ queryKey: ['bills'], queryFn: getBills })
  const [editing, setEditing] = useState<EditingRow | null>(null)
  const [rowErrors, setRowErrors] = useState<RowError[]>([])
  const [postingAll, setPostingAll] = useState(false)

  const clearRowError = (index: number) =>
    setRowErrors(prev => prev.filter(e => e.index !== index))

  const addMutation = useMutation({
    mutationFn: addBill,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['bills'] }); setEditing(null) },
  })

  const updateMutation = useMutation({
    mutationFn: ({ index, bill }: { index: number; bill: BillIn }) => updateBill(index, bill),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['bills'] }); setEditing(null) },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteBill,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bills'] }),
  })

  const postMutation = useMutation({
    mutationFn: postBill,
    onSuccess: (data, index) => {
      if (data.ok) {
        qc.invalidateQueries({ queryKey: ['bills'] })
        clearRowError(index)
      } else {
        setRowErrors(prev => [...prev.filter(e => e.index !== index), { index, message: data.error }])
      }
    },
  })

  const handlePostAll = async () => {
    setPostingAll(true)
    try {
      const result = await postAllBills()
      qc.invalidateQueries({ queryKey: ['bills'] })
      if (result.failed?.length) {
        const errors: RowError[] = result.failed.map((f: { vendor_name: string; error: string }, i: number) => ({
          index: i,
          message: `${f.vendor_name}: ${f.error}`,
        }))
        setRowErrors(errors)
      } else {
        setRowErrors([])
      }
    } finally {
      setPostingAll(false)
    }
  }

  if (isLoading) return <div className="text-slate-500 text-sm">Loading...</div>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-slate-800">Bills Queue</h1>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handlePostAll} disabled={postingAll || bills.length === 0}>
            {postingAll ? 'Processing...' : 'Post All'}
          </Button>
          <Button size="sm" onClick={() => setEditing({ mode: 'add' })}>+ Add Bill</Button>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Vendor</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-slate-500 uppercase">Amount</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Memo</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Date</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Check #</th>
              <th className="px-3 py-2 text-xs font-medium text-slate-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody>
            {editing?.mode === 'add' && (
              <EditableRow
                isNew
                onSave={bill => addMutation.mutate(bill)}
                onCancel={() => setEditing(null)}
              />
            )}
            {bills.map(bill =>
              editing?.mode === 'edit' && editing.index === bill.index ? (
                <EditableRow
                  key={bill.index}
                  initial={bill}
                  isNew={false}
                  onSave={b => updateMutation.mutate({ index: bill.index, bill: b })}
                  onCancel={() => setEditing(null)}
                />
              ) : (
                <BillRow
                  key={bill.index}
                  bill={bill}
                  onEdit={() => setEditing({ mode: 'edit', index: bill.index })}
                  onDelete={() => {
                    if (confirm(`Delete bill for ${bill.vendor_name}?`)) {
                      deleteMutation.mutate(bill.index)
                    }
                  }}
                  onPost={() => postMutation.mutate(bill.index)}
                  error={rowErrors.find(e => e.index === bill.index)?.message}
                />
              )
            )}
            {bills.length === 0 && !editing && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-slate-400 text-sm">
                  No bills in queue. Click "+ Add Bill" to add one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify in browser**

With both servers running, navigate to http://localhost:5173/bills. You should see the bills table, be able to add a bill, edit inline, delete, and post.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/bills.ts frontend/src/pages/BillsQueue.tsx
git commit -m "feat: implement Bills Queue page with inline add/edit/post/delete"
```

---

### Task 10: Cash Entry page

**Files:**
- Create: `frontend/src/api/cash.ts`
- Create: `frontend/src/api/accounts.ts`
- Modify: `frontend/src/pages/CashEntry.tsx`

- [ ] **Step 1: Create accounts API module**

Create `frontend/src/api/accounts.ts`:
```ts
import api from './client'

export interface Account { name: string; guid: string }
export interface MemoSuggestions { suggestions: string[] }

export const getCashAccounts = () => api.get<Account[]>('/accounts/cash').then(r => r.data)
export const getAllAccounts = () => api.get<Account[]>('/accounts').then(r => r.data)
export const getMemos = (q: string) => api.get<MemoSuggestions>(`/memos?q=${encodeURIComponent(q)}`).then(r => r.data)
```

- [ ] **Step 2: Create cash API module**

Create `frontend/src/api/cash.ts`:
```ts
import api from './client'

export interface CashEntryRow { account_guid: string; memo: string; amount: number }
export interface CashSubmitIn {
  entry_date: string
  entries: CashEntryRow[]
  deposit_account_guid?: string
  deposit_amount?: number
  deposit_date?: string
}

export const submitCash = (body: CashSubmitIn) => api.post('/cash/submit', body).then(r => r.data)
```

- [ ] **Step 3: Implement CashEntry page**

Replace `frontend/src/pages/CashEntry.tsx` with:
```tsx
import { useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getCashAccounts, getMemos, type Account } from '../api/accounts'
import { submitCash, type CashEntryRow } from '../api/cash'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

const today = () => new Date().toISOString().slice(0, 10)

interface Row { id: number; account_guid: string; memo: string; amount: string }
let nextId = 1

function newRow(): Row {
  return { id: nextId++, account_guid: '', memo: '', amount: '' }
}

function AutocompleteInput({
  value, onChange, suggestions, placeholder, className,
}: {
  value: string
  onChange: (v: string) => void
  suggestions: string[]
  placeholder?: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <Input
        className={className}
        value={value}
        placeholder={placeholder}
        onChange={e => { onChange(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
      />
      {open && suggestions.length > 0 && (
        <ul className="absolute z-10 w-full bg-white border border-slate-200 rounded shadow-lg max-h-48 overflow-y-auto text-sm">
          {suggestions.map(s => (
            <li
              key={s}
              className="px-3 py-1.5 cursor-pointer hover:bg-blue-50"
              onMouseDown={() => { onChange(s); setOpen(false) }}
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function CashEntry() {
  const [entryDate, setEntryDate] = useState(today())
  const [rows, setRows] = useState<Row[]>([newRow()])
  const [memoQuery, setMemoQuery] = useState('')
  const [memoSuggestions, setMemoSuggestions] = useState<string[]>([])
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const { data: accounts = [] } = useQuery({ queryKey: ['cashAccounts'], queryFn: getCashAccounts })

  const updateRow = (id: number, field: keyof Row, value: string) =>
    setRows(prev => prev.map(r => r.id === id ? { ...r, [field]: value } : r))

  const removeRow = (id: number) =>
    setRows(prev => prev.filter(r => r.id !== id))

  const addRow = () => setRows(prev => [...prev, newRow()])

  const fetchMemos = async (q: string) => {
    const data = await getMemos(q)
    setMemoSuggestions(data.suggestions)
  }

  const samuse = rows.reduce((sum, r) => sum + (parseFloat(r.amount) || 0), 0)

  const handleSubmit = async () => {
    const entries: CashEntryRow[] = rows
      .filter(r => r.account_guid && parseFloat(r.amount) > 0)
      .map(r => ({ account_guid: r.account_guid, memo: r.memo, amount: parseFloat(r.amount) }))

    if (!entries.length) { setError('Add at least one entry with an account and amount.'); return }

    setSubmitting(true)
    setError(null)
    try {
      const res = await submitCash({ entry_date: entryDate, entries })
      if (res.batch?.ok) {
        setResult(`Posted $${res.batch.total.toFixed(2)} to GnuCash.`)
        setRows([newRow()])
      } else {
        setError(res.batch?.error || 'Unknown error')
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Server error'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-slate-800">Cash Entry</h1>
        <div className="flex items-center gap-3">
          <label className="text-sm text-slate-500">Date</label>
          <Input type="date" className="h-8 w-36 text-sm" value={entryDate} onChange={e => setEntryDate(e.target.value)} />
          <Button onClick={handleSubmit} disabled={submitting} className="bg-green-600 hover:bg-green-700">
            {submitting ? 'Posting...' : 'Post to GnuCash'}
          </Button>
        </div>
      </div>

      {result && <div className="mb-3 p-3 bg-green-50 border border-green-200 rounded text-green-700 text-sm">{result}</div>}
      {error && <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

      <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase w-5/12">Memo</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase w-4/12">Account</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-slate-500 uppercase w-2/12">Amount</th>
              <th className="px-3 py-2 w-1/12"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.id} className="border-b border-slate-100">
                <td className="px-2 py-1">
                  <AutocompleteInput
                    className="h-7 text-sm"
                    value={row.memo}
                    placeholder="Client / memo"
                    suggestions={memoSuggestions}
                    onChange={v => { updateRow(row.id, 'memo', v); fetchMemos(v) }}
                  />
                </td>
                <td className="px-2 py-1">
                  <select
                    className="h-7 text-sm w-full border border-slate-200 rounded px-2 bg-white"
                    value={row.account_guid}
                    onChange={e => updateRow(row.id, 'account_guid', e.target.value)}
                  >
                    <option value="">Select account...</option>
                    {accounts.map((a: Account) => (
                      <option key={a.guid} value={a.guid}>{a.name}</option>
                    ))}
                  </select>
                </td>
                <td className="px-2 py-1">
                  <Input
                    className="h-7 text-sm text-right"
                    value={row.amount}
                    placeholder="0.00"
                    onChange={e => updateRow(row.id, 'amount', e.target.value)}
                  />
                </td>
                <td className="px-2 py-1 text-center">
                  <button className="text-red-400 hover:text-red-600 text-sm" onClick={() => removeRow(row.id)}>✕</button>
                </td>
              </tr>
            ))}
            <tr className="border-b border-slate-200">
              <td colSpan={4} className="px-3 py-1">
                <button className="text-blue-600 text-sm hover:underline" onClick={addRow}>+ Add row</button>
              </td>
            </tr>
            <tr className="bg-green-50">
              <td className="px-3 py-2 text-sm text-slate-500 italic">SAMUSE (auto)</td>
              <td className="px-3 py-2 text-sm text-slate-500">Cash on Hand</td>
              <td className="px-3 py-2 text-sm font-semibold text-green-700 text-right">${samuse.toFixed(2)}</td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Verify in browser**

Navigate to http://localhost:5173/cash. You should see the spreadsheet table with one empty row, account dropdown populated from GnuCash, memo autocomplete, live SAMUSE total, and a Post button.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/cash.ts frontend/src/api/accounts.ts frontend/src/pages/CashEntry.tsx
git commit -m "feat: implement Cash Entry page with spreadsheet form and SAMUSE footer"
```

---

### Task 11: Vendor Management page

**Files:**
- Create: `frontend/src/api/vendors.ts`
- Modify: `frontend/src/pages/Vendors.tsx`

- [ ] **Step 1: Create vendors API module**

Create `frontend/src/api/vendors.ts`:
```ts
import api from './client'

export interface Vendor {
  key: string
  display_name: string
  gnucash_guid: string
  synced: boolean
  aliases: string[]
  addr_line1: string
  addr_city: string
  addr_state: string
  addr_zip: string
}

export interface VendorUpdate {
  display_name?: string
  addr_line1?: string
  addr_city?: string
  addr_state?: string
  addr_zip?: string
  aliases?: string[]
}

export const getVendors = () => api.get<Vendor[]>('/vendors').then(r => r.data)
export const updateVendor = (key: string, body: VendorUpdate) => api.put(`/vendors/${key}`, body).then(r => r.data)
export const syncAllVendors = () => api.post('/vendors/sync-all').then(r => r.data)
export const syncVendor = (key: string) => api.post(`/vendors/${key}/sync`).then(r => r.data)
export const lookupAddress = (body: object) => api.post('/vendors/lookup-address', body).then(r => r.data)
```

- [ ] **Step 2: Implement Vendors page**

Replace `frontend/src/pages/Vendors.tsx` with:
```tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getVendors, updateVendor, syncAllVendors, type Vendor, type VendorUpdate } from '../api/vendors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'

function VendorDetail({
  vendor,
  onSaved,
}: {
  vendor: Vendor
  onSaved: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<VendorUpdate>({
    display_name: vendor.display_name,
    addr_line1: vendor.addr_line1,
    addr_city: vendor.addr_city,
    addr_state: vendor.addr_state,
    addr_zip: vendor.addr_zip,
    aliases: [...vendor.aliases],
  })
  const [newAlias, setNewAlias] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)

  const updateMutation = useMutation({
    mutationFn: (body: VendorUpdate) => updateVendor(vendor.key, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vendors'] })
      setEditing(false)
      onSaved()
    },
    onError: (e: unknown) => setSaveError(e instanceof Error ? e.message : 'Save failed'),
  })

  const syncMutation = useMutation({
    mutationFn: () => syncAllVendors(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vendors'] }),
  })

  const field = (label: string, key: keyof VendorUpdate, placeholder?: string) => (
    <div className="mb-3">
      <label className="text-xs text-slate-500 uppercase block mb-1">{label}</label>
      {editing ? (
        <Input
          className="h-7 text-sm"
          value={(form[key] as string) ?? ''}
          placeholder={placeholder}
          onChange={e => setForm(prev => ({ ...prev, [key]: e.target.value }))}
        />
      ) : (
        <div className="text-sm text-slate-800">{(vendor as Record<string, unknown>)[key] as string || <span className="text-slate-400">—</span>}</div>
      )}
    </div>
  )

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-base font-semibold text-slate-800">{vendor.display_name}</h2>
        <div className="flex gap-2">
          {editing ? (
            <>
              <Button size="sm" onClick={() => updateMutation.mutate(form)} disabled={updateMutation.isPending}>Save</Button>
              <Button size="sm" variant="outline" onClick={() => { setEditing(false); setSaveError(null) }}>Cancel</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="outline" onClick={() => setEditing(true)}>Edit</Button>
              <Button size="sm" onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}>
                {syncMutation.isPending ? 'Syncing...' : 'Sync'}
              </Button>
            </>
          )}
        </div>
      </div>

      {saveError && <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-red-600 text-xs">{saveError}</div>}

      {field('Display Name', 'display_name')}
      <div className="mb-3">
        <label className="text-xs text-slate-500 uppercase block mb-1">Vendor Key</label>
        <div className="text-sm text-slate-500 font-mono">{vendor.key}</div>
      </div>
      <div className="mb-3">
        <label className="text-xs text-slate-500 uppercase block mb-1">GnuCash GUID</label>
        <div className="text-xs text-slate-400 font-mono truncate">{vendor.gnucash_guid || '—'}</div>
      </div>
      {field('Address', 'addr_line1', '123 Main St')}
      <div className="flex gap-2">
        <div className="flex-1">{field('City', 'addr_city')}</div>
        <div className="w-16">{field('State', 'addr_state')}</div>
        <div className="w-24">{field('ZIP', 'addr_zip')}</div>
      </div>

      <div className="mt-4">
        <label className="text-xs text-slate-500 uppercase block mb-1">Aliases</label>
        <div className="flex flex-wrap gap-1 mb-2">
          {(form.aliases ?? []).map(a => (
            <Badge key={a} variant="secondary" className="text-xs gap-1">
              {a}
              {editing && (
                <button
                  className="ml-1 text-slate-400 hover:text-red-500"
                  onClick={() => setForm(prev => ({ ...prev, aliases: prev.aliases?.filter(x => x !== a) }))}
                >
                  ✕
                </button>
              )}
            </Badge>
          ))}
          {(form.aliases ?? []).length === 0 && <span className="text-sm text-slate-400">None</span>}
        </div>
        {editing && (
          <div className="flex gap-2">
            <Input
              className="h-7 text-sm w-40"
              placeholder="New alias"
              value={newAlias}
              onChange={e => setNewAlias(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && newAlias.trim()) {
                  setForm(prev => ({ ...prev, aliases: [...(prev.aliases ?? []), newAlias.trim()] }))
                  setNewAlias('')
                }
              }}
            />
            <Button size="sm" variant="outline" onClick={() => {
              if (newAlias.trim()) {
                setForm(prev => ({ ...prev, aliases: [...(prev.aliases ?? []), newAlias.trim()] }))
                setNewAlias('')
              }
            }}>Add</Button>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Vendors() {
  const qc = useQueryClient()
  const { data: vendors = [], isLoading } = useQuery({ queryKey: ['vendors'], queryFn: getVendors })
  const [selected, setSelected] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const syncMutation = useMutation({
    mutationFn: syncAllVendors,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vendors'] }),
  })

  const filtered = vendors.filter(v =>
    v.display_name.toLowerCase().includes(search.toLowerCase()) ||
    v.key.toLowerCase().includes(search.toLowerCase())
  )

  const selectedVendor = vendors.find(v => v.key === selected) ?? null

  if (isLoading) return <div className="text-slate-500 text-sm">Loading...</div>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-slate-800">Vendors</h1>
        <Button size="sm" variant="outline" onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}>
          {syncMutation.isPending ? 'Syncing...' : 'Sync All'}
        </Button>
      </div>

      <div className="flex gap-0 bg-white rounded-lg border border-slate-200 overflow-hidden" style={{ minHeight: 500 }}>
        {/* Master panel */}
        <div className="w-56 border-r border-slate-200 flex flex-col flex-shrink-0">
          <div className="p-2 border-b border-slate-100">
            <Input className="h-7 text-sm" placeholder="Search vendors..." value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <div className="flex-1 overflow-y-auto">
            {filtered.map(v => (
              <button
                key={v.key}
                onClick={() => setSelected(v.key)}
                className={`w-full text-left px-3 py-2 border-l-2 transition-colors ${
                  selected === v.key
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-transparent hover:bg-slate-50'
                }`}
              >
                <div className="text-sm font-medium text-slate-800 truncate">{v.display_name}</div>
                <div className="flex items-center gap-1 mt-0.5">
                  <span className="text-xs text-slate-400 truncate">{v.key}</span>
                  {!v.synced && <Badge variant="outline" className="text-xs py-0 h-4 text-amber-600 border-amber-300">unsynced</Badge>}
                </div>
              </button>
            ))}
            {filtered.length === 0 && (
              <div className="p-4 text-sm text-slate-400 text-center">No vendors found</div>
            )}
          </div>
        </div>

        {/* Detail panel */}
        <div className="flex-1">
          {selectedVendor ? (
            <VendorDetail vendor={selectedVendor} onSaved={() => {}} />
          ) : (
            <div className="flex items-center justify-center h-full text-slate-400 text-sm">
              Select a vendor to view details
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Verify in browser**

Navigate to http://localhost:5173/vendors. Master panel shows vendor list with search. Clicking a vendor shows its details. Edit mode lets you change fields and aliases.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/vendors.ts frontend/src/pages/Vendors.tsx
git commit -m "feat: implement Vendor Management page with master/detail layout"
```

---

### Task 12: Settings page

**Files:**
- Create: `frontend/src/api/settings.ts`
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Create settings API module**

Create `frontend/src/api/settings.ts`:
```ts
import api from './client'

export interface AppSettings {
  ap_account_guid: string | null
  ap_account_name: string | null
  checking_account_guid: string | null
  checking_account_name: string | null
  expense_account_guid: string | null
  expense_account_name: string | null
  cash_on_hand_account_name: string
  locality_city: string
  locality_state: string
  home_latitude: number
  home_longitude: number
  search_radius_miles: number
  fuzzy_match_threshold: number
  fuzzy_ambiguous_threshold: number
  enabled_cash_account_guids: string[]
  gnucash_db_path: string
  processing_accounts_configured: boolean
}

export interface SettingsUpdate {
  ap_account_guid?: string
  checking_account_guid?: string
  expense_account_guid?: string
  cash_on_hand_account_name?: string
  locality_city?: string
  locality_state?: string
  home_latitude?: number
  home_longitude?: number
  search_radius_miles?: number
  fuzzy_match_threshold?: number
  fuzzy_ambiguous_threshold?: number
  enabled_cash_account_guids?: string[]
  gnucash_db_path?: string
}

export const getSettings = () => api.get<AppSettings>('/settings').then(r => r.data)
export const updateSettings = (body: SettingsUpdate) => api.put('/settings', body).then(r => r.data)
```

- [ ] **Step 2: Implement Settings page**

Replace `frontend/src/pages/Settings.tsx` with:
```tsx
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getSettings, updateSettings, type SettingsUpdate } from '../api/settings'
import { getAllAccounts, type Account } from '../api/accounts'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import api from '../api/client'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-lg border border-slate-200 p-5 mb-4">
      <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-4">{title}</h3>
      {children}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <label className="block text-sm text-slate-600 mb-1">{label}</label>
      {children}
    </div>
  )
}

export default function Settings() {
  const qc = useQueryClient()
  const { data: settings, isLoading } = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const { data: allAccounts = [] } = useQuery({ queryKey: ['allAccounts'], queryFn: getAllAccounts })
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (body: SettingsUpdate) => updateSettings(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
    onError: (e: unknown) => setSaveError(e instanceof Error ? e.message : 'Save failed'),
  })

  const browsePath = async () => {
    const res = await api.get<{ path: string }>('/db/browse')
    if (res.data.path) {
      mutation.mutate({ gnucash_db_path: res.data.path })
    }
  }

  if (isLoading || !settings) return <div className="text-slate-500 text-sm">Loading...</div>

  return (
    <div className="max-w-2xl">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-semibold text-slate-800">Settings</h1>
        {saved && <span className="text-green-600 text-sm">Saved</span>}
        {saveError && <span className="text-red-600 text-sm">{saveError}</span>}
      </div>

      <Section title="Database">
        <Field label="GnuCash Database Path">
          <div className="flex gap-2">
            <Input className="h-8 text-sm flex-1" value={settings.gnucash_db_path} readOnly />
            <Button size="sm" variant="outline" onClick={browsePath}>Browse...</Button>
          </div>
        </Field>
      </Section>

      <Section title="Processing Accounts">
        <Field label="Accounts Payable Account">
          <select
            className="w-full h-8 text-sm border border-slate-200 rounded px-2 bg-white"
            value={settings.ap_account_guid ?? ''}
            onChange={e => mutation.mutate({ ap_account_guid: e.target.value || undefined })}
          >
            <option value="">— not set —</option>
            {allAccounts.map((a: Account) => (
              <option key={a.guid} value={a.guid}>{a.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Checking Account">
          <select
            className="w-full h-8 text-sm border border-slate-200 rounded px-2 bg-white"
            value={settings.checking_account_guid ?? ''}
            onChange={e => mutation.mutate({ checking_account_guid: e.target.value || undefined })}
          >
            <option value="">— not set —</option>
            {allAccounts.map((a: Account) => (
              <option key={a.guid} value={a.guid}>{a.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Default Expense Account">
          <select
            className="w-full h-8 text-sm border border-slate-200 rounded px-2 bg-white"
            value={settings.expense_account_guid ?? ''}
            onChange={e => mutation.mutate({ expense_account_guid: e.target.value || undefined })}
          >
            <option value="">— not set —</option>
            {allAccounts.map((a: Account) => (
              <option key={a.guid} value={a.guid}>{a.name}</option>
            ))}
          </select>
        </Field>
      </Section>

      <Section title="Cash Entry">
        <Field label="Cash-on-Hand Account Name">
          <Input
            className="h-8 text-sm"
            defaultValue={settings.cash_on_hand_account_name}
            onBlur={e => mutation.mutate({ cash_on_hand_account_name: e.target.value })}
          />
        </Field>
      </Section>

      <Section title="Locality">
        <div className="flex gap-3">
          <Field label="City">
            <Input className="h-8 text-sm" defaultValue={settings.locality_city}
              onBlur={e => mutation.mutate({ locality_city: e.target.value })} />
          </Field>
          <Field label="State">
            <Input className="h-8 text-sm w-16" defaultValue={settings.locality_state}
              onBlur={e => mutation.mutate({ locality_state: e.target.value })} />
          </Field>
        </div>
        <div className="flex gap-3">
          <Field label="Latitude">
            <Input className="h-8 text-sm" defaultValue={settings.home_latitude}
              onBlur={e => mutation.mutate({ home_latitude: parseFloat(e.target.value) || undefined })} />
          </Field>
          <Field label="Longitude">
            <Input className="h-8 text-sm" defaultValue={settings.home_longitude}
              onBlur={e => mutation.mutate({ home_longitude: parseFloat(e.target.value) || undefined })} />
          </Field>
          <Field label="Search Radius (miles)">
            <Input className="h-8 text-sm w-24" defaultValue={settings.search_radius_miles}
              onBlur={e => mutation.mutate({ search_radius_miles: parseFloat(e.target.value) || undefined })} />
          </Field>
        </div>
      </Section>

      <Section title="Fuzzy Matching">
        <div className="flex gap-3">
          <Field label="Match Threshold">
            <Input className="h-8 text-sm w-20" defaultValue={settings.fuzzy_match_threshold}
              onBlur={e => mutation.mutate({ fuzzy_match_threshold: parseInt(e.target.value) || undefined })} />
          </Field>
          <Field label="Ambiguous Threshold">
            <Input className="h-8 text-sm w-20" defaultValue={settings.fuzzy_ambiguous_threshold}
              onBlur={e => mutation.mutate({ fuzzy_ambiguous_threshold: parseInt(e.target.value) || undefined })} />
          </Field>
        </div>
      </Section>
    </div>
  )
}
```

- [ ] **Step 3: Verify in browser**

Navigate to http://localhost:5173/settings. Settings load from the API. Changing a dropdown or blurring a text field saves immediately. "Saved" confirmation appears briefly.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/settings.ts frontend/src/pages/Settings.tsx
git commit -m "feat: implement Settings page with auto-save on blur"
```

---

### Task 13: Build frontend and update launcher

**Files:**
- Modify: `GnuCash Bills.bat`

- [ ] **Step 1: Test production build**

```
cd frontend
npm run build
cd ..
```
Expected: `frontend/dist/` created with `index.html` and `assets/`.

- [ ] **Step 2: Test FastAPI serves the build**

```
uv run uvicorn bill_processor.web.app:app --port 7432
```
Open http://localhost:7432. You should see the React app served from FastAPI (not the Vite dev server).

- [ ] **Step 3: Update GnuCash Bills.bat**

Replace `GnuCash Bills.bat` with:
```bat
@echo off
setlocal enabledelayedexpansion
title GnuCash Bills - Starting...

echo Checking if GnuCash Bills server is already running on port 7432...
curl -s -o nul -w "" http://localhost:7432/api/status >nul 2>&1
if !errorlevel! equ 0 (
    echo Server is already running. Opening browser...
    start http://localhost:7432
    timeout /t 2 /nobreak >nul
    exit /b 0
)

echo Building frontend...
cd /d D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections\frontend
call npm run build
if !errorlevel! neq 0 (
    echo ERROR: Frontend build failed.
    pause
    exit /b 1
)
cd /d D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections

echo Starting GnuCash Bills server on port 7432...
start "GnuCash Bills Server" cmd /c "cd /d D:\Users\Conrad\Documents\programming\GnuCash_bills_and_collections && uv run uvicorn bill_processor.web.app:app --port 7432 & echo. & echo Server stopped. Closing in 3 seconds... & timeout /t 3 /nobreak >nul"

echo Waiting for server to start...
set /a max_wait_seconds=30
set /a elapsed=0
:wait_loop
curl -s -o nul -w "" http://localhost:7432/api/status >nul 2>&1
if !errorlevel! equ 0 goto server_ready
if !elapsed! geq !max_wait_seconds! goto server_failed
timeout /t 1 /nobreak >nul
set /a elapsed+=1
goto wait_loop

:server_failed
echo ERROR: Server failed to start after 30 seconds.
pause
exit /b 1

:server_ready
echo Opening browser...
start http://localhost:7432
echo.
echo SUCCESS: Server is running in a separate console window.
echo This window will close in 20 seconds...
timeout /t 20 >nul
```

- [ ] **Step 4: Commit**

```bash
git add "GnuCash Bills.bat"
git commit -m "feat: update launcher to build React frontend before starting server"
```

---

### Task 14: Delete old files

**Files:**
- Delete: `web/templates/` (entire directory)
- Delete: `bill_entry_gui.py`
- Delete: `vendor_manager_gui.py`

- [ ] **Step 1: Run full test suite — confirm nothing uses templates**

```
uv run pytest tests/ -v
```
Expected: all tests pass. If any test imports from templates or the GUIs, fix it first.

- [ ] **Step 2: Delete old files**

```bash
git rm -r web/templates/
git rm bill_entry_gui.py vendor_manager_gui.py
```

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove HTMX templates and Tkinter GUI files"
```

---

### Task 15: Final verification

- [ ] **Step 1: Run full test suite**

```
uv run pytest tests/ -v
```
Expected: all tests pass, zero failures, zero errors.

- [ ] **Step 2: Smoke test the full app**

```
cd frontend && npm run build && cd ..
uv run uvicorn bill_processor.web.app:app --port 7432
```
Open http://localhost:7432. Walk through each section:
- Bills: add a bill, edit it, delete it
- Cash: add two rows, verify SAMUSE total updates
- Vendors: select a vendor, view details
- Settings: verify settings load and dropdowns are populated

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete React frontend rewrite — all four sections working"
```

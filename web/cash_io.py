"""Client name list I/O for cash entry memo autocomplete."""

import json
from bill_processor import config
from bill_processor.config import CLIENTS_PATH


def read_clients() -> list:
    """Return sorted list of client names from clients.json."""
    if not CLIENTS_PATH.exists():
        return []
    try:
        data = json.loads(CLIENTS_PATH.read_text(encoding="utf-8"))
        return sorted(data.get("clients", []))
    except (json.JSONDecodeError, OSError):
        return []


def search_clients(query: str, limit: int = config.CLIENT_SEARCH_MAX_RESULTS) -> list:
    """Return client names that start with or contain query (case-insensitive)."""
    q = query.strip().lower()
    if not q:
        return []
    clients = read_clients()
    starts = [c for c in clients if c.lower().startswith(q)]
    contains = [c for c in clients if q in c.lower() and c not in starts]
    return (starts + contains)[:limit]

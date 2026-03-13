"""Client name list I/O for cash entry memo autocomplete."""

import json
from datetime import datetime
from pathlib import Path
from bill_processor import config
from bill_processor.config import CLIENTS_PATH, MEMO_HISTORY_PATH


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


def read_memo_history() -> dict:
    """
    Read memo history from memo_history.json.
    
    Returns dict mapping memo -> {"count": int, "last_used": ISO timestamp}
    """
    if not MEMO_HISTORY_PATH.exists():
        return {}
    try:
        data = json.loads(MEMO_HISTORY_PATH.read_text(encoding="utf-8"))
        return data.get("memos", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_memo_to_history(memo: str) -> None:
    """
    Save or update a memo in the history file.
    Increments usage count and updates last_used timestamp.
    """
    if not memo or not memo.strip():
        return
    
    memo = memo.strip()
    
    # Read existing history
    history = read_memo_history()
    
    # Update or create entry
    if memo in history:
        history[memo]["count"] = history[memo].get("count", 0) + 1
        history[memo]["last_used"] = datetime.now().isoformat()
    else:
        history[memo] = {
            "count": 1,
            "last_used": datetime.now().isoformat()
        }
    
    # Write back
    MEMO_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMO_HISTORY_PATH.write_text(
        json.dumps({"memos": history}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def get_memo_suggestions(query: str, limit: int = config.CLIENT_SEARCH_MAX_RESULTS) -> list:
    """
    Return memo suggestions based on history, sorted by relevance.
    
    Scoring: exact prefix match > substring match, then by usage count.
    """
    q = query.strip().lower()
    if not q:
        # Return top used memos when no query
        history = read_memo_history()
        sorted_memos = sorted(
            history.items(),
            key=lambda x: (x[1].get("count", 0), x[1].get("last_used", "")),
            reverse=True
        )
        return [memo for memo, _ in sorted_memos[:limit]]
    
    history = read_memo_history()
    
    # Separate by match type and sort by count
    starts_with = []
    contains = []
    
    for memo, data in history.items():
        memo_lower = memo.lower()
        count = data.get("count", 0)
        
        if memo_lower.startswith(q):
            starts_with.append((memo, count))
        elif q in memo_lower:
            contains.append((memo, count))
    
    # Sort each group by count (descending)
    starts_with.sort(key=lambda x: x[1], reverse=True)
    contains.sort(key=lambda x: x[1], reverse=True)
    
    # Combine and return memo strings only
    results = [memo for memo, _ in starts_with] + [memo for memo, _ in contains]
    return results[:limit]

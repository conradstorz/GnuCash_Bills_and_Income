"""Resolve bill_type labels and account names to GnuCash account GUIDs."""
import json
from pathlib import Path
from typing import Optional
from loguru import logger

from bill_processor import config


REGISTRY_PATH = config.PROJECT_ROOT / "data" / "bill_account_labels.json"


class BillAccountResolver:
    def __init__(self, registry_path: Path = None):
        self._path = registry_path or REGISTRY_PATH
        self._registry = self._load()

    def _load(self) -> dict:
        if not self._path.exists():
            return {"presets": {}, "labels": {}}
        with open(self._path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._registry, f, indent=2)

    def resolve(
        self,
        bill_type: str,
        expense_acct: str,
        checking_acct: str,
        payables_acct: str,
    ) -> Optional[dict]:
        """Return {"expense_guid", "checking_guid", "ap_guid"} or None (use global settings).

        Raises ValueError if resolution fails for any configured account.
        """
        if not any([bill_type, expense_acct, checking_acct, payables_acct]):
            return None

        defaults = {"expense_acct": None, "checking_acct": None, "payables_acct": None}
        if bill_type:
            preset = self._registry.get("presets", {}).get(bill_type)
            if preset is None:
                raise ValueError(f"Unknown bill type: '{bill_type}'")
            defaults = dict(preset)

        overrides = {
            "expense_acct": expense_acct.strip() or None,
            "checking_acct": checking_acct.strip() or None,
            "payables_acct": payables_acct.strip() or None,
        }

        resolved = {k: overrides[k] if overrides[k] is not None else defaults[k] for k in defaults}

        out_keys = {"expense_acct": "expense_guid", "checking_acct": "checking_guid", "payables_acct": "ap_guid"}
        result = {}
        for field, out_key in out_keys.items():
            value = resolved[field]
            if value is None:
                raise ValueError(f"No {field} configured for this bill")
            result[out_key] = self._to_guid(field, value)

        return result

    def _to_guid(self, field: str, value) -> str:
        if isinstance(value, dict):
            guid = value.get("guid", "")
            if guid:
                return guid
            name = value.get("name", "")
            if not name:
                raise ValueError(f"Preset {field} has neither name nor guid")
            return self._db_lookup(name)

        label_entry = self._registry.get("labels", {}).get(value)
        if label_entry:
            guid = label_entry.get("guid", "")
            if guid:
                return guid
            return self._db_lookup(label_entry.get("name", value))

        return self._db_lookup(value)

    def _db_lookup(self, name: str) -> str:
        from bill_processor import gnucash_db
        account = gnucash_db.get_account_by_name(name)
        if account is None:
            raise ValueError(f"Account not found in GnuCash: '{name}'")
        logger.warning(f"Resolved account by name lookup (no GUID in registry): '{name}'")
        return account["guid"]

    def sync_guids(self) -> dict:
        """Populate empty GUIDs by name lookup. Returns {"updated": N, "failed": [...]}."""
        from bill_processor import gnucash_db
        updated = 0
        failed = []

        def _sync_entry(entry: dict) -> None:
            nonlocal updated
            if entry.get("guid"):
                return
            name = entry.get("name", "")
            if not name:
                return
            account = gnucash_db.get_account_by_name(name)
            if account:
                entry["guid"] = account["guid"]
                updated += 1
            else:
                failed.append({"name": name, "error": "Account not found in GnuCash"})

        for preset in self._registry.get("presets", {}).values():
            for acct_entry in preset.values():
                if isinstance(acct_entry, dict):
                    _sync_entry(acct_entry)

        for label_entry in self._registry.get("labels", {}).values():
            if isinstance(label_entry, dict):
                _sync_entry(label_entry)

        if updated:
            self._save()

        return {"updated": updated, "failed": failed}

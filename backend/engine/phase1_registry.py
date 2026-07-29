from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_REGISTRY_PATH = ROOT / "config" / "strategy_registry_canonical.json"
LIFECYCLE_LEDGER_PATH = ROOT / "data" / "runtime" / "strategy_lifecycle_ledger.json"
LEGACY_CONFIG_PATH = ROOT / "config" / "strategies_registry.json"
LEGACY_DISPOSITION_PATH = ROOT / "config" / "strategy_legacy_disposition.json"

REQUIRED_FIELDS = (
    "strategy_id",
    "owner",
    "allowed_symbols",
    "envelope_version",
    "route",
    "operating_mode",
    "last_smoke_ts",
    "last_replay_ts",
    "registry_state",
    "deprecate_reason",
)

ALLOWED_ROUTE = {"paper", "shadow", "canary", "live", "disabled"}
ALLOWED_OPERATING_MODE = {"paper", "shadow", "canary", "live", "disabled"}
ALLOWED_REGISTRY_STATE = {"active", "paused", "deprecated", "candidate", "disabled"}
ALLOWED_LEGACY_SOURCE_PRESENCE = {"config", "runtime", "both"}
ALLOWED_LEGACY_DISPOSITION = {"quarantine", "candidate", "alias", "retire"}

# Phase 1 starter scope:
# - keep canonical set tight to strategies that can actually touch execution today
# - legacy packs remain discoverable through audit only until owner mapping is confirmed
REQUIRED_ACTIVE_IDS = (
    "bingx_live_micro",
    "btc_trend_v1",
    "eth_trend_v1",
)


def _safe_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return _safe_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def _index_entries(entries: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    duplicates: List[str] = []
    for row in entries:
        strategy_id = _safe_str(row.get("strategy_id"))
        if not strategy_id:
            continue
        if strategy_id in indexed:
            duplicates.append(strategy_id)
            continue
        indexed[strategy_id] = row
    return indexed, sorted(set(duplicates))


def _normalize_entry(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    out["strategy_id"] = _safe_str(row.get("strategy_id"))
    out["owner"] = _safe_str(row.get("owner"))
    allowed_symbols = []
    for item in _safe_list(row.get("allowed_symbols")):
        token = _safe_str(item)
        if token:
            allowed_symbols.append(token)
    out["allowed_symbols"] = allowed_symbols
    out["envelope_version"] = _safe_str(row.get("envelope_version"))
    out["route"] = _safe_str(row.get("route")).lower()
    out["operating_mode"] = _safe_str(row.get("operating_mode")).lower()
    out["last_smoke_ts"] = _safe_str(row.get("last_smoke_ts"))
    out["last_replay_ts"] = _safe_str(row.get("last_replay_ts"))
    out["registry_state"] = _safe_str(row.get("registry_state")).lower()
    out["deprecate_reason"] = _safe_str(row.get("deprecate_reason"))
    return out


def _validate_entry(row: Dict[str, Any], *, source: str) -> List[str]:
    errors: List[str] = []
    strategy_id = _safe_str(row.get("strategy_id")) or "<missing>"
    missing = [key for key in REQUIRED_FIELDS if key not in row]
    if missing:
        errors.append(f"{source}:{strategy_id}:missing_fields={','.join(missing)}")

    normalized = _normalize_entry(row)
    if not normalized["strategy_id"]:
        errors.append(f"{source}:{strategy_id}:strategy_id_empty")
    if not normalized["owner"]:
        errors.append(f"{source}:{strategy_id}:owner_empty")
    if not normalized["allowed_symbols"]:
        errors.append(f"{source}:{strategy_id}:allowed_symbols_empty")
    if not normalized["envelope_version"]:
        errors.append(f"{source}:{strategy_id}:envelope_version_empty")
    if normalized["route"] not in ALLOWED_ROUTE:
        errors.append(f"{source}:{strategy_id}:bad_route={normalized['route']}")
    if normalized["operating_mode"] not in ALLOWED_OPERATING_MODE:
        errors.append(f"{source}:{strategy_id}:bad_operating_mode={normalized['operating_mode']}")
    if normalized["registry_state"] not in ALLOWED_REGISTRY_STATE:
        errors.append(f"{source}:{strategy_id}:bad_registry_state={normalized['registry_state']}")
    return errors


def load_canonical_manifest(path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or CANONICAL_REGISTRY_PATH
    doc = _load_json(target)
    raw_entries = _safe_list(doc.get("entries"))
    entries = [_normalize_entry(_safe_dict(row)) for row in raw_entries if isinstance(row, dict)]
    out = {
        "schema_version": _safe_str(doc.get("schema_version")) or "phase1_registry_canonical.v1",
        "entries": entries,
    }
    return out




def _normalize_legacy_disposition_entry(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    out["strategy_id"] = _safe_str(row.get("strategy_id"))
    out["source_presence"] = _safe_str(row.get("source_presence")).lower()
    out["disposition"] = _safe_str(row.get("disposition")).lower()
    out["canonical_target"] = _safe_str(row.get("canonical_target"))
    out["owner"] = _safe_str(row.get("owner"))
    out["note"] = _safe_str(row.get("note"))
    return out


def _validate_legacy_disposition_entry(row: Dict[str, Any], *, source: str) -> List[str]:
    errors: List[str] = []
    normalized = _normalize_legacy_disposition_entry(row)
    strategy_id = normalized["strategy_id"] or "<missing>"
    if not normalized["strategy_id"]:
        errors.append(f"{source}:{strategy_id}:strategy_id_empty")
    if normalized["source_presence"] not in ALLOWED_LEGACY_SOURCE_PRESENCE:
        errors.append(f"{source}:{strategy_id}:bad_source_presence={normalized['source_presence']}")
    if normalized["disposition"] not in ALLOWED_LEGACY_DISPOSITION:
        errors.append(f"{source}:{strategy_id}:bad_disposition={normalized['disposition']}")
    if not normalized["owner"]:
        errors.append(f"{source}:{strategy_id}:owner_empty")
    if not normalized["note"]:
        errors.append(f"{source}:{strategy_id}:note_empty")
    if normalized["disposition"] == "alias" and not normalized["canonical_target"]:
        errors.append(f"{source}:{strategy_id}:canonical_target_required_for_alias")
    return errors


def load_legacy_disposition_manifest(path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or LEGACY_DISPOSITION_PATH
    doc = _load_json(target)
    raw_entries = _safe_list(doc.get("entries"))
    entries = [_normalize_legacy_disposition_entry(_safe_dict(row)) for row in raw_entries if isinstance(row, dict)]
    out = {
        "schema_version": _safe_str(doc.get("schema_version")) or "phase1_legacy_disposition.v1",
        "entries": entries,
    }
    return out


def load_lifecycle_ledger(path: Optional[Path] = None) -> Dict[str, Any]:
    target = path or LIFECYCLE_LEDGER_PATH
    doc = _load_json(target)
    raw_entries = _safe_list(doc.get("entries"))
    entries = [_normalize_entry(_safe_dict(row)) for row in raw_entries if isinstance(row, dict)]
    out = {
        "schema_version": _safe_str(doc.get("schema_version")) or "phase1_strategy_lifecycle_ledger.v1",
        "entries": entries,
    }
    return out


def list_strategy_records() -> List[Dict[str, Any]]:
    return list(load_canonical_manifest().get("entries") or [])


def get_strategy_record(strategy_id: str) -> Dict[str, Any]:
    want = _safe_str(strategy_id)
    if not want:
        return {}
    for row in list_strategy_records():
        if _safe_str(row.get("strategy_id")) == want:
            return dict(row)
    return {}


def list_lifecycle_records() -> List[Dict[str, Any]]:
    return list(load_lifecycle_ledger().get("entries") or [])


def list_legacy_disposition_records() -> List[Dict[str, Any]]:
    return list(load_legacy_disposition_manifest().get("entries") or [])


def _load_legacy_ids_from_config() -> List[str]:
    doc = _load_json(LEGACY_CONFIG_PATH)
    if not isinstance(doc, dict):
        return []
    out = []
    for key in doc.keys():
        token = _safe_str(key)
        if token:
            out.append(token)
    return sorted(set(out))


def _load_legacy_ids_from_runtime_registry() -> List[str]:
    try:
        from backend.strategies.registry import list_strategies

        ids = []
        for item in list_strategies():
            token = _safe_str(item)
            if token:
                ids.append(token)
        return sorted(set(ids))
    except Exception:
        return []


def audit_registry_phase1() -> Dict[str, Any]:
    manifest = load_canonical_manifest()
    ledger = load_lifecycle_ledger()
    legacy_disposition = load_legacy_disposition_manifest()

    manifest_entries = list(manifest.get("entries") or [])
    ledger_entries = list(ledger.get("entries") or [])
    legacy_disposition_entries = list(legacy_disposition.get("entries") or [])

    manifest_map, manifest_duplicates = _index_entries(manifest_entries)
    ledger_map, ledger_duplicates = _index_entries(ledger_entries)
    legacy_disposition_map, legacy_disposition_duplicates = _index_entries(legacy_disposition_entries)

    validation_errors: List[str] = []
    for row in manifest_entries:
        validation_errors.extend(_validate_entry(row, source="canonical"))
    for row in ledger_entries:
        validation_errors.extend(_validate_entry(row, source="ledger"))
    for row in legacy_disposition_entries:
        validation_errors.extend(_validate_legacy_disposition_entry(row, source="legacy_disposition"))

    required_ids = sorted(set(REQUIRED_ACTIVE_IDS))
    manifest_ids = sorted(manifest_map.keys())
    ledger_ids = sorted(ledger_map.keys())

    missing_in_registry = [sid for sid in required_ids if sid not in manifest_map]
    missing_in_lifecycle = [sid for sid in manifest_ids if sid not in ledger_map]
    ledger_only_ids = [sid for sid in ledger_ids if sid not in manifest_map]

    legacy_config_ids = _load_legacy_ids_from_config()
    legacy_runtime_ids = _load_legacy_ids_from_runtime_registry()
    legacy_source_ids = sorted((set(legacy_config_ids) | set(legacy_runtime_ids)) - set(manifest_ids))
    managed_legacy_ids = [sid for sid in legacy_source_ids if sid in legacy_disposition_map]
    unmanaged_legacy_ids = [sid for sid in legacy_source_ids if sid not in legacy_disposition_map]
    stale_legacy_disposition_ids = [sid for sid in sorted(legacy_disposition_map.keys()) if sid not in legacy_source_ids]

    return {
        "ok": not (manifest_duplicates or ledger_duplicates or legacy_disposition_duplicates or validation_errors or missing_in_registry or missing_in_lifecycle or unmanaged_legacy_ids or stale_legacy_disposition_ids),
        "schema_version": "phase1_registry_audit.v1",
        "canonical_registry": str(CANONICAL_REGISTRY_PATH),
        "lifecycle_ledger": str(LIFECYCLE_LEDGER_PATH),
        "legacy_disposition": str(LEGACY_DISPOSITION_PATH),
        "required_active_ids": required_ids,
        "canonical_ids": manifest_ids,
        "lifecycle_ids": ledger_ids,
        "manifest_duplicates": manifest_duplicates,
        "ledger_duplicates": ledger_duplicates,
        "legacy_disposition_duplicates": legacy_disposition_duplicates,
        "missing_in_registry": missing_in_registry,
        "missing_in_lifecycle": missing_in_lifecycle,
        "ledger_only_ids": ledger_only_ids,
        "validation_errors": validation_errors,
        "legacy_config_only_ids": [sid for sid in legacy_config_ids if sid not in manifest_map],
        "legacy_runtime_only_ids": [sid for sid in legacy_runtime_ids if sid not in manifest_map],
        "managed_legacy_ids": managed_legacy_ids,
        "unmanaged_legacy_ids": unmanaged_legacy_ids,
        "stale_legacy_disposition_ids": stale_legacy_disposition_ids,
        "counts": {
            "required_active": len(required_ids),
            "canonical": len(manifest_ids),
            "lifecycle": len(ledger_ids),
            "legacy_config": len(legacy_config_ids),
            "legacy_runtime": len(legacy_runtime_ids),
            "managed_legacy": len(managed_legacy_ids),
            "unmanaged_legacy": len(unmanaged_legacy_ids),
            "stale_legacy_disposition": len(stale_legacy_disposition_ids),
        },
        "next_action": (
            "phase1 legacy quarantine seeded: canonical registry stays live-touching only while legacy ids remain explicitly dispositioned until owner mapping is confirmed"
        ),
    }


__all__ = [
    "CANONICAL_REGISTRY_PATH",
    "LIFECYCLE_LEDGER_PATH",
    "REQUIRED_ACTIVE_IDS",
    "audit_registry_phase1",
    "get_strategy_record",
    "list_lifecycle_records",
    "list_legacy_disposition_records",
    "list_strategy_records",
    "load_canonical_manifest",
    "load_lifecycle_ledger",
    "load_legacy_disposition_manifest",
]

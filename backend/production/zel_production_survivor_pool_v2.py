from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.production import zel_production_survivor_pool_v1 as v1
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = v1.SCHEMA
QUARANTINE_SCHEMA = "zel.production_survivor_quarantine.v1"
DEFAULT_POLICY = v1.DEFAULT_POLICY


def _receipt(row: Mapping[str, Any], label: str) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError(f"SURVIVOR_POOL_V2_{label}_RECEIPT_INVALID")
    actual = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    if actual != claimed:
        raise RuntimeError(f"SURVIVOR_POOL_V2_{label}_RECEIPT_MISMATCH")
    return claimed


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    cfg = v1.validate_policy(policy)
    if not str(cfg.get("quarantine_path") or "").strip():
        raise RuntimeError("SURVIVOR_POOL_V2_QUARANTINE_PATH_MISSING")
    return cfg


def _identity(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("family_id") or ""),
        str(row.get("runtime_symbol") or row.get("symbol") or "").replace("-", "").upper(),
        str(row.get("canary_key") or ""),
        str(row.get("contract_id") or ""),
    )


def _quarantined(row: Mapping[str, Any] | None) -> tuple[set[tuple[str, str, str, str]], str | None]:
    if row is None:
        return set(), None
    if row.get("schema_version") != QUARANTINE_SCHEMA:
        raise RuntimeError("SURVIVOR_POOL_V2_QUARANTINE_SCHEMA_INVALID")
    receipt = _receipt(row, "QUARANTINE")
    entries = row.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError("SURVIVOR_POOL_V2_QUARANTINE_ENTRIES_INVALID")
    return {_identity(x) for x in entries if isinstance(x, Mapping)}, receipt


def _filtered_catalog(catalog: Mapping[str, Any] | None, blocked: set[tuple[str, str, str, str]]) -> tuple[dict[str, Any] | None, int]:
    if catalog is None:
        return None, 0
    if catalog.get("schema_version") != v1.CATALOG_SCHEMA:
        raise RuntimeError("SURVIVOR_POOL_V2_CATALOG_SCHEMA_INVALID")
    rows = catalog.get("survivors")
    if not isinstance(rows, list):
        raise RuntimeError("SURVIVOR_POOL_V2_CATALOG_ROWS_INVALID")
    kept = []
    removed = 0
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise RuntimeError("SURVIVOR_POOL_V2_CATALOG_ROW_INVALID")
        if _identity(raw) in blocked:
            removed += 1
            continue
        kept.append(dict(raw))
    out = dict(catalog)
    out["survivors"] = kept
    if "survivor_count" in out:
        out["survivor_count"] = len(kept)
    return out, removed


def _filtered_registry(registry: Mapping[str, Any] | None, blocked: set[tuple[str, str, str, str]]) -> tuple[Mapping[str, Any] | None, int]:
    if not isinstance(registry, Mapping):
        return registry, 0
    authority = registry.get("current_authority")
    if not isinstance(authority, Mapping) or not authority:
        return registry, 0
    if _identity(authority) not in blocked:
        return registry, 0
    out = dict(registry)
    out["current_authority"] = {}
    out["current_metrics"] = {}
    return out, 1


def pool_tick(
    policy: Mapping[str, Any],
    *,
    catalog: Mapping[str, Any] | None,
    incumbent_registry: Mapping[str, Any] | None,
    quarantine_catalog: Mapping[str, Any] | None,
    previous_pool: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    blocked, quarantine_receipt = _quarantined(quarantine_catalog)
    filtered_catalog, catalog_removed = _filtered_catalog(catalog, blocked)
    filtered_registry, registry_removed = _filtered_registry(incumbent_registry, blocked)
    state, event = v1.pool_tick(
        cfg,
        catalog=filtered_catalog,
        incumbent_registry=filtered_registry,
        previous_pool=previous_pool,
        now_ms=now_ms,
    )
    state = dict(state)
    state.update({
        "pool_version": "V2_RUNTIME_QUARANTINE_AWARE",
        "quarantine_receipt_sha256": quarantine_receipt,
        "quarantined_identity_count": len(blocked),
        "quarantined_candidate_count": catalog_removed + registry_removed,
    })
    state["receipt_sha256"] = stable_sha({k: v for k, v in state.items() if k != "receipt_sha256"})
    if event is not None:
        event = dict(event)
        event["pool_receipt_sha256"] = state["receipt_sha256"]
        event["quarantine_receipt_sha256"] = quarantine_receipt
        event["receipt_sha256"] = stable_sha({k: v for k, v in event.items() if k != "receipt_sha256"})
    return state, event


def main() -> int:
    ap = argparse.ArgumentParser(description="ZEL quarantine-aware symbol-qualified 3+2 survivor pool")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args()
    policy = read_json(ns.policy, required=True)
    assert policy is not None
    cfg = validate_policy(policy)
    pool_path = Path(str(cfg["pool_state_path"]))
    previous = read_json(pool_path)
    state, event = pool_tick(
        cfg,
        catalog=read_json(Path(str(cfg["candidate_catalog_path"]))),
        incumbent_registry=read_json(Path(str(cfg["legacy_incumbent_registry_path"]))),
        quarantine_catalog=read_json(Path(str(cfg["quarantine_path"]))),
        previous_pool=previous,
    )
    atomic_json_write(pool_path, state)
    if event is not None:
        atomic_json_write(Path(str(cfg["pool_event_path"])), event)
    print(json.dumps({
        "state": state["state"],
        "active_count": state["active_count"],
        "reserve_count": state["reserve_count"],
        "quarantined_candidate_count": state["quarantined_candidate_count"],
        "event_type": None if event is None else event["event_type"],
        "receipt_sha256": state["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

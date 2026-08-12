from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production import zel_production_survivor_rotation_v1 as v1
from backend.production.zel_production_active_alpha_adapter_v1 import authority_is_executable
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = v1.SCHEMA
HEALTH_STATE_SCHEMA = "zel.production_survivor_runtime_health.v1"
DEFAULT_POLICY = v1.DEFAULT_POLICY


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    cfg = v1.validate_policy(policy)
    if not str(cfg.get("health_state_path") or "").strip():
        raise RuntimeError("SURVIVOR_ROTATION_V2_HEALTH_STATE_PATH_MISSING")
    return cfg


def _hold(reason: str, now_ms: int) -> dict[str, Any]:
    return v1._hold(reason, now_ms)


def _health_gate(
    authority: Mapping[str, Any],
    health_state: Mapping[str, Any] | None,
    health_result: Mapping[str, Any] | None,
) -> tuple[bool, str]:
    if not isinstance(health_state, Mapping):
        return False, "RUNTIME_HEALTH_STATE_MISSING"
    if health_state.get("schema_version") != HEALTH_STATE_SCHEMA:
        raise RuntimeError("SURVIVOR_ROTATION_V2_HEALTH_STATE_SCHEMA_INVALID")
    v1._receipt(health_state, "HEALTH_STATE")
    if str(health_state.get("status") or "") != "REJECT":
        return False, "RUNTIME_HEALTH_STATE_NOT_REJECT"
    authority_receipt = str(authority.get("receipt_sha256") or "")
    if str(health_state.get("authority_receipt_sha256") or "") != authority_receipt:
        return False, "RUNTIME_HEALTH_STATE_STALE_AUTHORITY"
    if not isinstance(health_result, Mapping):
        raise RuntimeError("SURVIVOR_ROTATION_V2_HEALTH_RESULT_MISSING_FOR_REJECT_STATE")
    result_receipt = v1._receipt(health_result, "HEALTH_RESULT")
    if str(health_state.get("terminal_result_receipt_sha256") or "") != result_receipt:
        raise RuntimeError("SURVIVOR_ROTATION_V2_HEALTH_STATE_RESULT_RECEIPT_MISMATCH")
    v1._health_matches(authority, health_result)
    return True, "RUNTIME_HEALTH_REJECT_CONFIRMED"


def _eligible_pool_view(pool: Mapping[str, Any], cfg: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if pool.get("schema_version") != v1.POOL_SCHEMA:
        raise RuntimeError("SURVIVOR_ROTATION_V2_POOL_SCHEMA_INVALID")
    source_receipt = v1._receipt(pool, "POOL")
    out = dict(pool)
    skipped: list[dict[str, str]] = []
    for bucket in ("active", "reserve"):
        raw_rows = pool.get(bucket)
        if not isinstance(raw_rows, list):
            raise RuntimeError("SURVIVOR_ROTATION_V2_POOL_ROWS_INVALID")
        kept: list[dict[str, Any]] = []
        for raw in raw_rows:
            if not isinstance(raw, Mapping):
                skipped.append({"bucket": bucket, "reason": "NON_MAPPING"})
                continue
            try:
                kept.append(v1._validate_candidate(raw, cfg["risk_request"]))
            except RuntimeError as exc:
                skipped.append({
                    "bucket": bucket,
                    "family_id": str(raw.get("family_id") or ""),
                    "reason": str(exc),
                })
        out[bucket] = kept
    out["active_count"] = len(out["active"])
    out["reserve_count"] = len(out["reserve"])
    out["rotation_filter_source_pool_receipt_sha256"] = source_receipt
    out["rotation_ineligible_row_count"] = len(skipped)
    out["rotation_ineligible_rows"] = skipped
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out, source_receipt


def _original_index(pool: Mapping[str, Any], authority: Mapping[str, Any]) -> int:
    target = v1._identity(authority)
    rows: list[Mapping[str, Any]] = []
    for bucket in ("active", "reserve"):
        raw = pool.get(bucket)
        if isinstance(raw, list):
            rows.extend(x for x in raw if isinstance(x, Mapping))
    for idx, row in enumerate(rows):
        if v1._identity(row) == target:
            return idx
    return -1


def _restore_source_pool_provenance(
    state: dict[str, Any],
    authority: dict[str, Any] | None,
    source_pool_receipt: str,
    source_pool: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if authority is None or state.get("state") != "PASS_SURVIVOR_RUNTIME_ROTATED":
        return state, authority
    fallback_view_receipt = str(authority.get("pool_receipt_sha256") or "")
    original_idx = _original_index(source_pool, authority)
    authority = dict(authority)
    authority["pool_receipt_sha256"] = source_pool_receipt
    authority["fallback_pool_view_receipt_sha256"] = fallback_view_receipt
    authority["pool_rank"] = original_idx
    authority["receipt_sha256"] = stable_sha({k: v for k, v in authority.items() if k != "receipt_sha256"})
    state = dict(state)
    state["source_pool_receipt_sha256"] = source_pool_receipt
    state["fallback_pool_view_receipt_sha256"] = fallback_view_receipt
    state["pool_order_index"] = original_idx
    state["authority_receipt_sha256"] = authority["receipt_sha256"]
    state["receipt_sha256"] = stable_sha({k: v for k, v in state.items() if k != "receipt_sha256"})
    return state, authority


def rotate_tick(
    policy: Mapping[str, Any],
    *,
    authority: Mapping[str, Any] | None,
    health_state: Mapping[str, Any] | None,
    health_result: Mapping[str, Any] | None,
    pool: Mapping[str, Any] | None,
    canary_state: Mapping[str, Any] | None,
    quarantine_catalog: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if not isinstance(authority, Mapping) or not authority_is_executable(authority):
        return _hold("NO_EXECUTABLE_AUTHORITY", now), None, None
    v1._receipt(authority, "AUTHORITY")
    rotate, reason = _health_gate(authority, health_state, health_result)
    if not rotate:
        return _hold(reason, now), None, None
    if not isinstance(pool, Mapping):
        raise RuntimeError("SURVIVOR_ROTATION_V2_POOL_MISSING")
    filtered_pool, source_pool_receipt = _eligible_pool_view(pool, cfg)
    state, replacement, quarantine = v1.rotate_tick(
        cfg,
        authority=authority,
        health_result=health_result,
        pool=filtered_pool,
        canary_state=canary_state,
        quarantine_catalog=quarantine_catalog,
        now_ms=now,
    )
    state, replacement = _restore_source_pool_provenance(
        state,
        replacement,
        source_pool_receipt,
        pool,
    )
    return state, replacement, quarantine


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="State-gated survivor demotion and ordered fallback rotation")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    policy = read_json(ns.policy, required=True)
    assert policy is not None
    cfg = validate_policy(policy)
    state, authority, quarantine = rotate_tick(
        cfg,
        authority=read_json(Path(str(cfg["authority_path"]))),
        health_state=read_json(Path(str(cfg["health_state_path"]))),
        health_result=read_json(Path(str(cfg["health_result_path"]))),
        pool=read_json(Path(str(cfg["pool_path"]))),
        canary_state=read_json(Path(str(cfg["canary_state_path"]))),
        quarantine_catalog=read_json(Path(str(cfg["quarantine_path"]))),
    )
    atomic_json_write(Path(str(cfg["state_path"])), state)
    if quarantine is not None:
        atomic_json_write(Path(str(cfg["quarantine_path"])), quarantine)
    if authority is not None:
        atomic_json_write(Path(str(cfg["authority_path"])), authority)
    print(json.dumps({
        "state": state["state"],
        "action": state["action"],
        "authority_written": state["authority_written"],
        "from_family_id": state.get("from_family_id"),
        "to_family_id": state.get("to_family_id"),
        "receipt_sha256": state["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

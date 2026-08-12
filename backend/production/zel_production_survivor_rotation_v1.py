from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.production.zel_production_active_alpha_adapter_v1 import authority_is_executable
from backend.production.zel_production_ai_admission_executor_v2 import SUPPORTED_TEMPLATES
from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha
from backend.production.zel_production_survivor_authority_activation_v1 import _verify_canary

SCHEMA = "zel.production_survivor_rotation.v1"
POLICY_SCHEMA = "zel.production_survivor_rotation_policy.v1"
HEALTH_RESULT_SCHEMA = "zel.production_survivor_runtime_health_result.v1"
POOL_SCHEMA = "zel.production_survivor_pool.v1"
CANARY_STATE_SCHEMA = "zel.production_family_paper_canary_runner.v1"
AUTHORITY_SCHEMA = "zel.production_alpha_authority.v1"
QUARANTINE_SCHEMA = "zel.production_survivor_quarantine.v1"
DEFAULT_POLICY = Path("config/zel_production_survivor_rotation_v1.json")
RUNTIME_SYMBOLS = {"BTCUSDT", "ETHUSDT"}


def _receipt(row: Mapping[str, Any], label: str) -> str:
    claimed = str(row.get("receipt_sha256") or "")
    if len(claimed) != 64:
        raise RuntimeError(f"SURVIVOR_ROTATION_{label}_RECEIPT_INVALID")
    actual = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    if actual != claimed:
        raise RuntimeError(f"SURVIVOR_ROTATION_{label}_RECEIPT_MISMATCH")
    return claimed


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("SURVIVOR_ROTATION_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("SURVIVOR_ROTATION_NON_PAPER_FORBIDDEN")
    for key in ("authority_path", "pool_path", "canary_state_path", "health_result_path", "quarantine_path", "state_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"SURVIVOR_ROTATION_PATH_MISSING:{key}")
    if policy.get("rotation_order") != ["active", "reserve"]:
        raise RuntimeError("SURVIVOR_ROTATION_ORDER_DRIFT")
    if policy.get("selection_rule") != "EXISTING_POOL_ORDER_EXCLUDING_CURRENT_AND_QUARANTINED_NO_RERANK":
        raise RuntimeError("SURVIVOR_ROTATION_SELECTION_RULE_DRIFT")
    if policy.get("risk_request") != {"leverage_x": 10, "position_pct": 5.0}:
        raise RuntimeError("SURVIVOR_ROTATION_RISK_REQUEST_DRIFT")
    if policy.get("execution_authority") != "PAPER_SIM_ONLY":
        raise RuntimeError("SURVIVOR_ROTATION_EXECUTION_AUTHORITY_INVALID")
    if policy.get("order_authority") != "BLOCKED" or policy.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_ROTATION_LIVE_AUTHORITY_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("SURVIVOR_ROTATION_MUTATION_FORBIDDEN")
    return dict(policy)


def _identity(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("family_id") or ""),
        str(row.get("runtime_symbol") or row.get("symbol") or "").replace("-", "").upper(),
        str(row.get("canary_key") or ""),
        str(row.get("contract_id") or ""),
    )


def _empty_quarantine(now_ms: int) -> dict[str, Any]:
    row = {
        "schema_version": QUARANTINE_SCHEMA,
        "state": "PASS_SURVIVOR_QUARANTINE_CATALOG",
        "entries": [],
        "quarantined_count": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now_ms,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def _load_quarantine(row: Mapping[str, Any] | None, now_ms: int) -> dict[str, Any]:
    if row is None:
        return _empty_quarantine(now_ms)
    if row.get("schema_version") != QUARANTINE_SCHEMA:
        raise RuntimeError("SURVIVOR_ROTATION_QUARANTINE_SCHEMA_INVALID")
    _receipt(row, "QUARANTINE")
    entries = row.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError("SURVIVOR_ROTATION_QUARANTINE_ENTRIES_INVALID")
    out = dict(row)
    out["entries"] = [dict(x) for x in entries if isinstance(x, Mapping)]
    return out


def _append_quarantine(
    catalog: Mapping[str, Any],
    authority: Mapping[str, Any],
    health: Mapping[str, Any],
    now_ms: int,
) -> tuple[dict[str, Any], bool]:
    out = dict(catalog)
    entries = [dict(x) for x in out.get("entries") or [] if isinstance(x, Mapping)]
    ident = _identity(authority)
    for row in entries:
        if _identity(row) == ident:
            return out, False
    entry = {
        "family_id": ident[0],
        "runtime_symbol": ident[1],
        "canary_key": ident[2],
        "contract_id": ident[3],
        "strategy_id": str(authority.get("strategy_id") or ""),
        "alpha_id": str(authority.get("alpha_id") or ""),
        "authority_receipt_sha256": str(authority.get("receipt_sha256") or ""),
        "health_result_receipt_sha256": str(health.get("receipt_sha256") or ""),
        "health_epoch_index": int(health.get("epoch_index") or 0),
        "reason": "POST_ACTIVATION_SURVIVOR_RUNTIME_HEALTH_REJECT",
        "quarantined_at_ms": now_ms,
    }
    entry["entry_sha256"] = stable_sha(entry)
    entries.append(entry)
    out.update({
        "schema_version": QUARANTINE_SCHEMA,
        "state": "PASS_SURVIVOR_QUARANTINE_CATALOG",
        "entries": entries,
        "quarantined_count": len(entries),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now_ms,
    })
    out["receipt_sha256"] = stable_sha({k: v for k, v in out.items() if k != "receipt_sha256"})
    return out, True


def _health_matches(authority: Mapping[str, Any], health: Mapping[str, Any]) -> None:
    if health.get("schema_version") != HEALTH_RESULT_SCHEMA:
        raise RuntimeError("SURVIVOR_ROTATION_HEALTH_SCHEMA_INVALID")
    _receipt(health, "HEALTH_RESULT")
    if str(health.get("state") or "") != "REJECT_SURVIVOR_RUNTIME_HEALTH":
        raise RuntimeError("SURVIVOR_ROTATION_HEALTH_NOT_REJECT")
    expected = {
        "authority_receipt_sha256": str(authority.get("receipt_sha256") or ""),
        "family_id": str(authority.get("family_id") or ""),
        "strategy_id": str(authority.get("strategy_id") or ""),
        "alpha_id": str(authority.get("alpha_id") or ""),
        "runtime_symbol": str(authority.get("runtime_symbol") or authority.get("symbol") or "").replace("-", "").upper(),
        "canary_key": str(authority.get("canary_key") or ""),
        "contract_id": str(authority.get("contract_id") or ""),
        "contract_receipt_sha256": str(authority.get("contract_receipt_sha256") or ""),
    }
    for key, want in expected.items():
        got = str(health.get(key) or "")
        if key == "runtime_symbol":
            got = got.replace("-", "").upper()
        if got != want:
            raise RuntimeError(f"SURVIVOR_ROTATION_HEALTH_LINEAGE_MISMATCH:{key}")


def _quarantined_set(catalog: Mapping[str, Any]) -> set[tuple[str, str, str, str]]:
    return {_identity(x) for x in catalog.get("entries") or [] if isinstance(x, Mapping)}


def _validate_candidate(candidate: Mapping[str, Any], risk_request: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(candidate)
    if row.get("symbol_qualified") is not True:
        raise RuntimeError("SURVIVOR_ROTATION_CANDIDATE_NOT_SYMBOL_QUALIFIED")
    symbol = str(row.get("runtime_symbol") or "").replace("-", "").upper()
    if symbol not in RUNTIME_SYMBOLS:
        raise RuntimeError("SURVIVOR_ROTATION_CANDIDATE_SYMBOL_INVALID")
    if str(row.get("strategy_id") or "") not in SUPPORTED_TEMPLATES:
        raise RuntimeError("SURVIVOR_ROTATION_CANDIDATE_STRATEGY_UNSUPPORTED")
    for key in ("family_id", "strategy_id", "alpha_id", "canary_key", "contract_id"):
        if not str(row.get(key) or ""):
            raise RuntimeError(f"SURVIVOR_ROTATION_CANDIDATE_IDENTITY_MISSING:{key}")
    for key in ("contract_receipt_sha256", "canary_receipt_sha256"):
        if len(str(row.get(key) or "")) != 64:
            raise RuntimeError(f"SURVIVOR_ROTATION_CANDIDATE_LINEAGE_INVALID:{key}")
    hashes = row.get("source_hashes")
    if not isinstance(hashes, list) or not hashes or any(not str(x).strip() for x in hashes):
        raise RuntimeError("SURVIVOR_ROTATION_CANDIDATE_SOURCE_HASHES_INVALID")
    if row.get("risk_request") != dict(risk_request):
        raise RuntimeError("SURVIVOR_ROTATION_CANDIDATE_RISK_REQUEST_MISMATCH")
    row["runtime_symbol"] = symbol
    return row


def _ordered_candidates(pool: Mapping[str, Any]) -> list[dict[str, Any]]:
    if pool.get("schema_version") != POOL_SCHEMA:
        raise RuntimeError("SURVIVOR_ROTATION_POOL_SCHEMA_INVALID")
    _receipt(pool, "POOL")
    active = pool.get("active")
    reserve = pool.get("reserve")
    if not isinstance(active, list) or not isinstance(reserve, list):
        raise RuntimeError("SURVIVOR_ROTATION_POOL_ROWS_INVALID")
    return [dict(x) for x in active + reserve if isinstance(x, Mapping)]


def _blocked_authority(authority: Mapping[str, Any], health: Mapping[str, Any], quarantine: Mapping[str, Any], now_ms: int) -> dict[str, Any]:
    row = dict(authority)
    row.update({
        "state": "HOLD_SURVIVOR_RUNTIME_QUARANTINED",
        "alpha_state": "QUARANTINED",
        "research_only": True,
        "promotion_authority": False,
        "execution_allowed": False,
        "runtime_bound": False,
        "runtime_authority": {
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "quarantined_from_authority_receipt_sha256": str(authority.get("receipt_sha256") or ""),
        "runtime_health_reject_receipt_sha256": str(health.get("receipt_sha256") or ""),
        "quarantine_catalog_receipt_sha256": str(quarantine.get("receipt_sha256") or ""),
        "quarantined_at_ms": now_ms,
    })
    row["receipt_sha256"] = stable_sha({k: v for k, v in row.items() if k != "receipt_sha256"})
    return row


def _rotated_authority(
    candidate: Mapping[str, Any],
    *,
    pool: Mapping[str, Any],
    canary_state: Mapping[str, Any],
    prior_authority: Mapping[str, Any],
    health: Mapping[str, Any],
    quarantine: Mapping[str, Any],
    pool_order_index: int,
    policy: Mapping[str, Any],
    now_ms: int,
) -> dict[str, Any]:
    row = _validate_candidate(candidate, policy["risk_request"])
    canary_receipt = _verify_canary(row, canary_state)
    symbol = str(row["runtime_symbol"])
    authority = {
        "schema_version": AUTHORITY_SCHEMA,
        "state": "PASS_SURVIVOR_ACTIVE_AUTHORITY",
        "alpha_state": "SURVIVOR_ACTIVE",
        "family_id": str(row["family_id"]),
        "strategy_id": str(row["strategy_id"]),
        "alpha_id": str(row["alpha_id"]),
        "symbol": symbol,
        "runtime_symbol": symbol,
        "symbol_qualified": True,
        "canary_key": str(row["canary_key"]),
        "contract_id": str(row["contract_id"]),
        "contract_receipt_sha256": str(row["contract_receipt_sha256"]),
        "canary_receipt_sha256": canary_receipt,
        "pool_receipt_sha256": str(pool.get("receipt_sha256") or ""),
        "pool_rank": pool_order_index,
        "selection_rule": policy["selection_rule"],
        "source_hashes": sorted(set(map(str, row["source_hashes"]))),
        "risk_request": dict(policy["risk_request"]),
        "metrics": dict(row.get("metrics") or {}),
        "research_only": False,
        "selection_authority": False,
        "promotion_authority": True,
        "execution_allowed": True,
        "runtime_bound": True,
        "runtime_authority": {
            "execution_authority": "PAPER_SIM_ONLY",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "source_code_mutation_applied": False,
        "self_modification_applied": False,
        "rotated_from_authority_receipt_sha256": str(prior_authority.get("receipt_sha256") or ""),
        "rotation_health_receipt_sha256": str(health.get("receipt_sha256") or ""),
        "quarantine_catalog_receipt_sha256": str(quarantine.get("receipt_sha256") or ""),
        "activated_at_ms": now_ms,
        "rotated_at_ms": now_ms,
    }
    authority["receipt_sha256"] = stable_sha(authority)
    return authority


def _hold(reason: str, now_ms: int) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA,
        "state": "HOLD_SURVIVOR_ROTATION",
        "action": "hold",
        "reason": reason,
        "authority_written": False,
        "quarantine_written": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now_ms,
    }
    row["receipt_sha256"] = stable_sha(row)
    return row


def rotate_tick(
    policy: Mapping[str, Any],
    *,
    authority: Mapping[str, Any] | None,
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
    _receipt(authority, "AUTHORITY")
    if not isinstance(health_result, Mapping):
        return _hold("RUNTIME_HEALTH_RESULT_MISSING", now), None, None
    if str(health_result.get("state") or "") != "REJECT_SURVIVOR_RUNTIME_HEALTH":
        return _hold("RUNTIME_HEALTH_NOT_REJECT", now), None, None
    _health_matches(authority, health_result)
    if not isinstance(pool, Mapping):
        raise RuntimeError("SURVIVOR_ROTATION_POOL_MISSING")
    if not isinstance(canary_state, Mapping) or canary_state.get("schema_version") != CANARY_STATE_SCHEMA:
        raise RuntimeError("SURVIVOR_ROTATION_CANARY_STATE_INVALID")

    quarantine = _load_quarantine(quarantine_catalog, now)
    quarantine, quarantine_changed = _append_quarantine(quarantine, authority, health_result, now)
    blocked = _blocked_authority(authority, health_result, quarantine, now)
    current_id = _identity(authority)
    quarantined = _quarantined_set(quarantine)
    selected = None
    selected_idx = -1
    for idx, raw in enumerate(_ordered_candidates(pool)):
        candidate = _validate_candidate(raw, cfg["risk_request"])
        ident = _identity(candidate)
        if ident == current_id or ident in quarantined:
            continue
        selected = candidate
        selected_idx = idx
        break

    if selected is None:
        state = {
            "schema_version": SCHEMA,
            "state": "HOLD_SURVIVOR_ROTATION_NO_ELIGIBLE_FALLBACK",
            "action": "hold",
            "reason": "CURRENT_SURVIVOR_QUARANTINED_NO_ELIGIBLE_POOL_FALLBACK",
            "authority_written": True,
            "authority_executable": False,
            "quarantine_written": quarantine_changed,
            "quarantined_family_id": str(authority.get("family_id") or ""),
            "quarantine_catalog_receipt_sha256": quarantine["receipt_sha256"],
            "authority_receipt_sha256": blocked["receipt_sha256"],
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "updated_at_ms": now,
        }
        state["receipt_sha256"] = stable_sha(state)
        return state, blocked, quarantine

    rotated = _rotated_authority(
        selected,
        pool=pool,
        canary_state=canary_state,
        prior_authority=authority,
        health=health_result,
        quarantine=quarantine,
        pool_order_index=selected_idx,
        policy=cfg,
        now_ms=now,
    )
    state = {
        "schema_version": SCHEMA,
        "state": "PASS_SURVIVOR_RUNTIME_ROTATED",
        "action": "route_change",
        "reason": "RUNTIME_HEALTH_REJECT_ROTATED_BY_EXISTING_POOL_ORDER",
        "authority_written": True,
        "authority_executable": True,
        "quarantine_written": quarantine_changed,
        "from_family_id": str(authority.get("family_id") or ""),
        "to_family_id": rotated["family_id"],
        "to_runtime_symbol": rotated["runtime_symbol"],
        "pool_order_index": selected_idx,
        "health_result_receipt_sha256": str(health_result.get("receipt_sha256") or ""),
        "quarantine_catalog_receipt_sha256": quarantine["receipt_sha256"],
        "authority_receipt_sha256": rotated["receipt_sha256"],
        "selection_authority": False,
        "promotion_authority": True,
        "execution_authority": "PAPER_SIM_ONLY",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now,
    }
    state["receipt_sha256"] = stable_sha(state)
    return state, rotated, quarantine


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Demote failed active survivor and rotate through existing 3+2 pool order")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args(argv)
    policy = read_json(ns.policy, required=True)
    assert policy is not None
    cfg = validate_policy(policy)
    state, authority, quarantine = rotate_tick(
        cfg,
        authority=read_json(Path(str(cfg["authority_path"]))),
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

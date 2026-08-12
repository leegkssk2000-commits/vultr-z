from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_survivor_pool.v1"
POLICY_SCHEMA = "zel.production_survivor_pool_policy.v1"
CATALOG_SCHEMA = "zel.production_survivor_catalog.v1"
REGISTRY_SCHEMA = "zel.production_incumbent_registry.v1"
DEFAULT_POLICY = Path("config/zel_production_survivor_pool_v1.json")
RUNTIME_SYMBOLS = ("BTCUSDT", "ETHUSDT")


def _f(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"SURVIVOR_POOL_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"SURVIVOR_POOL_NUMERIC_NONFINITE:{name}")
    return out


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("SURVIVOR_POOL_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("SURVIVOR_POOL_NON_PAPER_FORBIDDEN")
    if int(policy.get("active_target") or 0) != 3 or int(policy.get("reserve_target") or 0) != 2:
        raise RuntimeError("SURVIVOR_POOL_TARGET_MUST_BE_3_PLUS_2")
    if policy.get("distinct_family_required") is not True:
        raise RuntimeError("SURVIVOR_POOL_DISTINCT_FAMILY_REQUIRED")
    if policy.get("ranking_method") != "LEXICOGRAPHIC_NO_WEIGHT":
        raise RuntimeError("SURVIVOR_POOL_RANKING_METHOD_INVALID")
    expected = ["net_expectancy_desc", "profit_factor_desc", "max_dd_pct_asc", "net_pnl_desc", "trade_count_desc"]
    if policy.get("ranking_fields") != expected:
        raise RuntimeError("SURVIVOR_POOL_RANKING_FIELDS_INVALID")
    for key in ("candidate_catalog_path", "legacy_incumbent_registry_path", "pool_state_path", "pool_event_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"SURVIVOR_POOL_PATH_MISSING:{key}")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("SURVIVOR_POOL_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_POOL_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED" or policy.get("exchange_order_submitted") is not False:
        raise RuntimeError("SURVIVOR_POOL_LIVE_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("SURVIVOR_POOL_MUTATION_FORBIDDEN")
    return dict(policy)


def _metrics(row: Mapping[str, Any]) -> dict[str, float]:
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        raise RuntimeError("SURVIVOR_POOL_METRICS_MISSING")
    return {
        "net_expectancy": _f(metrics.get("net_expectancy"), "net_expectancy"),
        "profit_factor": _f(metrics.get("profit_factor"), "profit_factor"),
        "net_pnl": _f(metrics.get("net_pnl"), "net_pnl"),
        "max_dd_pct": _f(metrics.get("max_dd_pct"), "max_dd_pct"),
        "trade_count": _f(metrics.get("trade_count"), "trade_count"),
    }


def _validated_candidate(row: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    if str(row.get("state") or "") != "PASS_ECONOMIC_SURVIVOR":
        raise RuntimeError("SURVIVOR_POOL_CANDIDATE_NOT_SURVIVOR")
    for key in ("economic_gate_pass", "durability_gate_pass", "integrity_pass"):
        if row.get(key) is not True:
            raise RuntimeError(f"SURVIVOR_POOL_CANDIDATE_GATE_FAIL:{key}")
    family_id = str(row.get("family_id") or "").strip()
    strategy_id = str(row.get("strategy_id") or "").strip()
    alpha_id = str(row.get("alpha_id") or "").strip()
    runtime_symbol = str(row.get("runtime_symbol") or "").replace("-", "").upper()
    if not family_id or not strategy_id or not alpha_id:
        raise RuntimeError("SURVIVOR_POOL_IDENTITY_MISSING")
    if runtime_symbol not in RUNTIME_SYMBOLS:
        raise RuntimeError("SURVIVOR_POOL_RUNTIME_SYMBOL_INVALID")
    if str(row.get("order_authority") or "BLOCKED") != "BLOCKED" or str(row.get("live_trade_authority") or "BLOCKED") != "BLOCKED":
        raise RuntimeError("SURVIVOR_POOL_CANDIDATE_LIVE_AUTHORITY_FORBIDDEN")
    hashes = row.get("source_hashes")
    if not isinstance(hashes, list) or not hashes or any(not str(v).strip() for v in hashes):
        raise RuntimeError("SURVIVOR_POOL_SOURCE_HASHES_INVALID")
    metrics = _metrics(row)
    canary_key = str(row.get("canary_key") or "").strip()
    contract_id = str(row.get("contract_id") or "").strip()
    contract_receipt = str(row.get("contract_receipt_sha256") or "").strip()
    canary_receipt = str(row.get("canary_receipt_sha256") or "").strip()
    verified_family = source == "SURVIVOR_CATALOG" and row.get("symbol_qualified") is True
    if verified_family and (not canary_key or not contract_id or len(contract_receipt) != 64 or len(canary_receipt) != 64):
        raise RuntimeError("SURVIVOR_POOL_FAMILY_LINEAGE_INCOMPLETE")
    risk = row.get("risk_request")
    risk_out = None
    if isinstance(risk, Mapping):
        risk_out = {"leverage_x": int(_f(risk.get("leverage_x"), "risk_request.leverage_x")), "position_pct": _f(risk.get("position_pct"), "risk_request.position_pct")}
    return {
        "family_id": family_id,
        "strategy_id": strategy_id,
        "alpha_id": alpha_id,
        "symbol_qualified": bool(row.get("symbol_qualified") is True),
        "runtime_symbol": runtime_symbol,
        "canary_key": canary_key or None,
        "contract_id": contract_id or None,
        "contract_receipt_sha256": contract_receipt or None,
        "canary_receipt_sha256": canary_receipt or None,
        "authority_receipt_sha256": str(row.get("authority_receipt_sha256") or ""),
        "source_hashes": sorted(set(str(v) for v in hashes)),
        "risk_request": risk_out,
        "metrics": metrics,
        "source": source,
    }


def _from_registry(registry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(registry, Mapping):
        return None
    if registry.get("schema_version") != REGISTRY_SCHEMA:
        raise RuntimeError("SURVIVOR_POOL_REGISTRY_SCHEMA_INVALID")
    authority = registry.get("current_authority")
    metrics = registry.get("current_metrics")
    if not isinstance(authority, Mapping) or not authority or not isinstance(metrics, Mapping):
        return None
    if authority.get("alpha_state") != "SURVIVOR_ACTIVE":
        return None
    runtime = authority.get("runtime_authority")
    if not isinstance(runtime, Mapping) or runtime.get("execution_authority") != "PAPER_SIM_ONLY":
        raise RuntimeError("SURVIVOR_POOL_REGISTRY_EXECUTION_INVALID")
    if runtime.get("order_authority") != "BLOCKED" or runtime.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_POOL_REGISTRY_LIVE_AUTHORITY_INVALID")
    strategy_id = str(authority.get("strategy_id") or "").strip()
    if not strategy_id:
        raise RuntimeError("SURVIVOR_POOL_REGISTRY_STRATEGY_ID_MISSING")
    family_id = str(authority.get("family_id") or strategy_id).strip()
    runtime_symbol = str(authority.get("symbol") or "").replace("-", "").upper()
    if runtime_symbol not in RUNTIME_SYMBOLS:
        return None
    source_hashes = authority.get("source_hashes")
    if not isinstance(source_hashes, list) or not source_hashes:
        raise RuntimeError("SURVIVOR_POOL_REGISTRY_SOURCE_HASHES_INVALID")
    synthetic = {
        "state": "PASS_ECONOMIC_SURVIVOR",
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "runtime_symbol": runtime_symbol,
        "family_id": family_id,
        "strategy_id": strategy_id,
        "alpha_id": str(authority.get("alpha_id") or "").strip(),
        "authority_receipt_sha256": str(authority.get("receipt_sha256") or ""),
        "source_hashes": list(source_hashes),
        "risk_request": authority.get("risk_request"),
        "metrics": dict(metrics),
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    return _validated_candidate(synthetic, source="LEGACY_INCUMBENT_REGISTRY")


def _rank_key(row: Mapping[str, Any]) -> tuple[float, float, float, float, float]:
    m = row["metrics"]
    return (
        float(m["net_expectancy"]),
        float(m["profit_factor"]),
        -float(m["max_dd_pct"]),
        float(m["net_pnl"]),
        float(m["trade_count"]),
    )


def _identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "family_id": row["family_id"],
        "strategy_id": row["strategy_id"],
        "alpha_id": row["alpha_id"],
        "symbol_qualified": row.get("symbol_qualified") is True,
        "runtime_symbol": row["runtime_symbol"],
        "canary_key": row.get("canary_key"),
        "contract_id": row.get("contract_id"),
        "contract_receipt_sha256": row.get("contract_receipt_sha256"),
        "canary_receipt_sha256": row.get("canary_receipt_sha256"),
        "authority_receipt_sha256": row.get("authority_receipt_sha256"),
        "source_hashes": list(row.get("source_hashes") or []),
        "risk_request": None if row.get("risk_request") is None else dict(row["risk_request"]),
        "metrics": dict(row["metrics"]),
        "source": row.get("source"),
    }


def pool_tick(
    policy: Mapping[str, Any],
    *,
    catalog: Mapping[str, Any] | None,
    incumbent_registry: Mapping[str, Any] | None,
    previous_pool: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    candidates: list[dict[str, Any]] = []

    if catalog is not None:
        if catalog.get("schema_version") != CATALOG_SCHEMA:
            raise RuntimeError("SURVIVOR_POOL_CATALOG_SCHEMA_INVALID")
        rows = catalog.get("survivors")
        if not isinstance(rows, list):
            raise RuntimeError("SURVIVOR_POOL_CATALOG_ROWS_INVALID")
        for row in rows:
            if not isinstance(row, Mapping):
                raise RuntimeError("SURVIVOR_POOL_CATALOG_ROW_INVALID")
            candidates.append(_validated_candidate(row, source="SURVIVOR_CATALOG"))

    incumbent = _from_registry(incumbent_registry)
    if incumbent is not None:
        candidates.append(incumbent)

    best_by_family: dict[str, dict[str, Any]] = {}
    for row in candidates:
        family_id = row["family_id"]
        current = best_by_family.get(family_id)
        if current is None or _rank_key(row) > _rank_key(current):
            best_by_family[family_id] = row

    ranked = sorted(best_by_family.values(), key=_rank_key, reverse=True)
    active_n = int(cfg["active_target"])
    reserve_n = int(cfg["reserve_target"])
    active = [_identity(v) for v in ranked[:active_n]]
    reserve = [_identity(v) for v in ranked[active_n:active_n + reserve_n]]
    target_reached = len(active) == active_n and len(reserve) == reserve_n

    state = {
        "schema_version": SCHEMA,
        "state": "PASS_SURVIVOR_POOL_TARGET_3_PLUS_2" if target_reached else "HOLD_SURVIVOR_POOL_BUILDING",
        "action": "hold",
        "active_target": active_n,
        "reserve_target": reserve_n,
        "active_count": len(active),
        "reserve_count": len(reserve),
        "verified_family_count": len(ranked),
        "active": active,
        "reserve": reserve,
        "ranking_method": cfg["ranking_method"],
        "ranking_fields": list(cfg["ranking_fields"]),
        "diversity_state": "STRUCTURAL_FAMILY_DISTINCT_ONLY",
        "statistical_independence_claimed": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now,
    }
    state["receipt_sha256"] = stable_sha(state)

    previous_active = []
    previous_reserve = []
    previous_target = False
    if isinstance(previous_pool, Mapping) and previous_pool.get("schema_version") == SCHEMA:
        previous_active = [(str(v.get("alpha_id")), str(v.get("runtime_symbol"))) for v in previous_pool.get("active") or [] if isinstance(v, Mapping)]
        previous_reserve = [(str(v.get("alpha_id")), str(v.get("runtime_symbol"))) for v in previous_pool.get("reserve") or [] if isinstance(v, Mapping)]
        previous_target = str(previous_pool.get("state") or "") == "PASS_SURVIVOR_POOL_TARGET_3_PLUS_2"
    current_active = [(str(v.get("alpha_id")), str(v.get("runtime_symbol"))) for v in active]
    current_reserve = [(str(v.get("alpha_id")), str(v.get("runtime_symbol"))) for v in reserve]

    changed = previous_active != current_active or previous_reserve != current_reserve or (target_reached and not previous_target)
    event = None
    if changed:
        event_type = "POOL_TARGET_3_PLUS_2_REACHED" if target_reached and not previous_target else "SURVIVOR_POOL_CHANGED"
        event = {
            "schema_version": "zel.production_survivor_pool_event.v1",
            "state": "PASS_SURVIVOR_POOL_EVENT",
            "event_type": event_type,
            "previous_active": previous_active,
            "current_active": current_active,
            "previous_reserve": previous_reserve,
            "current_reserve": current_reserve,
            "active_count": len(active),
            "reserve_count": len(reserve),
            "pool_receipt_sha256": state["receipt_sha256"],
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "created_at_ms": now,
        }
        event["receipt_sha256"] = stable_sha(event)
    return state, event


def main() -> int:
    ap = argparse.ArgumentParser(description="ZEL deterministic symbol-qualified multi-survivor 3+2 pool")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args()
    policy = read_json(ns.policy, required=True)
    assert policy is not None
    cfg = validate_policy(policy)
    catalog = read_json(Path(str(cfg["candidate_catalog_path"])))
    incumbent = read_json(Path(str(cfg["legacy_incumbent_registry_path"])))
    pool_path = Path(str(cfg["pool_state_path"]))
    previous = read_json(pool_path)
    state, event = pool_tick(cfg, catalog=catalog, incumbent_registry=incumbent, previous_pool=previous)
    atomic_json_write(pool_path, state)
    if event is not None:
        atomic_json_write(Path(str(cfg["pool_event_path"])), event)
    print(json.dumps({
        "state": state["state"],
        "active_count": state["active_count"],
        "reserve_count": state["reserve_count"],
        "event_type": None if event is None else event["event_type"],
        "receipt_sha256": state["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

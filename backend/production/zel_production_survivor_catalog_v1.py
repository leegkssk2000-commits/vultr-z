from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Mapping

from backend.production.zel_production_improvement_controller_v1 import atomic_json_write, read_json, stable_sha

SCHEMA = "zel.production_survivor_catalog.v1"
POLICY_SCHEMA = "zel.production_survivor_catalog_policy.v1"
INTAKE_SCHEMA = "zel.production_verified_survivor_receipt.v1"
REGISTRY_SCHEMA = "zel.production_incumbent_registry.v1"
DEFAULT_POLICY = Path("config/zel_production_survivor_catalog_v1.json")


def _f(value: Any, name: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"SURVIVOR_CATALOG_NUMERIC_INVALID:{name}") from exc
    if not math.isfinite(out):
        raise RuntimeError(f"SURVIVOR_CATALOG_NUMERIC_NONFINITE:{name}")
    return out


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("schema_version") != POLICY_SCHEMA:
        raise RuntimeError("SURVIVOR_CATALOG_POLICY_SCHEMA_INVALID")
    if str(policy.get("mode") or "").upper() != "PAPER":
        raise RuntimeError("SURVIVOR_CATALOG_NON_PAPER_FORBIDDEN")
    for key in ("legacy_incumbent_registry_path", "verified_survivor_intake_path", "catalog_path", "event_path"):
        if not str(policy.get(key) or "").strip():
            raise RuntimeError(f"SURVIVOR_CATALOG_PATH_MISSING:{key}")
    if policy.get("distinct_family_required") is not True:
        raise RuntimeError("SURVIVOR_CATALOG_DISTINCT_FAMILY_REQUIRED")
    if policy.get("ranking_method") != "LEXICOGRAPHIC_NO_WEIGHT":
        raise RuntimeError("SURVIVOR_CATALOG_RANKING_INVALID")
    expected = ["net_expectancy_desc", "profit_factor_desc", "max_dd_pct_asc", "net_pnl_desc", "trade_count_desc"]
    if policy.get("ranking_fields") != expected:
        raise RuntimeError("SURVIVOR_CATALOG_RANKING_FIELDS_INVALID")
    if policy.get("selection_authority") is not False or policy.get("promotion_authority") is not False:
        raise RuntimeError("SURVIVOR_CATALOG_AUTHORITY_FORBIDDEN")
    if policy.get("execution_authority") != "NONE" or policy.get("order_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_CATALOG_EXECUTION_FORBIDDEN")
    if policy.get("live_trade_authority") != "BLOCKED" or policy.get("exchange_order_submitted") is not False:
        raise RuntimeError("SURVIVOR_CATALOG_LIVE_FORBIDDEN")
    if policy.get("source_code_mutation_allowed") is not False or policy.get("self_modification_allowed") is not False:
        raise RuntimeError("SURVIVOR_CATALOG_MUTATION_FORBIDDEN")
    return dict(policy)


def _metrics(row: Mapping[str, Any]) -> dict[str, float]:
    metrics = row.get("metrics")
    if not isinstance(metrics, Mapping):
        raise RuntimeError("SURVIVOR_CATALOG_METRICS_MISSING")
    out = {
        "net_expectancy": _f(metrics.get("net_expectancy"), "net_expectancy"),
        "profit_factor": _f(metrics.get("profit_factor"), "profit_factor"),
        "max_dd_pct": _f(metrics.get("max_dd_pct"), "max_dd_pct"),
        "net_pnl": _f(metrics.get("net_pnl"), "net_pnl"),
        "trade_count": _f(metrics.get("trade_count"), "trade_count"),
    }
    if out["trade_count"] <= 0:
        raise RuntimeError("SURVIVOR_CATALOG_TRADE_COUNT_NONPOSITIVE")
    return out


def _rank_key(row: Mapping[str, Any]) -> tuple[float, float, float, float, float]:
    m = row["metrics"]
    return (
        float(m["net_expectancy"]),
        float(m["profit_factor"]),
        -float(m["max_dd_pct"]),
        float(m["net_pnl"]),
        float(m["trade_count"]),
    )


def _validate_survivor(row: Mapping[str, Any], *, source: str) -> dict[str, Any]:
    if str(row.get("state") or "") != "PASS_ECONOMIC_SURVIVOR":
        raise RuntimeError("SURVIVOR_CATALOG_INTAKE_NOT_SURVIVOR")
    for key in ("economic_gate_pass", "durability_gate_pass", "integrity_pass"):
        if row.get(key) is not True:
            raise RuntimeError(f"SURVIVOR_CATALOG_GATE_FAIL:{key}")
    family_id = str(row.get("family_id") or "").strip()
    strategy_id = str(row.get("strategy_id") or "").strip()
    alpha_id = str(row.get("alpha_id") or "").strip()
    if not family_id or not strategy_id or not alpha_id:
        raise RuntimeError("SURVIVOR_CATALOG_IDENTITY_MISSING")
    hashes = row.get("source_hashes")
    if not isinstance(hashes, list) or not hashes or any(not str(v).strip() for v in hashes):
        raise RuntimeError("SURVIVOR_CATALOG_SOURCE_HASHES_INVALID")
    receipt = str(row.get("authority_receipt_sha256") or "").strip()
    if not receipt:
        raise RuntimeError("SURVIVOR_CATALOG_AUTHORITY_RECEIPT_MISSING")
    if row.get("selection_authority") not in (None, False) or row.get("promotion_authority") not in (None, False):
        raise RuntimeError("SURVIVOR_CATALOG_INPUT_AUTHORITY_FORBIDDEN")
    if str(row.get("order_authority") or "BLOCKED") != "BLOCKED":
        raise RuntimeError("SURVIVOR_CATALOG_INPUT_ORDER_AUTHORITY_INVALID")
    if str(row.get("live_trade_authority") or "BLOCKED") != "BLOCKED":
        raise RuntimeError("SURVIVOR_CATALOG_INPUT_LIVE_AUTHORITY_INVALID")
    return {
        "state": "PASS_ECONOMIC_SURVIVOR",
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "family_id": family_id,
        "strategy_id": strategy_id,
        "alpha_id": alpha_id,
        "authority_receipt_sha256": receipt,
        "source_hashes": sorted(set(str(v) for v in hashes)),
        "metrics": _metrics(row),
        "source": source,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
    }


def _from_registry(registry: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(registry, Mapping):
        return None
    if registry.get("schema_version") != REGISTRY_SCHEMA:
        raise RuntimeError("SURVIVOR_CATALOG_REGISTRY_SCHEMA_INVALID")
    authority = registry.get("current_authority")
    metrics = registry.get("current_metrics")
    if not isinstance(authority, Mapping) or not authority or not isinstance(metrics, Mapping):
        return None
    if authority.get("alpha_state") != "SURVIVOR_ACTIVE":
        return None
    runtime = authority.get("runtime_authority")
    if not isinstance(runtime, Mapping) or runtime.get("execution_authority") != "PAPER_SIM_ONLY":
        raise RuntimeError("SURVIVOR_CATALOG_REGISTRY_EXECUTION_INVALID")
    if runtime.get("order_authority") != "BLOCKED" or runtime.get("live_trade_authority") != "BLOCKED":
        raise RuntimeError("SURVIVOR_CATALOG_REGISTRY_LIVE_INVALID")
    strategy_id = str(authority.get("strategy_id") or "").strip()
    family_id = str(authority.get("family_id") or strategy_id).strip()
    alpha_id = str(authority.get("alpha_id") or "").strip()
    hashes = authority.get("source_hashes")
    if not strategy_id or not family_id or not alpha_id or not isinstance(hashes, list) or not hashes:
        raise RuntimeError("SURVIVOR_CATALOG_REGISTRY_IDENTITY_INVALID")
    synthetic = {
        "state": "PASS_ECONOMIC_SURVIVOR",
        "economic_gate_pass": True,
        "durability_gate_pass": True,
        "integrity_pass": True,
        "family_id": family_id,
        "strategy_id": strategy_id,
        "alpha_id": alpha_id,
        "authority_receipt_sha256": str(authority.get("receipt_sha256") or ""),
        "source_hashes": list(hashes),
        "metrics": dict(metrics),
        "selection_authority": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }
    return _validate_survivor(synthetic, source="INCUMBENT_REGISTRY")


def _from_intake(intake: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(intake, Mapping):
        return None
    if intake.get("schema_version") != INTAKE_SCHEMA:
        raise RuntimeError("SURVIVOR_CATALOG_INTAKE_SCHEMA_INVALID")
    return _validate_survivor(intake, source="VERIFIED_SURVIVOR_INTAKE")


def _existing_rows(catalog: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if catalog is None:
        return []
    if catalog.get("schema_version") != SCHEMA:
        raise RuntimeError("SURVIVOR_CATALOG_EXISTING_SCHEMA_INVALID")
    rows = catalog.get("survivors")
    if not isinstance(rows, list):
        raise RuntimeError("SURVIVOR_CATALOG_EXISTING_ROWS_INVALID")
    return [_validate_survivor(v, source=str(v.get("source") or "CATALOG")) for v in rows if isinstance(v, Mapping)]


def catalog_tick(
    policy: Mapping[str, Any],
    *,
    catalog: Mapping[str, Any] | None,
    incumbent_registry: Mapping[str, Any] | None,
    intake: Mapping[str, Any] | None,
    now_ms: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cfg = validate_policy(policy)
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    rows = _existing_rows(catalog)
    incoming = [v for v in (_from_registry(incumbent_registry), _from_intake(intake)) if v is not None]

    best_by_family: dict[str, dict[str, Any]] = {}
    for row in rows + incoming:
        family = row["family_id"]
        current = best_by_family.get(family)
        if current is None or _rank_key(row) > _rank_key(current):
            best_by_family[family] = row

    ranked = sorted(best_by_family.values(), key=_rank_key, reverse=True)
    previous_ids = [(v["family_id"], v["alpha_id"], v["authority_receipt_sha256"]) for v in rows]
    current_ids = [(v["family_id"], v["alpha_id"], v["authority_receipt_sha256"]) for v in ranked]
    changed = previous_ids != current_ids
    state = {
        "schema_version": SCHEMA,
        "state": "PASS_SURVIVOR_CATALOG_UPDATED" if changed else "HOLD_SURVIVOR_CATALOG_UNCHANGED",
        "action": "hold",
        "family_count": len(ranked),
        "survivors": ranked,
        "ranking_method": cfg["ranking_method"],
        "ranking_fields": list(cfg["ranking_fields"]),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "updated_at_ms": now,
    }
    state["receipt_sha256"] = stable_sha(state)
    event = None
    if changed:
        event = {
            "schema_version": "zel.production_survivor_catalog_event.v1",
            "state": "PASS_SURVIVOR_CATALOG_EVENT",
            "event_type": "SURVIVOR_FAMILY_CATALOG_CHANGED",
            "previous_family_count": len(rows),
            "current_family_count": len(ranked),
            "families": [v["family_id"] for v in ranked],
            "catalog_receipt_sha256": state["receipt_sha256"],
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
            "exchange_order_submitted": False,
            "created_at_ms": now,
        }
        event["receipt_sha256"] = stable_sha(event)
    return state, event


def main() -> int:
    ap = argparse.ArgumentParser(description="ZEL verified multi-family survivor catalog writer")
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ns = ap.parse_args()
    policy = read_json(ns.policy, required=True)
    assert policy is not None
    cfg = validate_policy(policy)
    catalog_path = Path(str(cfg["catalog_path"]))
    state, event = catalog_tick(
        cfg,
        catalog=read_json(catalog_path),
        incumbent_registry=read_json(Path(str(cfg["legacy_incumbent_registry_path"]))),
        intake=read_json(Path(str(cfg["verified_survivor_intake_path"]))),
    )
    atomic_json_write(catalog_path, state)
    if event is not None:
        atomic_json_write(Path(str(cfg["event_path"])), event)
    print(json.dumps({
        "state": state["state"],
        "family_count": state["family_count"],
        "event_type": None if event is None else event["event_type"],
        "receipt_sha256": state["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

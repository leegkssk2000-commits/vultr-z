#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_top5_additive_entry_union_v1 import evaluate

ROOT = Path(__file__).resolve().parents[3]
INCUMBENT = ROOT / "backend/research/rebuild/a1_supertrend_5455_research_incumbent_v1.json"
BOUNDARY = ROOT / "backend/research/rebuild/a1_supertrend_5455_add_only_boundary_v1.json"
BASE_PARENT = ROOT / "backend/research/rebuild/a1_supertrend_pullback_highwr_frozen_parent_v1.json"
SCHEMA = "zel.a1.supertrend.5455.add_only_continuation.v1"
STRATEGY = "supertrend_pullback"
RULE_HOUR = 0
FRESH_TARGET = 25


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def semantic_key(trade: Mapping[str, Any]) -> tuple[str, int, int, str]:
    return str(trade["symbol"]), int(trade["signal_ts"]), int(trade["entry_ts"]), str(trade["side"])


def row_key(row: Any) -> tuple[str, int, int, str]:
    if not isinstance(row, list) or len(row) != 4:
        raise RuntimeError("SEMANTIC_KEY_ROW_INVALID")
    return str(row[0]), int(row[1]), int(row[2]), str(row[3])


def signal_hour_utc(trade: Mapping[str, Any]) -> int:
    return datetime.fromtimestamp(int(trade["signal_ts"]) / 1000.0, tz=timezone.utc).hour


def payoff(trades: list[Mapping[str, Any]]) -> float | None:
    vals = [float(x["net_bps"]) for x in trades]
    wins = [x for x in vals if x > 0.0]
    losses = [-x for x in vals if x < 0.0]
    if not wins or not losses:
        return None
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def validate_incumbent(inc: Mapping[str, Any]) -> None:
    if inc.get("schema_version") != "zel.a1.supertrend.research_incumbent_5455.v1":
        raise RuntimeError("SUPERTREND_5455_INCUMBENT_SCHEMA_MISMATCH")
    if inc.get("strategy_id") != STRATEGY:
        raise RuntimeError("SUPERTREND_5455_INCUMBENT_STRATEGY_MISMATCH")
    supplied = str(inc.get("receipt_sha256") or "")
    core = dict(inc)
    core.pop("receipt_sha256", None)
    if supplied != stable(core):
        raise RuntimeError("SUPERTREND_5455_INCUMBENT_RECEIPT_MISMATCH")
    metrics = inc.get("metrics") or {}
    expected = {
        "trades": 11,
        "win_rate": 6 / 11,
        "net_pnl_bps": 8987.160536440786,
        "net_expectancy_bps": 817.0145942218896,
        "profit_factor": 12.301261556184716,
        "drawdown_bps": 245.7358707597723,
    }
    for key, value in expected.items():
        actual = metrics.get(key)
        if key == "trades":
            if int(actual or -1) != value:
                raise RuntimeError(f"SUPERTREND_5455_INCUMBENT_METRIC_MISMATCH:{key}:{actual}:{value}")
        elif actual is None or abs(float(actual) - float(value)) > 1e-9 * max(1.0, abs(float(value))):
            raise RuntimeError(f"SUPERTREND_5455_INCUMBENT_METRIC_MISMATCH:{key}:{actual}:{value}")
    construction = inc.get("construction") or {}
    if construction.get("predicate") != {"field": "signal_hour_utc", "op": "eq", "value": 0}:
        raise RuntimeError("SUPERTREND_5455_INCUMBENT_RULE_MISMATCH")
    if construction.get("parent_mutation") is not False or construction.get("post_outcome_trade_cherry_pick") is not False:
        raise RuntimeError("SUPERTREND_5455_INCUMBENT_MUTATION_CONTRACT_INVALID")


def materialize_incumbent(inc: Mapping[str, Any], base_parent: Mapping[str, Any]) -> dict[str, Any]:
    expected = inc.get("base_parent") or {}
    if base_parent.get("strategy_id") != STRATEGY:
        raise RuntimeError("SUPERTREND_5455_BASE_PARENT_STRATEGY_MISMATCH")
    if str(base_parent.get("receipt_sha256") or "") != str(expected.get("receipt_sha256") or ""):
        raise RuntimeError("SUPERTREND_5455_BASE_PARENT_RECEIPT_MISMATCH")
    base_trades = [dict(x) for x in base_parent.get("trades") or []]
    if len(base_trades) != int(expected.get("trade_count") or -1):
        raise RuntimeError("SUPERTREND_5455_BASE_PARENT_COUNT_MISMATCH")
    added = [dict(x) for x in (inc.get("construction") or {}).get("added_trades") or []]
    trades = base_trades + added
    actual_keys = [list(semantic_key(x)) for x in trades]
    if actual_keys != (inc.get("semantic_trade_keys") or []):
        raise RuntimeError("SUPERTREND_5455_MATERIALIZED_KEY_ORDER_MISMATCH")
    return {"strategy_id": STRATEGY, "trades": trades}


def validate_boundary(incumbent_receipt: Mapping[str, Any], boundary: Mapping[str, Any]) -> set[tuple[str, int, int, str]]:
    if boundary.get("schema_version") != "zel.a1.supertrend.5455.add_only_boundary.v1":
        raise RuntimeError("SUPERTREND_5455_BOUNDARY_SCHEMA_MISMATCH")
    supplied = str(boundary.get("receipt_sha256") or "")
    core = dict(boundary)
    core.pop("receipt_sha256", None)
    if supplied != stable(core):
        raise RuntimeError("SUPERTREND_5455_BOUNDARY_RECEIPT_MISMATCH")
    if str(boundary.get("research_incumbent_receipt_sha256") or "") != str(read(INCUMBENT).get("receipt_sha256") or ""):
        raise RuntimeError("SUPERTREND_5455_BOUNDARY_INCUMBENT_BIND_MISMATCH")
    freeze = boundary.get("validation_freeze") or {}
    rows = freeze.get("semantic_trade_keys") or []
    baseline = {row_key(x) for x in rows}
    if int(freeze.get("trade_count") or -1) != 59 or len(baseline) != 59:
        raise RuntimeError(f"SUPERTREND_5455_EXPECTED_59T_BOUNDARY:{len(baseline)}")
    if str(freeze.get("broad_parent_receipt_sha256") or "") != "4d0d8a70b56b41d21382b2a653978cc0407e8f6219603fba27119c841fa1d243":
        raise RuntimeError("SUPERTREND_5455_BOUNDARY_BROAD_RECEIPT_MISMATCH")
    incumbent_keys = {semantic_key(x) for x in incumbent_receipt.get("trades") or []}
    if len(incumbent_keys) != 11 or not incumbent_keys.issubset(baseline):
        raise RuntimeError("SUPERTREND_5455_INCUMBENT_NOT_INSIDE_59T_BOUNDARY")
    return baseline


def run(current: Mapping[str, Any], incumbent: Mapping[str, Any], base_parent: Mapping[str, Any], boundary: Mapping[str, Any]) -> dict[str, Any]:
    validate_incumbent(incumbent)
    incumbent_receipt = materialize_incumbent(incumbent, base_parent)
    baseline = validate_boundary(incumbent_receipt, boundary)
    if current.get("strategy_id") != STRATEGY:
        raise RuntimeError("SUPERTREND_5455_CURRENT_STRATEGY_MISMATCH")
    current_trades = [dict(x) for x in current.get("trades") or []]
    if len(current_trades) != int(current.get("completed_trades") or -1):
        raise RuntimeError("SUPERTREND_5455_CURRENT_COUNT_MISMATCH")
    current_by: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for trade in current_trades:
        key = semantic_key(trade)
        if key in current_by:
            raise RuntimeError(f"SUPERTREND_5455_DUPLICATE_CURRENT_KEY:{key}")
        current_by[key] = trade
    current_keys = set(current_by)
    if not baseline.issubset(current_keys):
        missing = sorted(baseline - current_keys, key=str)
        raise RuntimeError(f"SUPERTREND_5455_59T_BOUNDARY_KEYS_MISSING:{missing[:3]}:{len(missing)}")

    fresh_keys = current_keys - baseline
    fresh_all = [current_by[k] for k in sorted(fresh_keys, key=str)]
    fresh_accepted = [x for x in fresh_all if signal_hour_utc(x) == RULE_HOUR]
    fresh_rejected = [x for x in fresh_all if signal_hour_utc(x) != RULE_HOUR]

    additive = evaluate(incumbent_receipt, {"strategy_id": STRATEGY, "trades": fresh_accepted})
    incumbent_trades = [dict(x) for x in incumbent_receipt.get("trades") or []]
    combined_trades = incumbent_trades + fresh_accepted
    parent_payoff = payoff(incumbent_trades)
    combined_payoff = payoff(combined_trades)
    payoff_non_decrease = parent_payoff is None or (combined_payoff is not None and combined_payoff >= parent_payoff)
    strict_economic_pass = additive["state"] == "PASS_ADD_ONLY_ENTRY_LANE" and payoff_non_decrease
    fresh_sample_ready = len(fresh_accepted) >= FRESH_TARGET

    blockers: list[str] = []
    if not fresh_accepted:
        blockers.append("NO_FRESH_APAC_OPEN_POINT_T")
    if fresh_accepted and additive["state"] != "PASS_ADD_ONLY_ENTRY_LANE":
        blockers.extend(additive.get("failed_checks") or ["ADD_ONLY_ECONOMIC_GATE"])
    if fresh_accepted and not payoff_non_decrease:
        blockers.append("PAYOFF_DECREASE")
    if len(fresh_accepted) < FRESH_TARGET:
        blockers.append(f"FRESH_ACCEPTED_LT_{FRESH_TARGET}")

    if strict_economic_pass and fresh_sample_ready:
        state = "PASS_SUPERTREND_5455_FRESH25_ADD_ONLY_DEVELOPMENT_READY"
    elif strict_economic_pass:
        state = "COLLECT_SUPERTREND_5455_FRESH_ADD_ONLY_ECONOMIC_PASS"
    elif not fresh_accepted:
        state = "WAIT_SUPERTREND_5455_FRESH_APAC_OPEN_POINT"
    else:
        state = "HOLD_SUPERTREND_5455_FRESH_ADD_ONLY_ECONOMIC"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": STRATEGY,
        "research_incumbent_receipt_sha256": incumbent.get("receipt_sha256"),
        "research_incumbent_metrics": incumbent.get("metrics"),
        "prospective_boundary_trade_count": len(baseline),
        "prospective_boundary_receipt_sha256": (boundary.get("validation_freeze") or {}).get("broad_parent_receipt_sha256"),
        "changed_axis": "ADD_ONLY_SESSION_APAC_OPEN_POINT",
        "predicate": {"field": "signal_hour_utc", "op": "eq", "value": RULE_HOUR},
        "current_broad_parent_T": len(current_trades),
        "fresh_all_T": len(fresh_all),
        "fresh_accepted_T": len(fresh_accepted),
        "fresh_rejected_T": len(fresh_rejected),
        "fresh_target_T": FRESH_TARGET,
        "fresh_sample_ready": fresh_sample_ready,
        "strict_economic_pass": strict_economic_pass,
        "payoff": {"parent": parent_payoff, "combined": combined_payoff, "non_decrease": payoff_non_decrease},
        "additive_receipt": additive,
        "promotion_blockers": sorted(set(blockers)),
        "policy": {
            "research_incumbent_is_11T_54p55": True,
            "production_ssot_unchanged": True,
            "parent_match_required_pct": 100.0,
            "parent_trade_delete_forbidden": True,
            "parent_trade_rewrite_forbidden": True,
            "append_only_new_trades": True,
            "prospective_only_after_59T_boundary": True,
            "outcome_blind_rule": True,
            "numeric_threshold_sweep": False,
            "post_outcome_trade_deletion": False,
            "wr_pnl_expectancy_pf_payoff_non_decrease_required": True,
            "dd_non_increase_required": True,
            "fresh25_required_before_development_ready": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    return result


def self_test() -> int:
    inc = read(INCUMBENT)
    base = read(BASE_PARENT)
    boundary = read(BOUNDARY)
    validate_incumbent(inc)
    materialized = materialize_incumbent(inc, base)
    baseline = validate_boundary(materialized, boundary)
    assert len(baseline) == 59
    assert len(materialized.get("trades") or []) == 11
    assert abs(float((inc.get("metrics") or {})["win_rate"]) - 6 / 11) < 1e-12
    assert int((boundary.get("validation_freeze") or {}).get("pre_freeze_new_since_discovery_apac_open_point_count") or -1) == 0
    print("PASS_A1_SUPERTREND_5455_ADD_ONLY_CONTINUATION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_supertrend_5455_add_only_continuation_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.current_parent is None:
        raise RuntimeError("--current-parent required")
    result = run(read(args.current_parent), read(INCUMBENT), read(BASE_PARENT), read(BOUNDARY))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    brief = {
        "state": result["state"],
        "incumbent_T": result["research_incumbent_metrics"]["trades"],
        "incumbent_WR": result["research_incumbent_metrics"]["win_rate"],
        "fresh_all_T": result["fresh_all_T"],
        "fresh_accepted_T": result["fresh_accepted_T"],
        "combined_T": result["additive_receipt"]["combined_trade_count"],
        "combined_metrics": result["additive_receipt"]["combined_metrics"],
        "payoff": result["payoff"],
        "blockers": result["promotion_blockers"],
        "receipt": result["receipt_sha256"],
    }
    print("A1_SUPERTREND_5455_ADD_ONLY=" + json.dumps(brief, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

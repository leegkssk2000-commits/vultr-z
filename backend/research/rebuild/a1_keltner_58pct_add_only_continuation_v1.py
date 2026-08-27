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
INCUMBENT = ROOT / "backend/research/rebuild/a1_keltner_58pct_research_incumbent_v1.json"
BOUNDARY = ROOT / "backend/research/rebuild/a1_keltner_add_only_quality_anchor_v1.json"
BASE_PARENT = ROOT / "backend/research/rebuild/a1_keltner_trend_highwr_frozen_parent_v1.json"
SCHEMA = "zel.a1.keltner.58pct.add_only_continuation.v1"
STRATEGY = "keltner_trend"
RULE_HOURS = (16, 17, 18)
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
    if inc.get("schema_version") != "zel.a1.keltner.research_incumbent_58pct.v1":
        raise RuntimeError("KELTNER_58_INCUMBENT_SCHEMA_MISMATCH")
    if inc.get("strategy_id") != STRATEGY:
        raise RuntimeError("KELTNER_58_INCUMBENT_STRATEGY_MISMATCH")
    supplied = str(inc.get("receipt_sha256") or "")
    core = dict(inc)
    core.pop("receipt_sha256", None)
    if supplied != stable(core):
        raise RuntimeError("KELTNER_58_INCUMBENT_RECEIPT_MISMATCH")
    metrics = inc.get("metrics") or {}
    expected = {
        "trades": 12,
        "win_rate": 7 / 12,
        "net_pnl_bps": 16213.02695520102,
        "net_expectancy_bps": 1351.085579600085,
        "profit_factor": 31.35081608201582,
        "drawdown_bps": 212.6882556068265,
    }
    for key, value in expected.items():
        actual = metrics.get(key)
        if key == "trades":
            if int(actual or -1) != value:
                raise RuntimeError(f"KELTNER_58_INCUMBENT_METRIC_MISMATCH:{key}:{actual}:{value}")
        elif actual is None or abs(float(actual) - float(value)) > 1e-9 * max(1.0, abs(float(value))):
            raise RuntimeError(f"KELTNER_58_INCUMBENT_METRIC_MISMATCH:{key}:{actual}:{value}")
    construction = inc.get("construction") or {}
    if construction.get("predicate") != {"field": "signal_hour_utc", "op": "in", "value": [16, 17, 18]}:
        raise RuntimeError("KELTNER_58_INCUMBENT_RULE_MISMATCH")
    if construction.get("parent_mutation") is not False or construction.get("post_outcome_trade_cherry_pick") is not False:
        raise RuntimeError("KELTNER_58_INCUMBENT_MUTATION_CONTRACT_INVALID")


def materialize_incumbent(inc: Mapping[str, Any], base_parent: Mapping[str, Any]) -> dict[str, Any]:
    expected = inc.get("base_parent") or {}
    if base_parent.get("strategy_id") != STRATEGY:
        raise RuntimeError("KELTNER_58_BASE_PARENT_STRATEGY_MISMATCH")
    if str(base_parent.get("receipt_sha256") or "") != str(expected.get("receipt_sha256") or ""):
        raise RuntimeError("KELTNER_58_BASE_PARENT_RECEIPT_MISMATCH")
    base_trades = [dict(x) for x in base_parent.get("trades") or []]
    if len(base_trades) != int(expected.get("trade_count") or -1):
        raise RuntimeError("KELTNER_58_BASE_PARENT_COUNT_MISMATCH")
    added = [dict(x) for x in (inc.get("construction") or {}).get("added_trades") or []]
    trades = base_trades + added
    actual_keys = [list(semantic_key(x)) for x in trades]
    if actual_keys != (inc.get("semantic_trade_keys") or []):
        raise RuntimeError("KELTNER_58_MATERIALIZED_KEY_ORDER_MISMATCH")
    return {"strategy_id": STRATEGY, "trades": trades}


def validate_boundary(incumbent_receipt: Mapping[str, Any], boundary: Mapping[str, Any]) -> set[tuple[str, int, int, str]]:
    freeze = boundary.get("validation_freeze") or {}
    rows = freeze.get("semantic_trade_keys") or []
    baseline = {row_key(x) for x in rows}
    if len(baseline) != 66:
        raise RuntimeError(f"KELTNER_58_EXPECTED_66T_BOUNDARY:{len(baseline)}")
    incumbent_keys = {semantic_key(x) for x in incumbent_receipt.get("trades") or []}
    if len(incumbent_keys) != 12 or not incumbent_keys.issubset(baseline):
        raise RuntimeError("KELTNER_58_INCUMBENT_NOT_INSIDE_66T_BOUNDARY")
    return baseline


def run(current: Mapping[str, Any], incumbent: Mapping[str, Any], base_parent: Mapping[str, Any], boundary: Mapping[str, Any]) -> dict[str, Any]:
    validate_incumbent(incumbent)
    incumbent_receipt = materialize_incumbent(incumbent, base_parent)
    baseline = validate_boundary(incumbent_receipt, boundary)
    if current.get("strategy_id") != STRATEGY:
        raise RuntimeError("KELTNER_58_CURRENT_STRATEGY_MISMATCH")
    current_trades = [dict(x) for x in current.get("trades") or []]
    if len(current_trades) != int(current.get("completed_trades") or -1):
        raise RuntimeError("KELTNER_58_CURRENT_COUNT_MISMATCH")
    current_by: dict[tuple[str, int, int, str], dict[str, Any]] = {}
    for trade in current_trades:
        key = semantic_key(trade)
        if key in current_by:
            raise RuntimeError(f"KELTNER_58_DUPLICATE_CURRENT_KEY:{key}")
        current_by[key] = trade
    current_keys = set(current_by)
    if not baseline.issubset(current_keys):
        missing = sorted(baseline - current_keys, key=str)
        raise RuntimeError(f"KELTNER_58_66T_BOUNDARY_KEYS_MISSING:{missing[:3]}:{len(missing)}")

    fresh_keys = current_keys - baseline
    fresh_all = [current_by[k] for k in sorted(fresh_keys, key=str)]
    fresh_accepted = [x for x in fresh_all if signal_hour_utc(x) in RULE_HOURS]
    fresh_rejected = [x for x in fresh_all if signal_hour_utc(x) not in RULE_HOURS]

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
        blockers.append("NO_FRESH_US_OPEN_3H_T")
    if fresh_accepted and additive["state"] != "PASS_ADD_ONLY_ENTRY_LANE":
        blockers.extend(additive.get("failed_checks") or ["ADD_ONLY_ECONOMIC_GATE"])
    if fresh_accepted and not payoff_non_decrease:
        blockers.append("PAYOFF_DECREASE")
    if len(fresh_accepted) < FRESH_TARGET:
        blockers.append(f"FRESH_ACCEPTED_LT_{FRESH_TARGET}")

    if strict_economic_pass and fresh_sample_ready:
        state = "PASS_KELTNER_58_FRESH25_ADD_ONLY_DEVELOPMENT_READY"
    elif strict_economic_pass:
        state = "COLLECT_KELTNER_58_FRESH_ADD_ONLY_ECONOMIC_PASS"
    elif not fresh_accepted:
        state = "WAIT_KELTNER_58_FRESH_US_OPEN_3H"
    else:
        state = "HOLD_KELTNER_58_FRESH_ADD_ONLY_ECONOMIC"

    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": STRATEGY,
        "research_incumbent_receipt_sha256": incumbent.get("receipt_sha256"),
        "research_incumbent_metrics": incumbent.get("metrics"),
        "prospective_boundary_trade_count": len(baseline),
        "prospective_boundary_receipt_sha256": (boundary.get("validation_freeze") or {}).get("broad_parent_receipt_sha256"),
        "changed_axis": "ADD_ONLY_SESSION_US_OPEN_3H",
        "predicate": {"field": "signal_hour_utc", "op": "in", "value": list(RULE_HOURS)},
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
            "research_incumbent_is_12T_58p33": True,
            "production_ssot_unchanged": True,
            "parent_match_required_pct": 100.0,
            "parent_trade_delete_forbidden": True,
            "parent_trade_rewrite_forbidden": True,
            "append_only_new_trades": True,
            "prospective_only_after_66T_boundary": True,
            "outcome_blind_rule": True,
            "numeric_threshold_sweep": False,
            "post_outcome_trade_deletion": False,
            "wr_pnl_expectancy_pf_payoff_non_decrease_required": True,
            "dd_non_increase_required": True,
            "fresh25_required_before_development_ready": True
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
        "action": "hold"
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
    assert len(baseline) == 66
    assert len(materialized.get("trades") or []) == 12
    assert abs(float((inc.get("metrics") or {})["win_rate"]) - 7 / 12) < 1e-12
    print("PASS_A1_KELTNER_58PCT_ADD_ONLY_CONTINUATION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current-parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_keltner_58pct_add_only_continuation_v1.json"))
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
        "receipt": result["receipt_sha256"]
    }
    print("A1_KELTNER_58PCT_ADD_ONLY=" + json.dumps(brief, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

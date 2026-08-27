#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild.a1_top5_additive_entry_union_v1 import evaluate, metrics, trade_key

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "backend/research/rebuild/a1_trendrider_wr8125_exact16_trade_receipt_v1.json"
SCHEMA = "zel.a1.trendrider.wr8125_plus_current12_union.v1"
MIN_SURVIVOR_T = 25


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def payoff(rows: list[Mapping[str, Any]]) -> float | None:
    net = [float(x["net_bps"]) for x in rows]
    wins = [x for x in net if x > 0]
    losses = [-x for x in net if x < 0]
    if not wins or not losses:
        return None
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def validate_parent(parent: Mapping[str, Any]) -> None:
    if parent.get("schema_version") != "zel.a1.trendrider.wr8125.trade_receipt.v1":
        raise RuntimeError("WR8125_TRADE_RECEIPT_SCHEMA_MISMATCH")
    supplied = str(parent.get("receipt_sha256") or "")
    core = dict(parent)
    core.pop("receipt_sha256", None)
    if supplied != stable(core):
        raise RuntimeError("WR8125_TRADE_RECEIPT_HASH_MISMATCH")
    rows = [dict(x) for x in parent.get("trades") or []]
    m = metrics(rows)
    p = payoff(rows)
    expected = parent.get("metrics") or {}
    checks = {
        "trades": (int(m["trades"]), 16),
        "win_rate": (float(m["win_rate"]), 0.8125),
        "net_pnl_bps": (float(m["net_pnl_bps"]), float(expected["net_pnl_bps"])),
        "net_expectancy_bps": (float(m["net_expectancy_bps"]), float(expected["net_expectancy_bps"])),
        "profit_factor": (float(m["profit_factor"]), float(expected["profit_factor"])),
        "drawdown_bps": (float(m["drawdown_bps"]), float(expected["drawdown_bps"])),
        "payoff": (float(p), float(expected["payoff"])),
    }
    for name, (actual, wanted) in checks.items():
        if abs(actual - wanted) > 1e-9 * max(1.0, abs(wanted)):
            raise RuntimeError(f"WR8125_PARENT_METRIC_MISMATCH:{name}:{actual}:{wanted}")


def run(current: Mapping[str, Any]) -> dict[str, Any]:
    parent = read(PARENT)
    validate_parent(parent)
    if current.get("strategy_id") != "trend_rider":
        raise RuntimeError("CURRENT12_STRATEGY_MISMATCH")
    current_rows = [dict(x) for x in current.get("trades") or []]
    if int(current.get("completed_trades") or -1) != 12 or len(current_rows) != 12:
        raise RuntimeError(f"CURRENT12_EXPECTED_EXACTLY_12T:{current.get('completed_trades')}:{len(current_rows)}")

    additive = evaluate(parent, {"strategy_id": "trend_rider", "trades": current_rows})
    parent_rows = [dict(x) for x in parent["trades"]]
    parent_keys = {trade_key(x) for x in parent_rows}
    current_by = {trade_key(x): x for x in current_rows}
    added_keys = sorted(set(current_by) - parent_keys, key=str)
    overlap_keys = sorted(set(current_by) & parent_keys, key=str)
    added_rows = [current_by[x] for x in added_keys]
    combined_rows = parent_rows + added_rows

    parent_payoff = payoff(parent_rows)
    added_payoff = payoff(added_rows)
    combined_payoff = payoff(combined_rows)
    payoff_non_decrease = parent_payoff is None or (combined_payoff is not None and combined_payoff >= parent_payoff)
    strict_checks = dict(additive["checks"])
    strict_checks["combined_payoff_non_decrease"] = payoff_non_decrease
    strict_all_metric_pass = all(strict_checks.values())

    historical_excluded_keys = {
        ("BTC-USDT", 1786914000000, 1786917600000, "short"),
        ("BTC-USDT", 1787439600000, 1787443200000, "long"),
        ("ETH-USDT", 1786906800000, 1786910400000, "long"),
    }
    historical_reintroduced = sorted(set(added_keys) & historical_excluded_keys, key=str)
    post_frozen24_added = sorted(set(added_keys) - historical_excluded_keys, key=str)

    combined_t = len(combined_rows)
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_8125_PLUS_CURRENT12_STRICT" if strict_all_metric_pass and combined_t >= MIN_SURVIVOR_T else "HOLD_8125_PLUS_CURRENT12_RESEARCH_UNION",
        "strategy_id": "trend_rider",
        "mode": "FROZEN_16T_8125_PARENT_PLUS_FULL_CURRENT12_DONOR_DEDUPED",
        "parent_T": len(parent_rows),
        "parent_metrics": additive["parent_metrics"],
        "parent_payoff": parent_payoff,
        "current_donor_T": len(current_rows),
        "overlap_T": len(overlap_keys),
        "overlap_keys": [list(x) for x in overlap_keys],
        "added_distinct_T": len(added_rows),
        "added_distinct_metrics": additive["added_only_metrics"],
        "added_distinct_payoff": added_payoff,
        "combined_T": combined_t,
        "combined_metrics": additive["combined_metrics"],
        "combined_payoff": combined_payoff,
        "strict_checks": strict_checks,
        "strict_all_metric_pass": strict_all_metric_pass,
        "minimum_survivor_T": MIN_SURVIVOR_T,
        "T_deficit_to_minimum_survivor_gate": max(0, MIN_SURVIVOR_T - combined_t),
        "tier_a_T_minimum_met": combined_t >= MIN_SURVIVOR_T,
        "historical_reintroduced_T": len(historical_reintroduced),
        "historical_reintroduced_keys": [list(x) for x in historical_reintroduced],
        "post_frozen24_added_T": len(post_frozen24_added),
        "post_frozen24_added_keys": [list(x) for x in post_frozen24_added],
        "additive_receipt": additive,
        "policy": {
            "full_current12_donor_used_without_outcome_filter": True,
            "semantic_dedupe_required": True,
            "parent_match_required_pct": 100.0,
            "historical_16T_8125_parent_immutable": True,
            "research_union_does_not_replace_parent": True,
            "survivor_requires_minimum_25T_plus_full_hardening": True,
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
    validate_parent(read(PARENT))
    print("PASS_A1_TRENDRIDER_WR8125_PLUS_CURRENT12_UNION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_wr8125_plus_current12_union_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.current is None:
        raise RuntimeError("--current required")
    result = run(read(args.current))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"], "parent_T": result["parent_T"], "current_donor_T": result["current_donor_T"],
        "overlap_T": result["overlap_T"], "added_distinct_T": result["added_distinct_T"], "combined_T": result["combined_T"],
        "combined_metrics": result["combined_metrics"], "combined_payoff": result["combined_payoff"],
        "T_deficit": result["T_deficit_to_minimum_survivor_gate"], "strict_all_metric_pass": result["strict_all_metric_pass"],
        "failed_checks": [k for k,v in result["strict_checks"].items() if not v], "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_recent_loss_cluster_diagnostic_v1 as diag
from backend.research.rebuild.a1_top5_additive_entry_union_v1 import evaluate, metrics, trade_key

ROOT = Path(__file__).resolve().parents[3]
FRESH = ROOT / "backend/research/rebuild/a1_trendrider_8125_fresh2_source_v1.json"
SCHEMA = "zel.a1.trendrider.current12_fresh2_reservoir.v1"
MIN_SURVIVOR_T = 25


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def payoff(rows: list[Mapping[str, Any]]) -> float | None:
    wins = [float(x["net_bps"]) for x in rows if float(x["net_bps"]) > 0.0]
    losses = [-float(x["net_bps"]) for x in rows if float(x["net_bps"]) < 0.0]
    if not wins or not losses:
        return None
    return (sum(wins) / len(wins)) / (sum(losses) / len(losses))


def validate_fresh(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    if source.get("schema_version") != "zel.a1.trendrider.8125.fresh2_source.v1":
        raise RuntimeError("FRESH2_SCHEMA_MISMATCH")
    core = dict(source)
    supplied = str(core.pop("receipt_sha256", ""))
    if supplied != stable(core):
        raise RuntimeError("FRESH2_RECEIPT_MISMATCH")
    rows = [dict(x) for x in source.get("trades") or []]
    if len(rows) != 2 or any(float(x.get("net_bps") or 0.0) <= 0.0 for x in rows):
        raise RuntimeError("FRESH2_EXPECTED_TWO_WINNERS")
    return rows


def rebuild_current() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="trend_current_fresh2_") as td:
        receipt = diag._run_receipt("trend_rider", Path(td) / "trend.json")
    if receipt.get("strategy_id") != "trend_rider":
        raise RuntimeError("CURRENT_STRATEGY_MISMATCH")
    rows = [dict(x) for x in receipt.get("trades") or []]
    if len(rows) != int(receipt.get("completed_trades") or -1):
        raise RuntimeError("CURRENT_COUNT_MISMATCH")
    if not rows:
        raise RuntimeError("CURRENT_TRADES_EMPTY")
    return receipt


def run() -> dict[str, Any]:
    current = rebuild_current()
    fresh_source = read(FRESH)
    fresh = validate_fresh(fresh_source)
    parent_rows = [dict(x) for x in current.get("trades") or []]
    parent_keys = {trade_key(x) for x in parent_rows}
    fresh_keys = {trade_key(x) for x in fresh}
    overlap = sorted(parent_keys & fresh_keys, key=str)
    if overlap:
        raise RuntimeError(f"FRESH2_OVERLAP_CURRENT:{overlap}")

    additive = evaluate(
        {"strategy_id": "trend_rider", "trades": parent_rows},
        {"strategy_id": "trend_rider", "trades": fresh},
    )
    combined_rows = parent_rows + fresh
    parent_m = metrics(parent_rows)
    combined_m = metrics(combined_rows)
    parent_payoff = payoff(parent_rows)
    combined_payoff = payoff(combined_rows)
    payoff_non_decrease = (
        parent_payoff is None or (combined_payoff is not None and combined_payoff >= parent_payoff)
    )
    combined_t = len(combined_rows)
    deficit = max(0, MIN_SURVIVOR_T - combined_t)

    strict_checks = dict(additive.get("checks") or {})
    strict_checks["combined_payoff_non_decrease"] = payoff_non_decrease
    strict_all_metric_pass = all(bool(v) for v in strict_checks.values())

    result = {
        "schema_version": SCHEMA,
        "state": "PASS_FRESH2_PRESERVED_IN_RESERVOIR" if additive.get("added_only_trade_count") == 2 else "HOLD_RESERVOIR_APPEND",
        "strategy_id": "trend_rider",
        "mode": "CURRENT_NATIVE_PARENT_PLUS_FROZEN_FRESH2_ADD_ONLY_RESERVOIR",
        "current_parent_receipt_sha256": current.get("receipt_sha256"),
        "current_parent_T": len(parent_rows),
        "fresh2_source_receipt_sha256": fresh_source.get("receipt_sha256"),
        "fresh2_T": len(fresh),
        "fresh2_overlap_T": len(overlap),
        "combined_T": combined_t,
        "minimum_survivor_T": MIN_SURVIVOR_T,
        "T_deficit_to_minimum_survivor_gate": deficit,
        "parent_metrics": parent_m,
        "fresh2_metrics": metrics(fresh),
        "combined_metrics": combined_m,
        "parent_payoff": parent_payoff,
        "combined_payoff": combined_payoff,
        "payoff_non_decrease": payoff_non_decrease,
        "additive_receipt": additive,
        "strict_checks": strict_checks,
        "strict_all_metric_pass": strict_all_metric_pass,
        "reservoir_policy": {
            "fresh2_preserved": True,
            "fresh2_not_deleted_for_low_amplitude": True,
            "counts_as_research_reservoir_T": True,
            "does_not_replace_81p25_historical_incumbent": True,
            "survivor_promotion_requires_minimum_25T": True,
            "survivor_promotion_requires_full_hardening_gate": True,
            "selection_authority": False,
            "promotion_authority": False,
            "execution_authority": "NONE",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
        "next": "COLLECT_APPEND_ONLY_UNSEEN_T_UNTIL_AT_LEAST_25T_THEN_FULL_SURVIVOR_GATE",
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "action": "hold",
    }
    result["receipt_sha256"] = stable(result)
    return result


def self_test() -> int:
    source = read(FRESH)
    rows = validate_fresh(source)
    assert len(rows) == 2
    assert all(float(x["net_bps"]) > 0.0 for x in rows)
    assert MIN_SURVIVOR_T == 25
    print("PASS_A1_TRENDRIDER_CURRENT12_FRESH2_RESERVOIR_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trendrider_current12_fresh2_reservoir_v1.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": r["state"],
        "current_parent_T": r["current_parent_T"],
        "fresh2_T": r["fresh2_T"],
        "combined_T": r["combined_T"],
        "T_deficit": r["T_deficit_to_minimum_survivor_gate"],
        "parent_metrics": r["parent_metrics"],
        "combined_metrics": r["combined_metrics"],
        "parent_payoff": r["parent_payoff"],
        "combined_payoff": r["combined_payoff"],
        "strict_all_metric_pass": r["strict_all_metric_pass"],
        "receipt": r["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_loss_streak_repair_regression_v1 as base

SPEC = {
    "trigger_run_id": 32623644328,
    "parent_policy": "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py",
    "child_policy": "backend/research/rebuild/trend_rider_transition_freshness_non_us_strength_reentry_child_policy_v1.py",
    "expected_context_trade_count": 24,
    "expected_loss_cluster_net_bps": -680.7580413522833,
    "loss_keys": [
        ("ETH-USDT", 1787400000000, "long"),
        ("ETH-USDT", 1787418000000, "long"),
        ("ETH-USDT", 1787439600000, "long"),
        ("BTC-USDT", 1787439600000, "long"),
    ],
    "changed_axis": "NON_US_SCAFFOLD_PLUS_US_ST_GAP_ATR_STRENGTHENING_REENTRY",
}

SCAFFOLD = {
    "policy": "backend/research/rebuild/trend_rider_transition_freshness_non_us_child_policy_v1.py",
    "trades": 15,
    "wins": 12,
    "losses": 3,
    "win_rate": 0.8,
    "net_pnl_bps": 21196.60152461874,
    "max_drawdown_bps": 219.06777382538348,
    "winner_retention": 0.8571428571428571,
    "source": "IMMUTABLE_TRIGGER_RUN_32623644328_GENERATION_1",
}


def classify(row: dict[str, Any]) -> dict[str, Any]:
    authority = bool((row.get("authority") or {}).get("match"))
    recovery = row["repair_context"]
    wr = recovery.get("win_rate")
    pnl = float(recovery.get("net_pnl_bps") or 0.0)
    dd = float(recovery.get("max_drawdown_bps") or 0.0)
    parent_pnl = float(row["parent_context"]["net_pnl_bps"])
    wr_floor_kept = wr is not None and float(wr) >= float(SCAFFOLD["win_rate"])
    pnl_recovered = pnl > float(SCAFFOLD["net_pnl_bps"])
    pnl_parent_restored = pnl >= parent_pnl
    dd_not_worse_than_parent = dd <= float(row["parent_context"]["max_drawdown_bps"])
    passed = bool(authority and wr_floor_kept and pnl_recovered)
    return {
        "schema_version": "zel.a1.trend_rider.wr80_scaffold_pnl_recovery.v1",
        "state": "PASS_WR_SCAFFOLD_PNL_RECOVERY" if passed else "HOLD_WR_SCAFFOLD_TRY_NEXT_PNL_RECOVERY_AXIS",
        "strategy_id": "trend_rider",
        "baseline_identity": "TREND_RIDER_NON_US_WR80_SCAFFOLD",
        "optimization_mode": "SEQUENTIAL_CONSTRAINED_PARETO_RECOVERY",
        "immutable_parent": row["parent_context"],
        "parked_scaffold": SCAFFOLD,
        "recovery_candidate": recovery,
        "recovery_retention": row["retention"],
        "authority": row["authority"],
        "constraints": {
            "preserve_scaffold_win_rate_floor": float(SCAFFOLD["win_rate"]),
            "win_rate_floor_kept": wr_floor_kept,
            "recover_net_pnl_above_scaffold": True,
            "net_pnl_recovered": pnl_recovered,
            "parent_net_pnl_fully_restored": pnl_parent_restored,
            "drawdown_not_worse_than_parent": dd_not_worse_than_parent,
            "fresh_25_h4_h5_still_required": True,
        },
        "deltas_vs_scaffold": {
            "win_rate_pp": None if wr is None else 100.0 * (float(wr) - float(SCAFFOLD["win_rate"])),
            "net_pnl_bps": pnl - float(SCAFFOLD["net_pnl_bps"]),
            "max_drawdown_bps": dd - float(SCAFFOLD["max_drawdown_bps"]),
            "trade_count": int(recovery["trades"]) - int(SCAFFOLD["trades"]),
        },
        "pnl_gap_to_parent_bps": parent_pnl - pnl,
        "historical_regression_is_promotion_evidence": False,
        "scaffold_must_not_be_discarded_if_this_axis_fails": True,
        "next": (
            "PREREGISTER_RECOVERY_CHILD_FRESH25_THEN_H4_H5"
            if passed
            else "KEEP_WR80_SCAFFOLD_AND_ROUTE_NEXT_DISTINCT_US_REENTRY_MECHANISM"
        ),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }


def run(out: Path) -> dict[str, Any]:
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = base.evaluate_case("trend_rider", SPEC, out.parent)
    result = classify(raw)
    result["receipt_sha256"] = base.stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    out.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "authority": result["authority"]["match"],
        "scaffold": result["parked_scaffold"],
        "recovery": result["recovery_candidate"],
        "deltas_vs_scaffold": result["deltas_vs_scaffold"],
        "next": result["next"],
    }, sort_keys=True, allow_nan=False))
    return result


def self_test() -> int:
    assert SCAFFOLD["win_rate"] == 0.8
    assert SCAFFOLD["net_pnl_bps"] > 0
    assert SPEC["expected_context_trade_count"] == 24
    assert len(SPEC["loss_keys"]) == 4
    assert "ST_GAP_ATR" in SPEC["changed_axis"]
    print("PASS_A1_TREND_RIDER_WR80_SCAFFOLD_PNL_RECOVERY_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_wr80_scaffold_pnl_recovery_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    run(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

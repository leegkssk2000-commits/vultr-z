#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.research.rebuild import a1_loss_streak_repair_regression_v1 as base

SPEC = {
    "trigger_run_id": 32623644328,
    "parent_policy": "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py",
    "child_policy": "backend/research/rebuild/trend_rider_transition_freshness_atr_expansion_child_policy_v1.py",
    "expected_context_trade_count": 24,
    "expected_loss_cluster_net_bps": -680.7580413522833,
    "loss_keys": [
        ("ETH-USDT", 1787400000000, "long"),
        ("ETH-USDT", 1787418000000, "long"),
        ("ETH-USDT", 1787439600000, "long"),
        ("BTC-USDT", 1787439600000, "long"),
    ],
    "changed_axis": "ATR14_CURRENT_GT_PRIOR_CLOSED_BAR_ON_TRANSITION_FRESHNESS_INCUMBENT",
}


def run(out: Path) -> dict:
    out.parent.mkdir(parents=True, exist_ok=True)
    row = base.evaluate_case("trend_rider", SPEC, out.parent)
    row["candidate_label"] = "TREND_TRANSITION_FRESHNESS_PLUS_ATR_EXPANSION"
    row["historical_regression_is_promotion_evidence"] = False
    row["fresh_25_h4_h5_still_required_if_dual_pass"] = True
    row["same_filter_cross_strategy_copy_forbidden"] = True
    row["receipt_sha256"] = base.stable({k: v for k, v in row.items() if k != "receipt_sha256"})
    out.write_text(json.dumps(row, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": row["state"],
        "authority": row["authority"]["match"],
        "parent": row["parent_context"],
        "repair": row["repair_context"],
        "deltas": row["deltas"],
        "retention": row["retention"],
        "next": row["decision"]["next"],
    }, sort_keys=True, allow_nan=False))
    return row


def self_test() -> int:
    assert SPEC["parent_policy"].endswith("trend_rider_transition_freshness_child_policy_v1.py")
    assert SPEC["child_policy"].endswith("trend_rider_transition_freshness_atr_expansion_child_policy_v1.py")
    assert SPEC["expected_context_trade_count"] == 24
    assert len(SPEC["loss_keys"]) == 4
    print("PASS_A1_TREND_RIDER_ATR_EXPANSION_LOSS_REGRESSION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_trend_rider_atr_expansion_loss_regression_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    run(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

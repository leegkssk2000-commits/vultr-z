#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_break_box_iterative_dd_repair_v1 as v1
from backend.research.rebuild import a1_break_box_iterative_dd_repair_v2 as v2

SCHEMA = "zel.a1.break_box_iterative_dd_repair.v3"


def _candidate_safe(rows: Sequence[Mapping[str, Any]], baseline: Mapping[str, Any], decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    raw = v1._metrics(rows)
    min_trades = max(8, math.ceil(int(baseline["trades"]) * 0.60))
    raw_pf = float(raw.get("profit_factor") or 0.0)
    base_pf = float(baseline.get("profit_factor") or 0.0)
    dd = float(raw.get("drawdown_bps") if raw.get("drawdown_bps") is not None else 1e18)
    base_dd = float(baseline.get("drawdown_bps") if baseline.get("drawdown_bps") is not None else 1e18)
    gate = bool(
        int(raw["trades"]) >= min_trades
        and float(raw.get("net_pnl_bps") if raw.get("net_pnl_bps") is not None else -1e18) >= float(baseline.get("net_pnl_bps") if baseline.get("net_pnl_bps") is not None else -1e18)
        and float(raw.get("net_expectancy_bps") if raw.get("net_expectancy_bps") is not None else -1e18) >= float(baseline.get("net_expectancy_bps") if baseline.get("net_expectancy_bps") is not None else -1e18)
        and raw_pf >= base_pf
        and dd < base_dd
    )
    metrics = dict(raw)
    metrics["profit_factor_infinite"] = math.isinf(raw_pf)
    if math.isinf(raw_pf) or math.isnan(raw_pf):
        metrics["profit_factor"] = None
    row = {
        "candidate_id": "break_box_r4_common_mode_lowest_chase_owner_v1",
        "generation": "R4",
        "changed_axis": "COMMON_MODE_EXPOSURE_CONTEXT_ONLY",
        "changed_variant": "ONE_SIGNAL_PER_TIMESTAMP_SELECT_LOWEST_BOX_CHASE_ATR",
        "changed_axis_count_this_generation": 1,
        "cumulative_parent": "break_and_continue_box_break_child_v1",
        "selection_feature": "BOX_CHASE_ATR_AT_COMPLETED_SIGNAL_BAR",
        "selection_feature_is_preentry_causal": True,
        "numeric_threshold_sweep": False,
        "post_outcome_threshold_fitting": False,
        "same_timestamp_only": True,
        "metrics": metrics,
        "minimum_development_trades": min_trades,
        "trade_retention_pct": 100.0 * int(raw["trades"]) / max(1, int(baseline["trades"])),
        "development_upgrade_gate_pass": gate,
        "group_decisions": list(decisions),
        "fresh_oos_required": True,
        "identity_h4_h5_required": True,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }
    row["candidate_sha256"] = v1._sha(row)
    return row


def run(out: Path) -> dict[str, Any]:
    original = v2._candidate
    try:
        v2._candidate = _candidate_safe
        result = v2.run(out)
    finally:
        v2._candidate = original
    result["schema_version"] = SCHEMA
    result["metric_serialization_hardened"] = True
    result["receipt_sha256"] = v1._sha({k: val for k, val in result.items() if k != "receipt_sha256"})
    out.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    base = {"trades": 10, "net_pnl_bps": 1000.0, "net_expectancy_bps": 100.0, "profit_factor": 2.0, "drawdown_bps": 200.0}
    rows = [{"signal_ts": i, "exit_ts": i, "entry_ts": i, "symbol": "BTC-USDT", "net_bps": 150.0} for i in range(8)]
    row = _candidate_safe(rows, base, [])
    assert row["minimum_development_trades"] == 8
    assert row["metrics"]["trades"] == 8
    assert row["metrics"]["profit_factor"] is None
    assert row["metrics"]["profit_factor_infinite"] is True
    assert row["development_upgrade_gate_pass"] is True
    json.dumps(row, allow_nan=False)
    print("PASS_A1_BREAK_BOX_ITERATIVE_DD_REPAIR_V3_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_break_box_iterative_dd_repair_v2_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.out)
    c = r["R4_candidate"]
    print(json.dumps({"state": r["state"], "r4_pass": c["development_upgrade_gate_pass"], "metrics": c["metrics"], "next": r["next"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

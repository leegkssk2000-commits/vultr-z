#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import a1_break_box_iterative_dd_repair_v1 as v1
from backend.research.rebuild.a1_a4_exact_parent_repair_batch_v1 import _maps, _signal_index
from backend.research.rebuild.a1_fresh_boundary_shadow_replay_v1 import run_terminal_shadow
from backend.research.rebuild.policy_kernel_v1 import atr

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "zel.a1.break_box_iterative_dd_repair.v2"


def _box_chase_atr(trade: Mapping[str, Any], receipt: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]]) -> float:
    symbol = str(trade.get("symbol") or "")
    idx = _signal_index(trade, maps)
    if idx is None or symbol not in bars_by or idx < 14 or idx < 8:
        return math.inf
    bars = bars_by[symbol]
    current = bars[idx]
    close = float(current["close"])
    a = max(float(atr(bars[: idx + 1], 14)), 1e-12)
    prior = bars[max(0, idx - 8):idx]
    if len(prior) < 8:
        return math.inf
    box_high = max(float(x["high"]) for x in prior)
    box_low = min(float(x["low"]) for x in prior)
    return max((close - box_high) / a, (box_low - close) / a, 0.0)


def _keep_one_per_timestamp_by_lowest_chase(rows: Sequence[Mapping[str, Any]], receipt: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bars_by, maps = _maps(receipt)
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        groups[int(raw.get("signal_ts") or 0)].append(dict(raw))
    out: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for ts in sorted(groups):
        group = groups[ts]
        if len(group) == 1:
            out.extend(group)
            continue
        ranked = sorted(
            ((_box_chase_atr(x, receipt, bars_by, maps), str(x.get("symbol") or ""), str(x.get("side") or ""), x) for x in group),
            key=lambda z: (z[0], z[1], z[2]),
        )
        keep = ranked[0][3]
        out.append(keep)
        decisions.append({
            "signal_ts": ts,
            "group_size": len(group),
            "selected_symbol": keep.get("symbol"),
            "selected_side": keep.get("side"),
            "selected_box_chase_atr": None if math.isinf(ranked[0][0]) else ranked[0][0],
            "discarded": [
                {"symbol": z[3].get("symbol"), "side": z[3].get("side"), "box_chase_atr": None if math.isinf(z[0]) else z[0]}
                for z in ranked[1:]
            ],
        })
    return out, decisions


def _candidate(rows: Sequence[Mapping[str, Any]], baseline: Mapping[str, Any], decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    m = v1._metrics(rows)
    min_trades = max(8, math.ceil(int(baseline["trades"]) * 0.60))
    gate = bool(
        int(m["trades"]) >= min_trades
        and float(m.get("net_pnl_bps") or -1e18) >= float(baseline.get("net_pnl_bps") or -1e18)
        and float(m.get("net_expectancy_bps") or -1e18) >= float(baseline.get("net_expectancy_bps") or -1e18)
        and float(m.get("profit_factor") or 0.0) >= float(baseline.get("profit_factor") or 0.0)
        and float(m.get("drawdown_bps") or 1e18) < float(baseline.get("drawdown_bps") or 1e18)
    )
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
        "metrics": m,
        "minimum_development_trades": min_trades,
        "trade_retention_pct": 100.0 * int(m["trades"]) / max(1, int(baseline["trades"])),
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


def evaluate(parent: Mapping[str, Any], box: Mapping[str, Any], boundary: str) -> dict[str, Any]:
    prior = v1.evaluate(parent, box, boundary)
    baseline_rows = [dict(x) for x in (box.get("trades") or [])]
    baseline = v1._metrics(baseline_rows)
    r4_rows, decisions = _keep_one_per_timestamp_by_lowest_chase(baseline_rows, box)
    r4 = _candidate(r4_rows, baseline, decisions)
    if r4["development_upgrade_gate_pass"]:
        state = "PASS_R4_COMMON_MODE_QUALITY_SELECTOR_READY"
        next_step = "FREEZE_R4_CHILD; START_INDEPENDENT_FRESH_OOS_AND_IDENTITY_H4_H5; PRESERVE_BOX_INCUMBENT_UNTIL_PASS"
    else:
        state = "HOLD_R4_NEXT_DISTINCT_AXIS_REQUIRED"
        next_step = "PRESERVE_BOX_PARTIAL_SUCCESS; CONTINUE_R5_DISTINCT_VOLATILITY_OR_EXIT_RISK_AXIS_WITHOUT_RESET"
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "strategy_id": v1.STRATEGY_ID,
        "comparison_boundary_utc": boundary,
        "best_partial_success_child": "break_and_continue_box_break_child_v1",
        "R2_R3": prior,
        "R4_candidate": r4,
        "next": next_step,
        "policy": {
            "preserve_partial_success": True,
            "restart_from_zero_forbidden": True,
            "one_primary_axis_per_generation": True,
            "R4_uses_only_entry_time_observable": True,
            "numeric_threshold_sweep": False,
            "fresh_oos_required": True,
            "continue_R5_RN_on_failure": True,
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = v1._sha(result)
    return result


def run(out: Path) -> dict[str, Any]:
    contract = v1._read(v1.CONTRACT)
    if not bool(((contract.get("iterative_pareto_repair") or {}).get("enabled"))):
        raise RuntimeError("ITERATIVE_REPAIR_CONTRACT_DISABLED")
    ledger = v1._read(v1.LEDGER)
    inventory = v1._read(v1.INVENTORY)
    row = (ledger.get("strategies") or {}).get(v1.STRATEGY_ID)
    if not isinstance(row, Mapping):
        raise RuntimeError("BREAK_STRATEGY_MISSING")
    boundary = str(row.get("prospective_boundary_utc") or "")
    if not boundary:
        raise RuntimeError("BREAK_BOUNDARY_MISSING")
    parent_policy = ROOT / str(inventory["strategies"][v1.STRATEGY_ID]["policy_owner"])
    with tempfile.TemporaryDirectory(prefix="break_box_iterative_dd_v2_") as td:
        p = Path(td)
        parent, _ = run_terminal_shadow(strategy_id=v1.STRATEGY_ID, policy_path=parent_policy, fresh_boundary_utc=boundary, out=p / "parent.json")
        box, _ = run_terminal_shadow(strategy_id=v1.STRATEGY_ID, policy_path=v1.BOX_CHILD, fresh_boundary_utc=boundary, out=p / "box.json")
    result = evaluate(parent, box, boundary)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    fake_receipt = {"source": {"symbols": []}, "trades": []}
    base = {"trades": 10, "net_pnl_bps": 1000.0, "net_expectancy_bps": 100.0, "profit_factor": 2.0, "drawdown_bps": 200.0}
    row = _candidate(
        [{"signal_ts": i, "exit_ts": i, "entry_ts": i, "symbol": "BTC-USDT", "net_bps": -50.0 if i == 0 else 150.0} for i in range(8)],
        base,
        [],
    )
    assert row["minimum_development_trades"] == 8
    assert row["metrics"]["trades"] == 8
    assert math.isfinite(float(row["metrics"]["profit_factor"]))
    assert row["selection_authority"] is False
    print("PASS_A1_BREAK_BOX_ITERATIVE_DD_REPAIR_V2_SELF_TEST")
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

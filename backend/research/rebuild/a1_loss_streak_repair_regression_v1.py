#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v2 as exact

ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ROOT / "backend/research/rebuild/strategy25_structural_inventory_v2.json"
SCHEMA = "zel.a1.loss_streak_repair_regression.v1"

CASES: dict[str, dict[str, Any]] = {
    "trend_rider": {
        "child_policy": "backend/research/rebuild/trend_rider_transition_freshness_non_us_child_policy_v1.py",
        "expected_context_trade_count": 24,
        "expected_loss_cluster_net_bps": -680.1800975576468,
        "loss_keys": [
            ("ETH-USDT", 1787184000000, "long"),
            ("ETH-USDT", 1787216400000, "long"),
            ("BTC-USDT", 1787238000000, "short"),
            ("BTC-USDT", 1787324400000, "short"),
        ],
        "changed_axis": "H5_NON_US_SESSION_ONLY",
    },
    "keltner_trend": {
        "child_policy": "backend/research/rebuild/keltner_trend_volatility_cool_child_policy_v1.py",
        "expected_context_trade_count": 10,
        "expected_loss_cluster_net_bps": -617.7985669039492,
        "loss_keys": [
            ("BTC-USDT", 1786856400000, "long"),
            ("BTC-USDT", 1786946400000, "short"),
            ("ETH-USDT", 1787040000000, "long"),
            ("ETH-USDT", 1787119200000, "long"),
        ],
        "changed_axis": "VOLATILITY_COOL_REGIME_ATR14_LT_ATR50_ONLY",
    },
}


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def identity(row: Mapping[str, Any]) -> tuple[str, int, str]:
    return (str(row.get("symbol")), int(row.get("signal_ts")), str(row.get("side")))


def trade_geometry_equal(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    for field in ("entry_ts", "exit_ts", "entry", "exit", "side", "reason", "gross_bps", "net_bps", "realized_cost_bps"):
        av, bv = a.get(field), b.get(field)
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            if not math.isclose(float(av), float(bv), rel_tol=0.0, abs_tol=1e-9):
                return False
        elif av != bv:
            return False
    return True


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    net = [float(x["net_bps"]) for x in rows]
    wins = [x for x in net if x > 0.0]
    losses = [-x for x in net if x < 0.0]
    gp, gl = sum(wins), sum(losses)
    return {
        "trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(rows) if rows else None,
        "net_pnl_bps": sum(net),
        "net_expectancy_bps": sum(net) / len(rows) if rows else None,
        "profit_factor": gp / gl if gl > 0.0 else (float("inf") if gp > 0.0 else None),
        "max_drawdown_bps": max_drawdown(net),
    }


def run_exact(strategy_id: str, *, child_policy: str | None, out: Path) -> dict[str, Any]:
    inventory = read(INVENTORY)
    if child_policy is not None:
        strategy = ((inventory.get("strategies") or {}).get(strategy_id) or {})
        if not strategy:
            raise RuntimeError(f"STRATEGY_NOT_IN_INVENTORY:{strategy_id}")
        strategy["policy_owner"] = child_policy
    with tempfile.TemporaryDirectory(prefix=f"{strategy_id}_loss_streak_regression_") as td:
        inv = Path(td) / "inventory.json"
        inv.write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        old_inventory = exact.v1.INVENTORY_PATH
        old_argv = sys.argv[:]
        try:
            exact.v1.INVENTORY_PATH = inv
            sys.argv = [old_argv[0], "--strategy-id", strategy_id, "--out", str(out), "--terminal-replay"]
            exact.main()
        finally:
            exact.v1.INVENTORY_PATH = old_inventory
            sys.argv = old_argv
    return read(out)


def evaluate_case(strategy_id: str, spec: Mapping[str, Any], out_dir: Path) -> dict[str, Any]:
    cache: dict[str, dict[str, Any]] = {}
    original_fetch = exact.v1.fetch_execution_snapshot

    def cached_fetch(symbol: str, authority: dict[str, Any]) -> dict[str, Any]:
        if symbol not in cache:
            cache[symbol] = copy.deepcopy(original_fetch(symbol, authority))
        return copy.deepcopy(cache[symbol])

    parent_path = out_dir / f"{strategy_id}_parent_terminal.json"
    child_path = out_dir / f"{strategy_id}_repair_terminal.json"
    old_fetch = exact.v1.fetch_execution_snapshot
    try:
        exact.v1.fetch_execution_snapshot = cached_fetch
        parent = run_exact(strategy_id, child_policy=None, out=parent_path)
        child = run_exact(strategy_id, child_policy=str(spec["child_policy"]), out=child_path)
    finally:
        exact.v1.fetch_execution_snapshot = old_fetch

    parent_rows = [dict(x) for x in (parent.get("trades") or [])]
    child_rows = [dict(x) for x in (child.get("trades") or [])]
    parent_index = {identity(x): x for x in parent_rows}
    child_index = {identity(x): x for x in child_rows}
    loss_keys = [tuple(x) for x in spec["loss_keys"]]
    found_losses = [parent_index[k] for k in loss_keys if k in parent_index]

    loss_identity_complete = len(found_losses) == len(loss_keys)
    cutoff = max((int(x["exit_ts"]) for x in found_losses), default=-1)
    parent_context = sorted(
        [x for x in parent_rows if cutoff >= 0 and int(x["exit_ts"]) <= cutoff],
        key=lambda x: (int(x["entry_ts"]), int(x["exit_ts"]), str(x["symbol"])),
    )
    child_context = sorted(
        [x for x in child_rows if cutoff >= 0 and int(x["exit_ts"]) <= cutoff],
        key=lambda x: (int(x["entry_ts"]), int(x["exit_ts"]), str(x["symbol"])),
    )
    parent_ids = {identity(x) for x in parent_context}
    child_ids = {identity(x) for x in child_context}
    retained_ids = parent_ids & child_ids

    geometry_mismatch = [
        str(key) for key in sorted(retained_ids)
        if not trade_geometry_equal(parent_index[key], child_index[key])
    ]
    tail_keys = [identity(x) for x in parent_context[-len(loss_keys):]] if len(parent_context) >= len(loss_keys) else []
    expected_loss_net = float(spec["expected_loss_cluster_net_bps"])
    observed_loss_net = sum(float(x["net_bps"]) for x in found_losses)
    loss_sum_match = loss_identity_complete and math.isclose(observed_loss_net, expected_loss_net, rel_tol=0.0, abs_tol=1e-6)
    context_count_match = len(parent_context) == int(spec["expected_context_trade_count"])
    consecutive_tail_match = tail_keys == loss_keys

    same_execution = parent.get("execution_snapshots") == child.get("execution_snapshots")
    same_cost = parent.get("cost_authority_sha256") == child.get("cost_authority_sha256")
    same_source = parent.get("source") == child.get("source")
    same_config = parent.get("config_sha") == child.get("config_sha")
    child_subset = child_ids.issubset(parent_ids)
    integrity_ok = (
        int(parent.get("leakage_lookahead") or 0) == 0
        and int(child.get("leakage_lookahead") or 0) == 0
        and not list(parent.get("integrity_defects") or [])
        and not list(child.get("integrity_defects") or [])
    )
    authority_match = all([
        loss_identity_complete,
        loss_sum_match,
        context_count_match,
        consecutive_tail_match,
        same_execution,
        same_cost,
        same_source,
        same_config,
        child_subset,
        not geometry_mismatch,
        integrity_ok,
    ])

    parent_m = metrics(parent_context)
    child_m = metrics(child_context)
    retained_loss_rows = [child_index[k] for k in loss_keys if k in child_index and k in child_ids]
    cluster_parent_m = metrics(found_losses)
    cluster_child_m = metrics(retained_loss_rows)

    parent_winners = {identity(x) for x in parent_context if float(x["net_bps"]) > 0.0}
    parent_losses = {identity(x) for x in parent_context if float(x["net_bps"]) < 0.0}
    retained_winners = len(parent_winners & child_ids)
    retained_losses = len(parent_losses & child_ids)
    winner_retention = retained_winners / len(parent_winners) if parent_winners else None
    loss_retention = retained_losses / len(parent_losses) if parent_losses else None
    trade_retention = len(child_context) / len(parent_context) if parent_context else None

    wr_improved = bool(
        parent_m["win_rate"] is not None and child_m["win_rate"] is not None
        and float(child_m["win_rate"]) > float(parent_m["win_rate"])
    )
    pnl_improved = float(child_m["net_pnl_bps"]) > float(parent_m["net_pnl_bps"])
    dd_improved_or_equal = float(child_m["max_drawdown_bps"]) <= float(parent_m["max_drawdown_bps"])
    dual_improvement = bool(authority_match and wr_improved and pnl_improved)

    if not authority_match:
        state = "HOLD_LOSS_STREAK_REPRODUCTION_AUTHORITY_MISMATCH"
    elif dual_improvement:
        state = "PASS_REPAIR_CONTEXT_WR_AND_NET_PNL_IMPROVED"
    else:
        state = "FAIL_REPAIR_CONTEXT_NO_DUAL_WR_PNL_IMPROVEMENT"

    result = {
        "strategy_id": strategy_id,
        "state": state,
        "changed_axis": spec["changed_axis"],
        "child_policy": spec["child_policy"],
        "regression_scope": "PRELOSS_CONTEXT_THROUGH_ORIGINAL_CONSECUTIVE_LOSS_CLUSTER_CUTOFF",
        "promotion_evidence": False,
        "mechanism_sanity_only": True,
        "authority": {
            "match": authority_match,
            "expected_context_trade_count": int(spec["expected_context_trade_count"]),
            "observed_context_trade_count": len(parent_context),
            "loss_identity_complete": loss_identity_complete,
            "consecutive_loss_cluster_is_context_tail": consecutive_tail_match,
            "expected_loss_cluster_net_bps": expected_loss_net,
            "observed_loss_cluster_net_bps": observed_loss_net,
            "loss_sum_match": loss_sum_match,
            "same_execution_snapshots": same_execution,
            "same_cost_authority_sha256": same_cost,
            "same_source": same_source,
            "same_config_sha": same_config,
            "child_subset_of_parent": child_subset,
            "retained_trade_geometry_mismatch": geometry_mismatch,
            "integrity_ok": integrity_ok,
            "cutoff_exit_ts": cutoff,
        },
        "parent_context": parent_m,
        "repair_context": child_m,
        "deltas": {
            "win_rate_pp": None if parent_m["win_rate"] is None or child_m["win_rate"] is None else 100.0 * (float(child_m["win_rate"]) - float(parent_m["win_rate"])),
            "net_pnl_bps": float(child_m["net_pnl_bps"]) - float(parent_m["net_pnl_bps"]),
            "net_expectancy_bps": None if parent_m["net_expectancy_bps"] is None or child_m["net_expectancy_bps"] is None else float(child_m["net_expectancy_bps"]) - float(parent_m["net_expectancy_bps"]),
            "max_drawdown_bps": float(child_m["max_drawdown_bps"]) - float(parent_m["max_drawdown_bps"]),
        },
        "original_loss_cluster": cluster_parent_m,
        "repair_retained_from_original_loss_cluster": cluster_child_m,
        "retention": {
            "trade_retention": trade_retention,
            "winner_retention": winner_retention,
            "loss_retention": loss_retention,
            "blocked_context_trades": len(parent_ids - child_ids),
            "blocked_context_winners": len(parent_winners - child_ids),
            "blocked_context_losses": len(parent_losses - child_ids),
            "blocked_original_cluster_losses": len(set(loss_keys) - child_ids),
        },
        "decision": {
            "win_rate_improved": wr_improved,
            "net_pnl_improved": pnl_improved,
            "drawdown_improved_or_equal": dd_improved_or_equal,
            "dual_wr_pnl_improvement": dual_improvement,
            "generalize_same_filter_to_other_strategies": False,
            "generalize_methodology_if_dual_improvement": dual_improvement,
            "next": (
                "KEEP_FRESH_25_H4_H5_AND_APPLY_PREENTRY_ONE_AXIS_METHOD_TO_NEXT_STRATEGY"
                if dual_improvement
                else "DO_NOT_GENERALIZE_THIS_FILTER_TRY_NEXT_DISTINCT_PREENTRY_AXIS"
            ),
        },
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = stable(result)
    return result


def run(out: Path) -> dict[str, Any]:
    out.parent.mkdir(parents=True, exist_ok=True)
    cases = {sid: evaluate_case(sid, spec, out.parent) for sid, spec in CASES.items()}
    authority_all = all(row["authority"]["match"] for row in cases.values())
    dual_pass = [sid for sid, row in cases.items() if row["decision"]["dual_wr_pnl_improvement"]]
    result = {
        "schema_version": SCHEMA,
        "state": (
            "HOLD_REPRODUCTION_AUTHORITY_MISMATCH"
            if not authority_all
            else "PASS_AT_LEAST_ONE_REPAIR_DUAL_IMPROVEMENT"
            if dual_pass
            else "FAIL_CURRENT_REPAIRS_NO_DUAL_IMPROVEMENT"
        ),
        "trigger_rule": "existing_consecutive_loss_trigger_only",
        "decision_rule": "historical_context_requires_both_win_rate_and_net_pnl_improvement",
        "historical_regression_is_promotion_evidence": False,
        "fresh_25_h4_h5_still_required": True,
        "strategy_specific_preentry_axis_required": True,
        "same_filter_cross_strategy_copy_forbidden": True,
        "cases": cases,
        "dual_improvement_strategy_ids": dual_pass,
        "methodology_next": (
            "FOR_EACH_TRIGGERED_STRATEGY_PREENTRY_ATTRIBUTION_ONE_AXIS_CONTEXT_REGRESSION_THEN_FRESH25_H4_H5"
            if authority_all else "REPAIR_REPRODUCTION_AUTHORITY_FIRST"
        ),
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "exchange_order_submitted": False,
        "protected_mutations": 0,
    }
    result["receipt_sha256"] = stable(result)
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"],
        "dual_improvement_strategy_ids": dual_pass,
        "cases": {
            sid: {
                "state": row["state"],
                "authority": row["authority"]["match"],
                "parent": row["parent_context"],
                "repair": row["repair_context"],
                "deltas": row["deltas"],
                "retention": row["retention"],
            } for sid, row in cases.items()
        },
    }, sort_keys=True, allow_nan=False))
    return result


def self_test() -> int:
    assert set(CASES) == {"trend_rider", "keltner_trend"}
    assert all(len(spec["loss_keys"]) == 4 for spec in CASES.values())
    assert CASES["trend_rider"]["expected_context_trade_count"] == 24
    assert CASES["keltner_trend"]["expected_context_trade_count"] == 10
    assert CASES["trend_rider"]["expected_loss_cluster_net_bps"] < 0.0
    assert CASES["keltner_trend"]["expected_loss_cluster_net_bps"] < 0.0
    print("PASS_A1_LOSS_STREAK_REPAIR_REGRESSION_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("out/a1_loss_streak_repair_regression_latest.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    run(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

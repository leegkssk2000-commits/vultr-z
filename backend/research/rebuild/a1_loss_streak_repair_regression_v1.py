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
SCHEMA = "zel.a1.loss_streak_repair_regression.v2"

CASES: dict[str, dict[str, Any]] = {
    "trend_rider": {
        # The observed 24-trade receipt came from this incumbent lineage, not
        # directly from the canonical trend policy.
        "parent_policy": "backend/research/rebuild/trend_rider_transition_freshness_child_policy_v1.py",
        "child_policy": "backend/research/rebuild/trend_rider_transition_freshness_non_us_child_policy_v1.py",
        "expected_context_trade_count": 24,
        "expected_loss_cluster_net_bps": -680.1800975576468,
        "loss_keys": [
            ("ETH-USDT", 1787184000000, "long"),
            ("ETH-USDT", 1787216400000, "long"),
            ("BTC-USDT", 1787238000000, "short"),
            ("BTC-USDT", 1787324400000, "short"),
        ],
        "changed_axis": "FROZEN_H5_US_SESSION_EXCLUSION_ONLY",
    },
    "keltner_trend": {
        "parent_policy": "backend/research/rebuild/breakout_policy_batch_v1.py",
        "child_policy": "backend/research/rebuild/keltner_trend_volatility_cool_child_policy_v1.py",
        "expected_context_trade_count": 10,
        "expected_loss_cluster_net_bps": -617.7985669039492,
        "loss_keys": [
            ("BTC-USDT", 1786856400000, "long"),
            ("BTC-USDT", 1786946400000, "short"),
            ("ETH-USDT", 1787040000000, "long"),
            ("ETH-USDT", 1787119200000, "long"),
        ],
        "changed_axis": "FROZEN_A4_VOLATILITY_COOL_REGIME_ONLY",
    },
}


def stable(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()
    ).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def ident(row: Mapping[str, Any]) -> tuple[str, int, str]:
    return (str(row.get("symbol")), int(row.get("signal_ts")), str(row.get("side")))


def same_geometry(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    fields = (
        "entry_ts", "exit_ts", "entry", "exit", "side", "reason",
        "gross_bps", "net_bps", "realized_cost_bps",
    )
    for field in fields:
        av, bv = a.get(field), b.get(field)
        if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
            if not math.isclose(float(av), float(bv), rel_tol=0.0, abs_tol=1e-9):
                return False
        elif av != bv:
            return False
    return True


def max_dd(values: list[float]) -> float:
    equity = peak = worst = 0.0
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
        "profit_factor": gp / gl if gl > 0.0 else None,
        "max_drawdown_bps": max_dd(net),
    }


def run_exact(strategy_id: str, *, policy_override: str, out: Path) -> dict[str, Any]:
    inventory = read(INVENTORY)
    strategy = ((inventory.get("strategies") or {}).get(strategy_id) or {})
    if not strategy:
        raise RuntimeError(f"STRATEGY_NOT_IN_INVENTORY:{strategy_id}")
    strategy["policy_owner"] = policy_override
    with tempfile.TemporaryDirectory(prefix=f"{strategy_id}_loss_regression_") as td:
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
    snapshot_cache: dict[str, dict[str, Any]] = {}
    bar_cache: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    original_snapshot = exact.v1.fetch_execution_snapshot
    original_bars = exact.v1.fetch_bars

    def cached_snapshot(symbol: str, authority: dict[str, Any]) -> dict[str, Any]:
        if symbol not in snapshot_cache:
            snapshot_cache[symbol] = copy.deepcopy(original_snapshot(symbol, authority))
        return copy.deepcopy(snapshot_cache[symbol])

    def cached_bars(symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        key = (symbol, interval, int(limit))
        if key not in bar_cache:
            bar_cache[key] = copy.deepcopy(original_bars(symbol, interval, limit))
        return copy.deepcopy(bar_cache[key])

    parent_path = out_dir / f"{strategy_id}_parent_terminal.json"
    child_path = out_dir / f"{strategy_id}_repair_terminal.json"
    try:
        exact.v1.fetch_execution_snapshot = cached_snapshot
        exact.v1.fetch_bars = cached_bars
        parent = run_exact(strategy_id, policy_override=str(spec["parent_policy"]), out=parent_path)
        child = run_exact(strategy_id, policy_override=str(spec["child_policy"]), out=child_path)
    finally:
        exact.v1.fetch_execution_snapshot = original_snapshot
        exact.v1.fetch_bars = original_bars

    parent_rows = [dict(x) for x in (parent.get("trades") or [])]
    child_rows = [dict(x) for x in (child.get("trades") or [])]
    pidx = {ident(x): x for x in parent_rows}
    cidx = {ident(x): x for x in child_rows}
    loss_keys = [tuple(x) for x in spec["loss_keys"]]
    found_losses = [pidx[k] for k in loss_keys if k in pidx]
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
    parent_ids = {ident(x) for x in parent_context}
    child_ids = {ident(x) for x in child_context}
    retained = parent_ids & child_ids
    geometry_mismatch = [str(k) for k in sorted(retained) if not same_geometry(pidx[k], cidx[k])]

    observed_loss_net = sum(float(x["net_bps"]) for x in found_losses)
    expected_loss_net = float(spec["expected_loss_cluster_net_bps"])
    tail_keys = [ident(x) for x in parent_context[-len(loss_keys):]] if len(parent_context) >= len(loss_keys) else []

    authority = {
        "parent_policy_expected": spec["parent_policy"],
        "parent_policy_observed": parent.get("policy_path"),
        "child_policy_expected": spec["child_policy"],
        "child_policy_observed": child.get("policy_path"),
        "loss_identity_complete": loss_identity_complete,
        "consecutive_loss_cluster_is_context_tail": tail_keys == loss_keys,
        "expected_context_trade_count": int(spec["expected_context_trade_count"]),
        "observed_context_trade_count": len(parent_context),
        "expected_loss_cluster_net_bps": expected_loss_net,
        "observed_loss_cluster_net_bps": observed_loss_net,
        "loss_sum_match": loss_identity_complete and math.isclose(observed_loss_net, expected_loss_net, rel_tol=0.0, abs_tol=1e-6),
        "same_execution_snapshots": parent.get("execution_snapshots") == child.get("execution_snapshots"),
        "same_cost_authority_sha256": parent.get("cost_authority_sha256") == child.get("cost_authority_sha256"),
        "same_source": parent.get("source") == child.get("source"),
        "same_config_sha": parent.get("config_sha") == child.get("config_sha"),
        "child_subset_of_parent": child_ids.issubset(parent_ids),
        "retained_trade_geometry_mismatch": geometry_mismatch,
        "integrity_ok": (
            int(parent.get("leakage_lookahead") or 0) == 0
            and int(child.get("leakage_lookahead") or 0) == 0
            and not list(parent.get("integrity_defects") or [])
            and not list(child.get("integrity_defects") or [])
        ),
        "cutoff_exit_ts": cutoff,
    }
    authority["match"] = bool(
        authority["parent_policy_observed"] == authority["parent_policy_expected"]
        and authority["child_policy_observed"] == authority["child_policy_expected"]
        and authority["loss_identity_complete"]
        and authority["consecutive_loss_cluster_is_context_tail"]
        and authority["observed_context_trade_count"] == authority["expected_context_trade_count"]
        and authority["loss_sum_match"]
        and authority["same_execution_snapshots"]
        and authority["same_cost_authority_sha256"]
        and authority["same_source"]
        and authority["same_config_sha"]
        and authority["child_subset_of_parent"]
        and not geometry_mismatch
        and authority["integrity_ok"]
    )

    pm, cm = metrics(parent_context), metrics(child_context)
    retained_cluster = [cidx[k] for k in loss_keys if k in cidx and k in child_ids]
    parent_winners = {ident(x) for x in parent_context if float(x["net_bps"]) > 0.0}
    parent_losses = {ident(x) for x in parent_context if float(x["net_bps"]) < 0.0}
    wr_improved = bool(pm["win_rate"] is not None and cm["win_rate"] is not None and cm["win_rate"] > pm["win_rate"])
    pnl_improved = bool(cm["net_pnl_bps"] > pm["net_pnl_bps"])
    dual = bool(authority["match"] and wr_improved and pnl_improved)

    if not authority["match"]:
        state = "HOLD_LOSS_STREAK_REPRODUCTION_AUTHORITY_MISMATCH"
    elif dual:
        state = "PASS_REPAIR_CONTEXT_WR_AND_NET_PNL_IMPROVED"
    else:
        state = "FAIL_REPAIR_CONTEXT_NO_DUAL_WR_PNL_IMPROVEMENT"

    result = {
        "strategy_id": strategy_id,
        "state": state,
        "changed_axis": spec["changed_axis"],
        "regression_scope": "INCUMBENT_PRELOSS_CONTEXT_THROUGH_ORIGINAL_CONSECUTIVE_LOSS_CLUSTER_CUTOFF",
        "promotion_evidence": False,
        "mechanism_sanity_only": True,
        "authority": authority,
        "parent_context": pm,
        "repair_context": cm,
        "deltas": {
            "win_rate_pp": None if pm["win_rate"] is None or cm["win_rate"] is None else 100.0 * (cm["win_rate"] - pm["win_rate"]),
            "net_pnl_bps": cm["net_pnl_bps"] - pm["net_pnl_bps"],
            "net_expectancy_bps": None if pm["net_expectancy_bps"] is None or cm["net_expectancy_bps"] is None else cm["net_expectancy_bps"] - pm["net_expectancy_bps"],
            "max_drawdown_bps": cm["max_drawdown_bps"] - pm["max_drawdown_bps"],
        },
        "original_loss_cluster": metrics(found_losses),
        "repair_retained_from_original_loss_cluster": metrics(retained_cluster),
        "retention": {
            "trade_retention": len(child_context) / len(parent_context) if parent_context else None,
            "winner_retention": len(parent_winners & child_ids) / len(parent_winners) if parent_winners else None,
            "loss_retention": len(parent_losses & child_ids) / len(parent_losses) if parent_losses else None,
            "blocked_context_trades": len(parent_ids - child_ids),
            "blocked_context_winners": len(parent_winners - child_ids),
            "blocked_context_losses": len(parent_losses - child_ids),
            "blocked_original_cluster_losses": len(set(loss_keys) - child_ids),
        },
        "decision": {
            "win_rate_improved": wr_improved,
            "net_pnl_improved": pnl_improved,
            "drawdown_improved_or_equal": cm["max_drawdown_bps"] <= pm["max_drawdown_bps"],
            "dual_wr_pnl_improvement": dual,
            "generalize_same_filter_to_other_strategies": False,
            "generalize_methodology_if_dual_improvement": dual,
            "next": (
                "KEEP_FRESH25_H4_H5_AND_APPLY_PREENTRY_ONE_AXIS_METHOD_TO_NEXT_TRIGGERED_STRATEGY"
                if dual else "DO_NOT_GENERALIZE_THIS_FILTER_TRY_NEXT_DISTINCT_PREENTRY_AXIS"
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
            "HOLD_REPRODUCTION_AUTHORITY_MISMATCH" if not authority_all
            else "PASS_AT_LEAST_ONE_REPAIR_DUAL_IMPROVEMENT" if dual_pass
            else "FAIL_CURRENT_REPAIRS_NO_DUAL_IMPROVEMENT"
        ),
        "trigger_rule": "EXISTING_CONSECUTIVE_LOSS_TRIGGER_MIN_3",
        "decision_rule": "HISTORICAL_CONTEXT_REQUIRES_BOTH_WIN_RATE_AND_NET_PNL_IMPROVEMENT",
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
    assert CASES["trend_rider"]["parent_policy"].endswith("transition_freshness_child_policy_v1.py")
    assert CASES["trend_rider"]["expected_context_trade_count"] == 24
    assert CASES["keltner_trend"]["expected_context_trade_count"] == 10
    assert all(float(spec["expected_loss_cluster_net_bps"]) < 0.0 for spec in CASES.values())
    print("PASS_A1_LOSS_STREAK_REPAIR_REGRESSION_V2_SELF_TEST")
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

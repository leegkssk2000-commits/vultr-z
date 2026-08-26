#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_a4_distinct_child_repair_batch_v1 as base
from backend.research.rebuild.a1_a4_exact_parent_repair_batch_v1 import _maps, read, validate_parent

SCHEMA = "zel.a1.a4.distinct_child_repair_batch.v2"
PRODUCTION_POLICY = base.ROOT / "backend/research/rebuild/a1_a4_production_candidate_policy_v1.json"
BREAK_PRODUCTION_MIN_WIN_RATE = 0.50
BREAK_SIDE_RECOVERY_AXIS = "SIDE_AWARE_RECOVERY_EXIT_ONLY"
BREAK_SIDE_RECOVERY_EVIDENCE = ("A5E2", "A5E3")

# V1 remains immutable. V2 extends only the development candidate vocabulary.
base.EVIDENCE_BY_AXIS.setdefault(BREAK_SIDE_RECOVERY_AXIS, BREAK_SIDE_RECOVERY_EVIDENCE)


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def _production_blockers(strategy_id: str, parent_m: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    """Fail closed before a development candidate can become READY.

    The 50% WR floor is intentionally scoped to new break_and_continue challengers.
    Existing profitable incumbents are never retroactively deleted by this gate.
    """
    m = candidate.get("metrics") or {}
    blockers: list[str] = []

    if strategy_id == "break_and_continue" and _num(m.get("win_rate"), -1.0) + 1e-12 < BREAK_PRODUCTION_MIN_WIN_RATE:
        blockers.append("WIN_RATE_BELOW_PRODUCTION_FLOOR_0_50")

    if int(m.get("trades") or 0) < int(parent_m.get("trades") or 0):
        blockers.append("TRADE_COUNT_DECREASE")

    for key, code in (
        ("net_pnl_bps", "NET_PNL_BELOW_PARENT"),
        ("net_expectancy_bps", "NET_EXPECTANCY_BELOW_PARENT"),
    ):
        if _num(m.get(key), float("-inf")) + 1e-9 < _num(parent_m.get(key), float("-inf")):
            blockers.append(code)

    parent_pf = parent_m.get("profit_factor")
    child_pf = m.get("profit_factor")
    if parent_pf is not None and (child_pf is None or _num(child_pf) + 1e-9 < _num(parent_pf)):
        blockers.append("PROFIT_FACTOR_BELOW_PARENT")

    if not bool(candidate.get("economic_gate_pass")):
        blockers.append("ECONOMIC_GATE_FAIL")
    if not bool(candidate.get("h5_blocker_count_improved_vs_parent")):
        blockers.append("CONCENTRATION_NOT_IMPROVED")
    return blockers


def _attach_production_gate(strategy_id: str, parent_m: Mapping[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    blockers = _production_blockers(strategy_id, parent_m, candidate)
    candidate["production_gate"] = {
        "passed": not blockers,
        "blockers": blockers,
        "minimum_win_rate": BREAK_PRODUCTION_MIN_WIN_RATE if strategy_id == "break_and_continue" else None,
        "trade_count_non_decrease_required": True,
        "net_pnl_non_decrease_required": True,
        "net_expectancy_non_decrease_required": True,
        "profit_factor_non_decrease_required": True,
        "concentration_blocker_count_improvement_required": True,
    }
    candidate["development_candidate_ready"] = bool(candidate.get("development_candidate_ready") and not blockers)
    candidate.pop("candidate_sha256", None)
    candidate["candidate_sha256"] = base.stable(candidate)
    return candidate


def _degraded_side(parent_trades: list[dict[str, Any]]) -> tuple[str | None, dict[str, float]]:
    side_net = {"long": 0.0, "short": 0.0}
    for trade in parent_trades:
        side = str(trade.get("side") or "")
        if side in side_net:
            side_net[side] += _num(trade.get("net_bps"))
    negative = [side for side, net in side_net.items() if net < 0.0]
    return (min(negative, key=lambda side: side_net[side]) if negative else None), side_net


def _side_aware_recovery_exit(
    parent: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Preserve every parent trade and repair only the structurally degraded side.

    For the degraded side, once a completed bar close is net-positive after the
    parent's full realized cost, schedule an unconditional exit at the next bar open.
    This is next-bar executable, has no threshold sweep, and keeps the parent's full
    realized cost as a conservative charge even though holding time may be shorter.
    """
    parent_trades = [dict(x) for x in (parent.get("trades") or [])]
    degraded_side, side_net = _degraded_side(parent_trades)
    if degraded_side is None:
        return parent_trades, {
            "degraded_side": None,
            "parent_side_net_bps": side_net,
            "modified_trade_count": 0,
            "execution": "NO_NEGATIVE_PARENT_SIDE",
        }

    out: list[dict[str, Any]] = []
    modified = 0
    for raw in parent_trades:
        trade = dict(raw)
        if str(trade.get("side")) != degraded_side:
            out.append(trade)
            continue

        symbol = str(trade["symbol"])
        bars = bars_by.get(symbol) or []
        idx_map = maps.get(symbol) or {}
        entry_idx = idx_map.get(int(trade["entry_ts"]))
        exit_idx = idx_map.get(int(trade["exit_ts"]))
        if entry_idx is None or exit_idx is None or exit_idx <= entry_idx or exit_idx >= len(bars):
            out.append(trade)
            continue

        entry = float(trade["entry"])
        side = str(trade["side"])
        cost = _num(trade.get("realized_cost_bps"))
        for j in range(entry_idx, exit_idx):
            close_px = float(bars[j]["close"])
            mark_gross = (close_px - entry) / entry * 10_000 if side == "long" else (entry - close_px) / entry * 10_000
            if mark_gross - cost <= 0.0:
                continue

            # Decision uses bar j only; execution occurs unconditionally at j+1 open.
            next_bar = bars[j + 1]
            new_exit = float(next_bar["open"])
            gross = (new_exit - entry) / entry * 10_000 if side == "long" else (entry - new_exit) / entry * 10_000
            trade["exit"] = new_exit
            trade["exit_ts"] = int(next_bar["ts_ms"])
            trade["reason"] = "SIDE_RECOVERY_FIRST_NET_POSITIVE_NEXT_OPEN"
            trade["gross_bps"] = gross
            trade["net_bps"] = gross - cost
            trade["parent_realized_cost_bps_conservative_upper_bound"] = cost
            modified += 1
            break
        out.append(trade)

    return out, {
        "degraded_side": degraded_side,
        "parent_side_net_bps": side_net,
        "modified_trade_count": modified,
        "execution": "COMPLETED_BAR_SIGNAL_NEXT_BAR_OPEN",
        "post_outcome_trade_deletion": False,
        "trade_count_preserved": len(out) == len(parent_trades),
    }


def evaluate(strategy_id: str, parent: Mapping[str, Any], hard: Mapping[str, Any]) -> dict[str, Any]:
    validate_parent(strategy_id, parent)
    row = base.evaluate(strategy_id, parent, hard)
    parent_m = dict(row["parent_metrics"])

    # Harden every pre-existing V1 challenger with the production gate.
    candidates = [_attach_production_gate(strategy_id, parent_m, dict(x)) for x in row["candidates"]]

    if strategy_id == "break_and_continue":
        bars_by, maps = _maps(parent)
        parent_trades = [dict(x) for x in (parent.get("trades") or [])]
        child, diagnostics = _side_aware_recovery_exit(parent, bars_by, maps)
        recovery = base._candidate(
            strategy_id=strategy_id,
            parent=parent,
            axis=BREAK_SIDE_RECOVERY_AXIS,
            variant="NEGATIVE_SIDE_FIRST_NET_POSITIVE_NEXT_OPEN",
            child_trades=child,
            parent_trades=parent_trades,
            bars_by=bars_by,
            maps=maps,
            hard=hard,
            entry_identity_preserved=True,
            exit_only=True,
            notes=[
                "degraded side selected from frozen parent side robustness diagnostic",
                "first completed-bar net-positive state schedules unconditional next-bar-open exit",
                "all parent trades retained; full parent realized cost charged conservatively",
                "no parameter sweep and no post-outcome trade deletion",
            ],
        )
        recovery["repair_diagnostics"] = diagnostics
        recovery = _attach_production_gate(strategy_id, parent_m, recovery)
        candidates.append(recovery)

    candidates.sort(key=lambda x: (
        not bool(x["development_candidate_ready"]),
        len((x.get("production_gate") or {}).get("blockers") or []),
        int((x.get("concentration") or {}).get("blocker_count") or 0),
        -_num((x.get("metrics") or {}).get("win_rate"), -1.0),
        -_num((x.get("metrics") or {}).get("net_expectancy_bps"), -1e18),
        -_num((x.get("metrics") or {}).get("profit_factor"), 0.0),
        _num((x.get("metrics") or {}).get("drawdown_bps"), 1e18),
        str(x.get("candidate_id") or ""),
    ))
    ready = [x for x in candidates if x["development_candidate_ready"]]
    row["candidates"] = candidates
    row["development_ready_count"] = len(ready)
    row["next_distinct_child_candidate"] = ready[0] if ready else None
    row["production_min_win_rate"] = BREAK_PRODUCTION_MIN_WIN_RATE if strategy_id == "break_and_continue" else None
    return row


def run(parent_paths: Mapping[str, Path], output: Path) -> dict[str, Any]:
    a5, hard, production = read(base.A5_CONTRACT), read(base.HARDENING_POLICY), read(PRODUCTION_POLICY)
    if production.get("state") != "FROZEN_PRODUCTION_CANDIDATE_GATE":
        raise RuntimeError("PRODUCTION_CANDIDATE_POLICY_NOT_FROZEN")
    if float(production["strategies"]["break_and_continue"]["minimum_win_rate"]) != BREAK_PRODUCTION_MIN_WIN_RATE:
        raise RuntimeError("BREAK_WIN_RATE_POLICY_DRIFT")
    axis_policy = production["strategies"]["break_and_continue"]["new_axis"]
    if axis_policy.get("axis") != BREAK_SIDE_RECOVERY_AXIS:
        raise RuntimeError("BREAK_RECOVERY_AXIS_POLICY_DRIFT")

    external_ids = {str(x["id"]) for x in a5["external_evidence"]}
    for ids in list(base.EVIDENCE_BY_AXIS.values()) + [BREAK_SIDE_RECOVERY_EVIDENCE]:
        if not set(ids).issubset(external_ids):
            raise RuntimeError("DISTINCT_CHILD_EVIDENCE_NOT_FROZEN")

    results: dict[str, Any] = {}
    ready: list[dict[str, Any]] = []
    for sid in base.A4:
        strategy_row = evaluate(sid, read(parent_paths[sid]), hard)
        results[sid] = strategy_row
        ready.extend([x for x in strategy_row["candidates"] if x["development_candidate_ready"]])

    ready.sort(key=lambda x: (
        len((x.get("production_gate") or {}).get("blockers") or []),
        int((x.get("concentration") or {}).get("blocker_count") or 0),
        -_num((x.get("metrics") or {}).get("win_rate"), -1.0),
        -_num((x.get("metrics") or {}).get("net_expectancy_bps"), -1e18),
        str(x.get("candidate_id") or ""),
    ))
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_A4_DISTINCT_CHILD_REPAIR_READY" if ready else "HOLD_A4_NEXT_DISTINCT_CHILD_REQUIRED",
        "strategies": results,
        "development_ready_count": len(ready),
        "next_distinct_child_candidate": ready[0] if ready else None,
        "production_policy": str(PRODUCTION_POLICY.relative_to(base.ROOT)),
        "policy": {
            "one_axis_only": True,
            "post_outcome_threshold_rescue_forbidden": True,
            "post_outcome_trade_deletion_forbidden": True,
            "parameter_sweep_forbidden": True,
            "development_only": True,
            "fresh_prospective_validation_required": True,
            "parent_signal_geometry_frozen_except_explicit_separate_child_axis": True,
            "cost_model_frozen": True,
            "break_production_min_win_rate": BREAK_PRODUCTION_MIN_WIN_RATE,
            "trade_count_non_decrease_required": True,
            "net_pnl_non_decrease_required": True,
            "net_expectancy_non_decrease_required": True,
            "profit_factor_non_decrease_required": True,
            "concentration_improvement_required": True,
            "existing_incumbents_not_retroactively_invalidated": True,
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
    result["receipt_sha256"] = base.stable(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    production = read(PRODUCTION_POLICY)
    assert production["state"] == "FROZEN_PRODUCTION_CANDIDATE_GATE"
    break_policy = production["strategies"]["break_and_continue"]
    assert float(break_policy["minimum_win_rate"]) == BREAK_PRODUCTION_MIN_WIN_RATE
    assert break_policy["new_axis"]["axis"] == BREAK_SIDE_RECOVERY_AXIS
    assert break_policy["new_axis"]["threshold_sweep"] is False
    assert production["global_requirements"]["trade_count_non_decrease"] is True

    parent = {"trades": 10, "net_pnl_bps": 100.0, "net_expectancy_bps": 10.0, "profit_factor": 2.0}
    good = {
        "metrics": {"trades": 10, "win_rate": 0.50, "net_pnl_bps": 101.0, "net_expectancy_bps": 10.1, "profit_factor": 2.1},
        "economic_gate_pass": True,
        "h5_blocker_count_improved_vs_parent": True,
    }
    assert _production_blockers("break_and_continue", parent, good) == []

    low_wr = json.loads(json.dumps(good))
    low_wr["metrics"]["win_rate"] = 0.499999
    assert "WIN_RATE_BELOW_PRODUCTION_FLOOR_0_50" in _production_blockers("break_and_continue", parent, low_wr)

    low_density = json.loads(json.dumps(good))
    low_density["metrics"]["trades"] = 9
    assert "TRADE_COUNT_DECREASE" in _production_blockers("break_and_continue", parent, low_density)

    low_econ = json.loads(json.dumps(good))
    low_econ["metrics"]["net_pnl_bps"] = 99.0
    assert "NET_PNL_BELOW_PARENT" in _production_blockers("break_and_continue", parent, low_econ)

    print("PASS_A1_A4_DISTINCT_CHILD_REPAIR_BATCH_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--break-parent", type=Path)
    ap.add_argument("--supertrend-parent", type=Path)
    ap.add_argument("--keltner-parent", type=Path)
    ap.add_argument("--macd-parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_a4_distinct_child_repair_batch_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    paths = {
        "break_and_continue": args.break_parent,
        "supertrend_pullback": args.supertrend_parent,
        "keltner_trend": args.keltner_parent,
        "trend_ma_macd": args.macd_parent,
    }
    if any(v is None for v in paths.values()):
        raise SystemExit("all four exact parent receipts required")
    result = run({k: v for k, v in paths.items() if v is not None}, args.out)
    print("A1_A4_DISTINCT_CHILD_REPAIR_V2=" + json.dumps({
        "state": result["state"],
        "ready": result["development_ready_count"],
        "next": (result.get("next_distinct_child_candidate") or {}).get("candidate_id"),
        "break_wr_floor": result["policy"]["break_production_min_win_rate"],
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

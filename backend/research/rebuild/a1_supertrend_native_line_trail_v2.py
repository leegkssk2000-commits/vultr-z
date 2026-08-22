#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from backend.research.rebuild.a1_a4_exact_parent_repair_batch_v1 import _maps, _signal_index, read, validate_parent
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import concentration, economic_gate, metrics
from backend.research.rebuild.policy_kernel_v1 import atr
from backend.research.rebuild.trend_policy_batch_v1 import TrendPolicyConfig, _supertrend_state

ROOT = Path(__file__).resolve().parents[3]
A5 = ROOT / "backend/research/contracts/a1_a5_no_idle_research_v1.json"
HARD = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
SCHEMA = "zel.a1.supertrend_pullback.native_line_trail.v2"
AXIS = "EXIT_TRAILING_ONLY"
VARIANT = "NATIVE_SUPERTREND_PRIOR_BAR_LINE"
GENERATION_INDEX = 2
EVIDENCE_IDS = ("A5E1", "A5E2")


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def _trail_child(parent: dict[str, Any], bars_by: dict[str, list[dict[str, Any]]], maps: dict[str, dict[int, int]]) -> list[dict[str, Any]]:
    cfg = TrendPolicyConfig()
    out: list[dict[str, Any]] = []
    for raw in parent.get("trades") or []:
        trade = dict(raw)
        symbol = str(trade["symbol"])
        side = str(trade["side"])
        bars = bars_by[symbol]
        sidx = _signal_index(trade, maps)
        eidx = maps[symbol].get(int(trade["entry_ts"]))
        xidx = maps[symbol].get(int(trade["exit_ts"]))
        if sidx is None or eidx is None or xidx is None or sidx < 20 or xidx < eidx:
            raise RuntimeError(f"PARENT_TRADE_BAR_IDENTITY_MISSING:{symbol}:{trade.get('signal_ts')}")

        signal_close = float(bars[sidx]["close"])
        a = atr(bars[: sidx + 1], cfg.atr_len)
        initial_stop = signal_close - 1.5 * a if side == "long" else signal_close + 1.5 * a
        trail = initial_stop
        entry = float(trade["entry"])
        parent_exit_ts = int(trade["exit_ts"])
        new_exit = float(trade["exit"])
        new_exit_ts = parent_exit_ts
        new_reason = str(trade.get("reason") or "PARENT_EXIT")

        for j in range(eidx, xidx + 1):
            if j > eidx:
                st_line, direction = _supertrend_state(bars[:j], cfg)  # prior completed bar only
                if side == "long" and direction == 1:
                    trail = max(trail, float(st_line))
                elif side == "short" and direction == -1:
                    trail = min(trail, float(st_line))
            bar = bars[j]
            op, hi, lo = float(bar["open"]), float(bar["high"]), float(bar["low"])
            ts = int(bar["ts_ms"])
            if ts >= parent_exit_ts:
                break
            if side == "long" and lo <= trail:
                new_exit = op if op < trail else trail
                new_exit_ts = ts
                new_reason = "NATIVE_SUPERTREND_PRIOR_BAR_TRAIL"
                break
            if side == "short" and hi >= trail:
                new_exit = op if op > trail else trail
                new_exit_ts = ts
                new_reason = "NATIVE_SUPERTREND_PRIOR_BAR_TRAIL"
                break

        if new_exit_ts < parent_exit_ts:
            gross = (new_exit - entry) / entry * 10_000 if side == "long" else (entry - new_exit) / entry * 10_000
            cost = float(trade.get("realized_cost_bps") or 0.0)
            trade["exit"] = float(new_exit)
            trade["exit_ts"] = int(new_exit_ts)
            trade["reason"] = new_reason
            trade["gross_bps"] = gross
            trade["net_bps"] = gross - cost
            trade["parent_realized_cost_bps_conservative_upper_bound"] = cost
        trade["trail_variant"] = VARIANT
        out.append(trade)
    return out


def run(parent_path: Path, output: Path) -> dict[str, Any]:
    parent = read(parent_path)
    validate_parent("supertrend_pullback", parent)
    hard = read(HARD)
    a5 = read(A5)
    axes = {str(x["axis"]) for x in a5["strategies"]["supertrend_pullback"]["repair_axes"]}
    if AXIS not in axes:
        raise RuntimeError("EXIT_TRAILING_AXIS_NOT_FROZEN")
    external = {str(x["id"]) for x in a5["external_evidence"]}
    if not set(EVIDENCE_IDS).issubset(external):
        raise RuntimeError("TRAIL_EVIDENCE_NOT_FROZEN")
    h1_max = int(hard["h1_strategy_family_kill_gate"]["maximum_generations_per_axis_data_sha"])
    if GENERATION_INDEX > h1_max:
        raise RuntimeError(f"H1_GENERATION_CAP_EXCEEDED:{GENERATION_INDEX}>{h1_max}")

    bars_by, maps = _maps(parent)
    parent_trades = [dict(x) for x in parent.get("trades") or []]
    child = _trail_child(parent, bars_by, maps)
    pm = metrics(parent_trades)
    ph5 = concentration(parent_trades, bars_by, maps, hard)
    cm = metrics(child)
    ch5 = concentration(child, bars_by, maps, hard)
    retention = 100.0
    econ_ok, econ_blockers = economic_gate(cm, retention, hard)
    h5_improved = int(ch5["blocker_count"]) < int(ph5["blocker_count"])
    changed_exits = sum(1 for p, c in zip(parent_trades, child) if int(p["exit_ts"]) != int(c["exit_ts"]))

    candidate = {
        "candidate_id": "supertrend_pullback__exit_trailing__native_supertrend_prior_bar_line_v2",
        "strategy_id": "supertrend_pullback",
        "parent_receipt_sha256": parent.get("receipt_sha256"),
        "changed_axis": AXIS,
        "changed_variant": VARIANT,
        "changed_axis_count": 1,
        "generation_index_within_axis_data_sha": GENERATION_INDEX,
        "h1_maximum_generations_per_axis_data_sha": h1_max,
        "evidence_ids": list(EVIDENCE_IDS),
        "entry_identity_preserved": True,
        "initial_stop_geometry_preserved": True,
        "timeout_preserved": True,
        "cost_model_preserved": True,
        "parent_realized_cost_retained_as_conservative_upper_bound": True,
        "prior_completed_bar_only": True,
        "numeric_threshold_sweep": False,
        "post_outcome_threshold_rescue": False,
        "completed_trades": len(child),
        "changed_exit_count": changed_exits,
        "trade_retention_pct": retention,
        "metrics": cm,
        "concentration": ch5,
        "economic_gate_pass": econ_ok,
        "economic_gate_blockers": econ_blockers,
        "h5_blocker_count_improved_vs_parent": h5_improved,
        "development_candidate_ready": bool(econ_ok and h5_improved and changed_exits > 0),
        "trade_identity_sha256": stable([(x["symbol"], x["signal_ts"], x["entry_ts"], x["side"]) for x in child]),
    }
    candidate["candidate_sha256"] = stable(candidate)
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_SUPERTREND_NATIVE_LINE_TRAIL_READY" if candidate["development_candidate_ready"] else "HOLD_SUPERTREND_EXIT_TRAILING_AXIS_EXHAUSTED",
        "strategy_id": "supertrend_pullback",
        "parent_metrics": pm,
        "parent_concentration": ph5,
        "candidate": candidate,
        "development_ready_count": 1 if candidate["development_candidate_ready"] else 0,
        "next_candidate": candidate if candidate["development_candidate_ready"] else None,
        "policy": {
            "exit_axis_generation_two_of_two": True,
            "h1_generation_cap_enforced": True,
            "native_supertrend_line_only": True,
            "trail_observable_on_prior_completed_bar_only": True,
            "entry_initial_stop_timeout_cost_frozen": True,
            "development_only": True,
            "fresh_prospective_validation_required": True,
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
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    hard = read(HARD)
    a5 = read(A5)
    axes = {str(x["axis"]) for x in a5["strategies"]["supertrend_pullback"]["repair_axes"]}
    assert AXIS in axes
    assert GENERATION_INDEX == 2
    assert GENERATION_INDEX <= int(hard["h1_strategy_family_kill_gate"]["maximum_generations_per_axis_data_sha"])
    assert hard["survivor_gate"]["minimum_retention_pct"] == 60.0
    print("PASS_A1_SUPERTREND_NATIVE_LINE_TRAIL_V2_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_supertrend_native_line_trail_v2.json"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.parent is None:
        raise SystemExit("--parent required")
    result = run(args.parent, args.out)
    print("A1_SUPERTREND_NATIVE_LINE_TRAIL_V2=" + json.dumps({"state": result["state"], "ready": result["development_ready_count"], "next": (result.get("next_candidate") or {}).get("candidate_id"), "receipt": result["receipt_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

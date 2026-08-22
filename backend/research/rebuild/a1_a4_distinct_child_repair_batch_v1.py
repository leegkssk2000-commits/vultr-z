#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_a4_exact_parent_repair_batch_v1 import (
    _maps,
    _signal_index,
    read,
    trade_identity,
    validate_parent,
)
from backend.research.rebuild.a1_trend_rider_exact_parent_repair_batch_v1 import (
    concentration,
    economic_gate,
    metrics,
)
from backend.research.rebuild.policy_kernel_v1 import atr, ema

ROOT = Path(__file__).resolve().parents[3]
A5_CONTRACT = ROOT / "backend/research/contracts/a1_a5_no_idle_research_v1.json"
HARDENING_POLICY = ROOT / "backend/research/zel_economic_hardening_policy_v1.json"
SCHEMA = "zel.a1.a4.distinct_child_repair_batch.v1"
A4 = ("break_and_continue", "supertrend_pullback", "keltner_trend", "trend_ma_macd")
HOUR_MS = 3_600_000

EVIDENCE_BY_AXIS = {
    "BREAKOUT_PERSISTENCE_OWNER_ONLY": ("A5E2", "A5E3"),
    "COST_TURNOVER_COMPRESSION_ONLY": ("A5E2",),
    "EXIT_TRAILING_ONLY": ("A5E1", "A5E2"),
}


def stable(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str).encode()).hexdigest()


def _candidate(
    *, strategy_id: str, parent: Mapping[str, Any], axis: str, variant: str,
    child_trades: list[dict[str, Any]], parent_trades: list[dict[str, Any]],
    bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]],
    hard: Mapping[str, Any], entry_identity_preserved: bool, exit_only: bool,
    notes: list[str],
) -> dict[str, Any]:
    parent_m = metrics(parent_trades)
    parent_h5 = concentration(parent_trades, bars_by, maps, hard)
    child_m = metrics(child_trades)
    retention = 100.0 * len(child_trades) / max(1, len(parent_trades))
    child_h5 = concentration(child_trades, bars_by, maps, hard)
    econ_ok, econ_blockers = economic_gate(child_m, retention, hard)
    h5_improved = int(child_h5["blocker_count"]) < int(parent_h5["blocker_count"])
    row = {
        "candidate_id": f"{strategy_id}__distinct_child__{axis.lower()}__{variant.lower()}",
        "strategy_id": strategy_id,
        "parent_receipt_sha256": parent.get("receipt_sha256"),
        "changed_axis": axis,
        "changed_variant": variant,
        "changed_axis_count": 1,
        "evidence_ids": list(EVIDENCE_BY_AXIS[axis]),
        "entry_identity_preserved": entry_identity_preserved,
        "exit_only": exit_only,
        "parent_signal_geometry_changed": False,
        "parent_initial_risk_geometry_changed": False,
        "parent_timeout_changed": False,
        "parent_cost_model_changed": False,
        "post_outcome_trade_deletion": False,
        "parameter_sweep": False,
        "completed_trades": len(child_trades),
        "trade_retention_pct": retention,
        "metrics": child_m,
        "concentration": child_h5,
        "economic_gate_pass": econ_ok,
        "economic_gate_blockers": econ_blockers,
        "h5_blocker_count_improved_vs_parent": h5_improved,
        "development_candidate_ready": bool(econ_ok and h5_improved),
        "trade_identity_sha256": stable(sorted(trade_identity(x) for x in child_trades)),
        "notes": notes,
    }
    row["candidate_sha256"] = stable(row)
    return row


def _breakout_persistence(
    parent: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]], variant: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in parent.get("trades") or []:
        trade = dict(raw)
        symbol = str(trade["symbol"])
        idx = _signal_index(trade, maps)
        if idx is None or idx < 56:
            continue
        bars = bars_by[symbol]
        side = str(trade["side"])
        if variant == "DIRECTIONAL_BODY_PERSISTENCE":
            keep = float(bars[idx]["close"]) > float(bars[idx]["open"]) if side == "long" else float(bars[idx]["close"]) < float(bars[idx]["open"])
        elif variant == "DUAL_EMA_SLOPE_PERSISTENCE":
            closes = [float(x["close"]) for x in bars[: idx + 1]]
            fast, slow = ema(closes, 21), ema(closes, 55)
            keep = (fast[-1] > fast[-2] and slow[-1] >= slow[-2]) if side == "long" else (fast[-1] < fast[-2] and slow[-1] <= slow[-2])
        else:
            raise RuntimeError(f"UNKNOWN_BREAKOUT_PERSISTENCE_VARIANT:{variant}")
        if keep:
            out.append(trade)
    return out


def _turnover_compression(parent: Mapping[str, Any], variant: str) -> list[dict[str, Any]]:
    trades = sorted((dict(x) for x in (parent.get("trades") or [])), key=lambda x: (int(x["signal_ts"]), str(x["symbol"]), str(x["side"])))
    accepted: list[dict[str, Any]] = []
    last: dict[tuple[str, ...], int] = {}
    cooldown_ms = 2 * HOUR_MS  # frozen parent DecisionIntent cooldown.bars=2 on 1h A4 policies
    for trade in trades:
        symbol, side, ts = str(trade["symbol"]), str(trade["side"]), int(trade["signal_ts"])
        key = (symbol, side) if variant == "PARENT_2BAR_SAME_SIDE" else (symbol,)
        prev = last.get(key)
        if prev is not None and ts - prev <= cooldown_ms:
            continue
        accepted.append(trade)
        last[key] = ts
    return accepted


def _supertrend_exit_trailing(
    parent: Mapping[str, Any], bars_by: Mapping[str, list[dict[str, Any]]], maps: Mapping[str, dict[int, int]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in parent.get("trades") or []:
        trade = dict(raw)
        symbol, side = str(trade["symbol"]), str(trade["side"])
        bars = bars_by[symbol]
        sidx = _signal_index(trade, maps)
        eidx = maps[symbol].get(int(trade["entry_ts"]))
        xidx = maps[symbol].get(int(trade["exit_ts"]))
        if sidx is None or eidx is None or xidx is None or sidx < 14 or xidx < eidx:
            out.append(trade)
            continue
        signal_close = float(bars[sidx]["close"])
        a = atr(bars[: sidx + 1], 14)
        initial_stop = signal_close - 1.5 * a if side == "long" else signal_close + 1.5 * a
        entry = float(trade["entry"])
        risk = abs(entry - initial_stop)
        if risk <= 0:
            out.append(trade)
            continue
        active = False
        trail: float | None = None
        new_exit = float(trade["exit"])
        new_exit_ts = int(trade["exit_ts"])
        new_reason = str(trade.get("reason") or "PARENT_EXIT")
        for j in range(eidx, xidx + 1):
            bar = bars[j]
            op, hi, lo = float(bar["open"]), float(bar["high"]), float(bar["low"])
            if trail is not None and j > eidx:
                if side == "long" and lo <= trail:
                    new_exit = min(op, trail) if op < trail else trail
                    new_exit_ts = int(bar["ts_ms"])
                    new_reason = "TRAIL_PRIOR_BAR_STRUCTURE"
                    break
                if side == "short" and hi >= trail:
                    new_exit = max(op, trail) if op > trail else trail
                    new_exit_ts = int(bar["ts_ms"])
                    new_reason = "TRAIL_PRIOR_BAR_STRUCTURE"
                    break
            if int(bar["ts_ms"]) >= int(trade["exit_ts"]):
                break
            if not active:
                active = hi >= entry + risk if side == "long" else lo <= entry - risk
            if active:
                structural = lo if side == "long" else hi
                if side == "long":
                    structural = max(initial_stop, structural)
                    trail = structural if trail is None else max(trail, structural)
                else:
                    structural = min(initial_stop, structural)
                    trail = structural if trail is None else min(trail, structural)
        if new_exit_ts < int(trade["exit_ts"]):
            gross = (new_exit - entry) / entry * 10_000 if side == "long" else (entry - new_exit) / entry * 10_000
            cost = float(trade.get("realized_cost_bps") or 0.0)
            trade["exit"] = new_exit
            trade["exit_ts"] = new_exit_ts
            trade["reason"] = new_reason
            trade["gross_bps"] = gross
            trade["net_bps"] = gross - cost
            trade["parent_realized_cost_bps_conservative_upper_bound"] = cost
        out.append(trade)
    return out


def evaluate(strategy_id: str, parent: Mapping[str, Any], hard: Mapping[str, Any]) -> dict[str, Any]:
    validate_parent(strategy_id, parent)
    bars_by, maps = _maps(parent)
    parent_trades = [dict(x) for x in parent.get("trades") or []]
    candidates: list[dict[str, Any]] = []

    if strategy_id == "break_and_continue":
        for variant in ("DIRECTIONAL_BODY_PERSISTENCE", "DUAL_EMA_SLOPE_PERSISTENCE"):
            child = _breakout_persistence(parent, bars_by, maps, variant)
            candidates.append(_candidate(
                strategy_id=strategy_id, parent=parent, axis="BREAKOUT_PERSISTENCE_OWNER_ONLY", variant=variant,
                child_trades=child, parent_trades=parent_trades, bars_by=bars_by, maps=maps, hard=hard,
                entry_identity_preserved=True, exit_only=False,
                notes=["completed-signal-bar ownership only", "no delayed confirmation or new trade admission"],
            ))
        for variant in ("PARENT_2BAR_SAME_SIDE", "PARENT_2BAR_ANY_SIDE"):
            child = _turnover_compression(parent, variant)
            candidates.append(_candidate(
                strategy_id=strategy_id, parent=parent, axis="COST_TURNOVER_COMPRESSION_ONLY", variant=variant,
                child_trades=child, parent_trades=parent_trades, bars_by=bars_by, maps=maps, hard=hard,
                entry_identity_preserved=True, exit_only=False,
                notes=["uses frozen parent cooldown.bars=2", "subset-only duplicate/re-entry compression"],
            ))

    elif strategy_id == "supertrend_pullback":
        child = _supertrend_exit_trailing(parent, bars_by, maps)
        candidates.append(_candidate(
            strategy_id=strategy_id, parent=parent, axis="EXIT_TRAILING_ONLY", variant="ONE_R_THEN_PRIOR_BAR_STRUCTURE",
            child_trades=child, parent_trades=parent_trades, bars_by=bars_by, maps=maps, hard=hard,
            entry_identity_preserved=True, exit_only=True,
            notes=["activation at parent initial-risk favorable progress", "trail derived only from prior completed bar", "parent realized cost retained as conservative upper bound"],
        ))

    elif strategy_id in ("keltner_trend", "trend_ma_macd"):
        for variant in ("PARENT_2BAR_SAME_SIDE", "PARENT_2BAR_ANY_SIDE"):
            child = _turnover_compression(parent, variant)
            candidates.append(_candidate(
                strategy_id=strategy_id, parent=parent, axis="COST_TURNOVER_COMPRESSION_ONLY", variant=variant,
                child_trades=child, parent_trades=parent_trades, bars_by=bars_by, maps=maps, hard=hard,
                entry_identity_preserved=True, exit_only=False,
                notes=["uses frozen parent cooldown.bars=2", "subset-only duplicate/re-entry compression"],
            ))

    candidates.sort(key=lambda x: (
        not bool(x["development_candidate_ready"]),
        int(x["concentration"]["blocker_count"]),
        -float(x["metrics"].get("net_expectancy_bps") or -1e18),
        -float(x["metrics"].get("profit_factor") or 0.0),
        float(x["metrics"].get("drawdown_bps") or 1e18),
        -float(x["trade_retention_pct"]),
        str(x["candidate_id"]),
    ))
    ready = [x for x in candidates if x["development_candidate_ready"]]
    bars = bars_by
    return {
        "strategy_id": strategy_id,
        "parent_receipt_sha256": parent.get("receipt_sha256"),
        "parent_metrics": metrics(parent_trades),
        "parent_concentration": concentration(parent_trades, bars, maps, hard),
        "candidates": candidates,
        "development_ready_count": len(ready),
        "next_distinct_child_candidate": ready[0] if ready else None,
    }


def run(parent_paths: Mapping[str, Path], output: Path) -> dict[str, Any]:
    a5, hard = read(A5_CONTRACT), read(HARDENING_POLICY)
    external_ids = {str(x["id"]) for x in a5["external_evidence"]}
    for ids in EVIDENCE_BY_AXIS.values():
        if not set(ids).issubset(external_ids):
            raise RuntimeError("DISTINCT_CHILD_EVIDENCE_NOT_FROZEN")
    results: dict[str, Any] = {}
    ready: list[dict[str, Any]] = []
    for sid in A4:
        row = evaluate(sid, read(parent_paths[sid]), hard)
        results[sid] = row
        ready.extend([x for x in row["candidates"] if x["development_candidate_ready"]])
    ready.sort(key=lambda x: (
        int(x["concentration"]["blocker_count"]),
        -float(x["metrics"].get("net_expectancy_bps") or -1e18),
        -float(x["metrics"].get("profit_factor") or 0.0),
        float(x["metrics"].get("drawdown_bps") or 1e18),
        str(x["candidate_id"]),
    ))
    result = {
        "schema_version": SCHEMA,
        "state": "PASS_A4_DISTINCT_CHILD_REPAIR_READY" if ready else "HOLD_A4_NEXT_DISTINCT_CHILD_REQUIRED",
        "strategies": results,
        "development_ready_count": len(ready),
        "next_distinct_child_candidate": ready[0] if ready else None,
        "policy": {
            "one_axis_only": True,
            "post_outcome_threshold_rescue_forbidden": True,
            "parameter_sweep_forbidden": True,
            "development_only": True,
            "fresh_prospective_validation_required": True,
            "parent_signal_geometry_frozen_except_explicit_separate_child_axis": True,
            "cost_model_frozen": True,
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
    a5 = read(A5_CONTRACT)
    axes = {sid: {x["axis"] for x in a5["strategies"][sid]["repair_axes"]} for sid in A4}
    assert "BREAKOUT_PERSISTENCE_OWNER_ONLY" in axes["break_and_continue"]
    assert "COST_TURNOVER_COMPRESSION_ONLY" in axes["break_and_continue"]
    assert "EXIT_TRAILING_ONLY" in axes["supertrend_pullback"]
    assert "COST_TURNOVER_COMPRESSION_ONLY" in axes["keltner_trend"]
    assert "COST_TURNOVER_COMPRESSION_ONLY" in axes["trend_ma_macd"]
    assert read(HARDENING_POLICY)["survivor_gate"]["minimum_retention_pct"] == 60.0
    print("PASS_A1_A4_DISTINCT_CHILD_REPAIR_BATCH_V1_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--break-parent", type=Path)
    ap.add_argument("--supertrend-parent", type=Path)
    ap.add_argument("--keltner-parent", type=Path)
    ap.add_argument("--macd-parent", type=Path)
    ap.add_argument("--out", type=Path, default=Path("out/a1_a4_distinct_child_repair_batch_v1.json"))
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
    print("A1_A4_DISTINCT_CHILD_REPAIR=" + json.dumps({
        "state": result["state"],
        "ready": result["development_ready_count"],
        "next": (result.get("next_distinct_child_candidate") or {}).get("candidate_id"),
        "receipt_sha256": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as base

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_break_supertrend_mom_filter_salvage_freeze_v1.json"
LATEST = ROOT / "backend/research/rebuild/a1_break_supertrend_mom_filter_salvage_fresh_latest.json"
SCHEMA = "zel.a1.break.supertrend_mom_filter_salvage.fresh.receipt.v1"
BOUNDARY_UTC = "2026-08-31T04:00:00Z"
BOUNDARY_MS = 1788148800000
COST_BPS = 20.0
MIN_FRESH_T = 6
SYMBOLS = ("BTC-USDT", "LINK-USDT")
HOLD_BARS = 6
ENTRY_EXPR = "close > lag('highest50',1) and ema20 > ema50 and vol_ratio(20) >= 1.1 and abs(ret1) >= 1.00 * retstd20 and ret1 > 0"
FEATURES = [
    {"name": "ema20", "formula": "ema(close,20)"},
    {"name": "ema50", "formula": "ema(close,50)"},
    {"name": "highest50", "formula": "highest(high,50)"},
    {"name": "ret1", "formula": "ret(1)"},
    {"name": "retstd20", "formula": "std(ret1,20)"},
]
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def stable(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def assert_contract(c: Mapping[str, Any]) -> None:
    assert c["schema_version"] == "zel.a1.break.supertrend_mom_filter_salvage.freeze.v1"
    assert c["state"] == "FROZEN_CONFIRMED_HISTORICAL_SALVAGE_CHILD_PRE_FRESH"
    assert c["child_id"] == "break_supertrend_mom1p00_filter_long_4h_h6_salvage_v1"
    assert c["activation_id"] == "g4.break.salvage.supertrend_mom1p00.20260831v1"
    assert c["cohort_id"] == "g4.break.salvage.supertrend_mom1p00.c1"
    assert c["prospective_boundary"]["utc"] == BOUNDARY_UTC
    assert int(c["prospective_boundary"]["ms"]) == BOUNDARY_MS
    assert tuple(c["symbol_universe"]) == SYMBOLS
    assert c["entry_semantics"]["type"] == "ADD_ONLY_FILTER_ON_PARENT_BREAK_SIGNAL"
    assert c["entry_semantics"]["future_bar_access"] is False
    assert c["exit_semantics"]["inherit_parent_exit"] is True
    assert int(c["exit_semantics"]["max_hold_bars"]) == HOLD_BARS
    assert float(c["cost_model"]["cost_bps_per_trade"]) == COST_BPS
    assert int(c["fresh_policy"]["minimum_fresh_T_before_formal_gate"]) == MIN_FRESH_T
    assert c["fresh_policy"]["roadmap_blocking"] is False


def metrics(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    vals = [float(x["net_bps"]) for x in trades]
    wins = [x for x in vals if x > 0]
    losses = [-x for x in vals if x < 0]
    gp = sum(wins)
    gl = sum(losses)
    eq = peak = dd = 0.0
    for value in vals:
        eq += value
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "closed_T": len(vals),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(vals) if vals else None,
        "net_pnl_bps": sum(vals),
        "net_expectancy_bps": sum(vals) / len(vals) if vals else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "drawdown_bps": dd,
        "cost_bps_per_trade": COST_BPS,
    }


def collect(now_ms: int, c: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    source: dict[str, Any] = {}
    for symbol in SYMBOLS:
        rows = base._bars(symbol, "4h", BOUNDARY_MS, now_ms)
        source[symbol] = {
            "closed_4h_bars": len(rows),
            "first_open_ts": int(rows[0]["ts"]) if rows else None,
            "last_open_ts": int(rows[-1]["ts"]) if rows else None,
        }
        if len(rows) < 60:
            continue
        _, engine = base._features(rows, {"features": FEATURES})
        engine.validate(ENTRY_EXPR)
        i = 50
        while i < len(rows) - 1:
            signal_ts = int(rows[i]["ts"])
            if signal_ts < BOUNDARY_MS:
                i += 1
                continue
            try:
                fire = bool(engine.eval(ENTRY_EXPR, i))
            except (TypeError, ValueError, ZeroDivisionError):
                fire = False
            if not fire:
                i += 1
                continue
            entry_i = i + 1
            exit_i = entry_i + HOLD_BARS - 1
            if exit_i >= len(rows):
                break
            entry_px = float(rows[entry_i]["open"])
            exit_px = float(rows[exit_i]["close"])
            gross = (exit_px / entry_px - 1.0) * 10000.0
            net = gross - COST_BPS
            key = {
                "activation_id": c["activation_id"],
                "cohort_id": c["cohort_id"],
                "child_id": c["child_id"],
                "symbol": symbol,
                "signal_ts": signal_ts,
                "entry_ts": int(rows[entry_i]["ts"]),
                "exit_ts": int(rows[exit_i]["ts"]),
                "side": "long",
            }
            trades.append({
                "closed_trade_id": stable(key),
                **key,
                "entry_px": entry_px,
                "exit_px": exit_px,
                "gross_bps": gross,
                "cost_bps": COST_BPS,
                "net_bps": net,
            })
            i = exit_i + 1
    trades.sort(key=lambda x: (x["exit_ts"], x["signal_ts"], x["symbol"], x["closed_trade_id"]))
    ids = [x["closed_trade_id"] for x in trades]
    if len(ids) != len(set(ids)):
        raise RuntimeError("DUPLICATE_FRESH_TRADE_ID")
    if any(int(x["signal_ts"]) < BOUNDARY_MS for x in trades):
        raise RuntimeError("PREBOUNDARY_TRADE_FORBIDDEN")
    return trades, source


def previous_ids(previous: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(previous, Mapping) or previous.get("schema_version") != SCHEMA:
        return set()
    return {str(x["closed_trade_id"]) for x in previous.get("closed_trades") or []}


def run(output: Path, previous_path: Path | None = None, now_ms: int | None = None) -> dict[str, Any]:
    c = read(CONTRACT)
    assert_contract(c)
    current_ms = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)
    previous = read(previous_path) if previous_path and previous_path.is_file() else (read(LATEST) if LATEST.is_file() else None)
    trades, source = collect(current_ms, c) if current_ms >= BOUNDARY_MS else ([], {})
    old_ids = previous_ids(previous)
    new_ids = {str(x["closed_trade_id"]) for x in trades}
    if not old_ids.issubset(new_ids):
        raise RuntimeError("APPEND_ONLY_REGRESSION")
    newly_closed = sorted(new_ids - old_ids)
    m = metrics(trades)
    if current_ms < BOUNDARY_MS:
        state = "WAIT_FRESH_BOUNDARY"
    elif int(m["closed_T"]) < MIN_FRESH_T:
        state = "FRESH_ACTIVE_WAIT_MIN_T"
    else:
        state = "FRESH_MIN_SAMPLE_REACHED_PENDING_CANONICAL_GATE"
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.fromtimestamp(current_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "child_id": c["child_id"],
        "parent_lane_id": c["parent_lane_id"],
        "activation_id": c["activation_id"],
        "cohort_id": c["cohort_id"],
        "prospective_boundary_utc": BOUNDARY_UTC,
        "prospective_boundary_ms": BOUNDARY_MS,
        "boundary_reached": current_ms >= BOUNDARY_MS,
        "symbol_universe": list(SYMBOLS),
        "fixed_entry_rule": ENTRY_EXPR,
        "fixed_cost_bps_per_trade": COST_BPS,
        "max_hold_bars": HOLD_BARS,
        "historical_credit_T": 0,
        "formal_g5_credit_T": 0,
        "fresh_T": int(m["closed_T"]),
        "minimum_fresh_T_before_gate": MIN_FRESH_T,
        "minimum_fresh_T_reached": int(m["closed_T"]) >= MIN_FRESH_T,
        "closed_trades": trades,
        "new_closed_trade_ids": newly_closed,
        "new_closed_T": len(newly_closed),
        "metrics": m,
        "source_summary": source,
        "old_history_union": False,
        "post_confirmation_retune": False,
        "threshold_sweep": False,
        "parent_exit_mutated": False,
        "roadmap_blocking": False,
        "fresh_failure_invalidates_historical_candidate": True,
        "paid_provider_calls": 0,
        "openai_calls": 0,
        "gemini_calls": 0,
        "next": "WAIT_FOR_BOUNDARY" if current_ms < BOUNDARY_MS else ("ACCUMULATE_FRESH_CLOSED_T_IN_SHADOW_PAPER" if int(m["closed_T"]) < MIN_FRESH_T else "APPLY_CANONICAL_FRESH_GATE_NO_RETUNE"),
        **AUTH,
    }
    result["receipt_sha256"] = stable({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    c = read(CONTRACT)
    assert_contract(c)
    assert BOUNDARY_MS == 1788148800000
    assert SYMBOLS == ("BTC-USDT", "LINK-USDT")
    assert MIN_FRESH_T == 6 and HOLD_BARS == 6 and COST_BPS == 20.0
    print("PASS_BREAK_SUPERTREND_SALVAGE_FRESH_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_break_supertrend_mom_filter_salvage_fresh_latest.json"))
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--now-ms", type=int)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    r = run(args.output, args.previous, args.now_ms)
    print(json.dumps({"state": r["state"], "fresh_T": r["fresh_T"], "metrics": r["metrics"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

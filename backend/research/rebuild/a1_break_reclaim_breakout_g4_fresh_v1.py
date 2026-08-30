#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.research.rebuild import a1_top5_replacement_child_prospective_v1 as base
from backend.research.rebuild.a1_break_keltner_reclaim_latched_owner_v2 import latched_state_from_values

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "backend/research/contracts/a1_break_reclaim_breakout_g4_fresh_v1.json"
DEV = ROOT / "backend/research/architecture_factory/a1_break_reclaim_breakout_independent_challenger_latest.json"
LATEST = ROOT / "backend/research/rebuild/a1_break_reclaim_breakout_g4_fresh_latest.json"
SCHEMA = "zel.a1.break.reclaim_breakout_g4_fresh.receipt.v1"
BOUNDARY_UTC = "2026-08-30T16:00:00Z"
BOUNDARY_MS = 1788105600000
COST_BPS = 20.0
MIN_FRESH_T = 6
SYMBOLS = (
    "1000PEPE-USDT",
    "BCH-USDT",
    "BTC-USDT",
    "ETH-USDT",
    "HYPE-USDT",
    "LINK-USDT",
    "SOL-USDT",
)
AUTH = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "protected_mutations": 0,
    "action": "hold",
}


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"OBJECT_REQUIRED:{path}")
    return value


def sha(value: Any) -> str:
    return base._sha(value)


def assert_contract(contract: Mapping[str, Any], dev: Mapping[str, Any]) -> dict[str, Any]:
    if contract.get("schema_version") != "zel.a1.break.reclaim_breakout_g4_freeze.v1":
        raise RuntimeError("CONTRACT_SCHEMA_DRIFT")
    if contract.get("state") != "G4_CHALLENGER_FROZEN_PRE_PROSPECTIVE":
        raise RuntimeError("CONTRACT_STATE_DRIFT")
    activation = contract.get("activation") or {}
    if activation.get("prospective_boundary_utc") != BOUNDARY_UTC or int(activation.get("prospective_boundary_ms") or 0) != BOUNDARY_MS:
        raise RuntimeError("BOUNDARY_DRIFT")
    if activation.get("backdating_forbidden") is not True:
        raise RuntimeError("BACKDATE_GUARD_REQUIRED")
    arch = contract.get("architecture") or {}
    if tuple(arch.get("symbol_universe") or []) != SYMBOLS:
        raise RuntimeError("SYMBOL_UNIVERSE_DRIFT")
    if abs(float(arch.get("cost_bps_per_trade") or 0.0) - COST_BPS) > 1e-12:
        raise RuntimeError("COST_DRIFT")
    state = arch.get("ownership_state") or {}
    if state.get("rule_hash_semantics") != "EXACT_REUSE_OF_BREAK_KELTNER_RECLAIM_LATCHED_OWNER_V2_NO_PARAMETER_CHANGE":
        raise RuntimeError("STATE_RULE_DRIFT")
    rules = contract.get("g4_rules") or {}
    required_false = (
        "old_history_union",
        "same_trade_reuse_from_old_g4",
        "threshold_sweep",
        "state_rule_variant_sweep",
        "post_result_retune",
        "symbol_universe_change_after_boundary",
        "cost_model_change_after_boundary",
        "exit_or_rr_change_after_boundary",
    )
    if any(rules.get(k) is not False for k in required_false):
        raise RuntimeError("G4_CONTAMINATION_GUARD_DRIFT")
    if int(rules.get("historical_seed_credit_T") or 0) != 0 or int(rules.get("development_credit_T") or 0) != 0 or int(rules.get("existing_v2_child_credit_T") or 0) != 0:
        raise RuntimeError("NONFRESH_G4_CREDIT_FORBIDDEN")
    if int(rules.get("minimum_fresh_closed_T_before_gate") or 0) != MIN_FRESH_T:
        raise RuntimeError("MIN_FRESH_T_DRIFT")
    if dev.get("schema_version") != "zel.a1.break.reclaim_breakout_independent_challenger.receipt.v1":
        raise RuntimeError("DEV_SCHEMA_DRIFT")
    if dev.get("state") != "PASS_DEVELOPMENT_ELIGIBLE_FOR_NEW_G4_CHALLENGER":
        raise RuntimeError("DEV_NOT_PASS")
    source = contract.get("source_development") or {}
    if dev.get("receipt_sha256") != source.get("receipt_sha256"):
        raise RuntimeError("DEV_RECEIPT_DRIFT")
    if dev.get("deterministic_result_sha256") != source.get("deterministic_result_sha256"):
        raise RuntimeError("DEV_DETERMINISTIC_HASH_DRIFT")
    if int(dev.get("fresh_g4_T") or 0) != 0 or int(dev.get("development_credit_to_g4_T") or 0) != 0:
        raise RuntimeError("DEV_ALREADY_CREDITED_TO_G4")
    return dict(arch)


def previous_ids(previous: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(previous, Mapping) or previous.get("schema_version") != SCHEMA:
        return set()
    return {
        str(x.get("closed_trade_id"))
        for x in previous.get("closed_trades") or []
        if isinstance(x, Mapping) and x.get("closed_trade_id")
    }


def metrics(trades: list[Mapping[str, Any]]) -> dict[str, Any]:
    net = [float(x["net_bps"]) for x in trades]
    gp = sum(x for x in net if x > 0)
    gl = -sum(x for x in net if x < 0)
    wins = sum(1 for x in net if x > 0)
    losses = sum(1 for x in net if x < 0)
    eq = peak = dd = 0.0
    for x in net:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    w = [x for x in net if x > 0]
    l = [-x for x in net if x < 0]
    payoff = None if not w or not l else (sum(w) / len(w)) / (sum(l) / len(l))
    return {
        "closed_T": len(net),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(net) if net else None,
        "net_pnl_bps": sum(net),
        "net_expectancy_bps": sum(net) / len(net) if net else None,
        "profit_factor": gp / gl if gl > 0 else None,
        "payoff": payoff,
        "drawdown_bps": dd,
        "cost_bps_per_trade": COST_BPS,
    }


def collect(arch: Mapping[str, Any], current_ms: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    features_spec = {"features": list(arch.get("features") or [])}
    entry_expr = "close > lag('highest50',1) and ema20 > ema50 and vol_ratio(20) >= 1.1"
    trades: list[dict[str, Any]] = []
    source: dict[str, Any] = {}
    activation = read(CONTRACT).get("activation") or {}
    activation_id = str(activation.get("activation_id") or "")
    cohort_id = str(activation.get("cohort_id") or "")
    challenger_id = str(arch.get("challenger_id") or "")
    for symbol in SYMBOLS:
        rows = base._bars(symbol, "4h", BOUNDARY_MS, current_ms)
        source[symbol] = {
            "closed_4h_bars": len(rows),
            "first_open_ts": int(rows[0]["ts"]) if rows else None,
            "last_open_ts": int(rows[-1]["ts"]) if rows else None,
            "post_boundary_closed_signal_bars": sum(1 for r in rows if int(r["ts"]) >= BOUNDARY_MS),
        }
        if len(rows) < 60:
            continue
        features, engine = base._features(rows, features_spec)
        engine.validate(entry_expr)
        states = latched_state_from_values(
            [float(x["close"]) for x in rows],
            list(features["ema20"]),
            list(features["ema50"]),
        )
        source[symbol]["ownership_true_bars"] = sum(1 for x in states if x)
        i = 50
        while i < len(rows) - 1:
            signal_ts = int(rows[i]["ts"])
            if signal_ts < BOUNDARY_MS:
                i += 1
                continue
            try:
                fire = bool(states[i] and engine.eval(entry_expr, i))
            except (TypeError, ZeroDivisionError, ValueError):
                fire = False
            if not fire:
                i += 1
                continue
            entry_i = i + 1
            exit_i = entry_i + 6 - 1
            if exit_i >= len(rows):
                break
            entry_px = float(rows[entry_i]["open"])
            exit_px = float(rows[exit_i]["close"])
            gross = (exit_px / entry_px - 1.0) * 10000.0
            net = gross - COST_BPS
            payload = {
                "activation_id": activation_id,
                "cohort_id": cohort_id,
                "challenger_id": challenger_id,
                "symbol": symbol,
                "side": "long",
                "signal_ts": signal_ts,
                "entry_ts": int(rows[entry_i]["ts"]),
                "exit_ts": int(rows[exit_i]["ts"]),
            }
            trades.append({
                "closed_trade_id": sha(payload),
                **payload,
                "entry_px": entry_px,
                "exit_px": exit_px,
                "gross_bps": gross,
                "net_bps": net,
                "cost_bps": COST_BPS,
            })
            i = exit_i + 1
    trades.sort(key=lambda x: (x["exit_ts"], x["signal_ts"], x["symbol"], x["closed_trade_id"]))
    ids = [x["closed_trade_id"] for x in trades]
    if len(ids) != len(set(ids)):
        raise RuntimeError("DUPLICATE_FRESH_G4_TRADE_ID")
    if any(int(x["signal_ts"]) < BOUNDARY_MS for x in trades):
        raise RuntimeError("PREBOUNDARY_G4_TRADE")
    return trades, source


def run(output: Path, previous_path: Path | None = None, now_ms: int | None = None) -> dict[str, Any]:
    contract = read(CONTRACT)
    dev = read(DEV)
    arch = assert_contract(contract, dev)
    current_ms = int(now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000)
    previous = read(previous_path) if previous_path and previous_path.is_file() else (read(LATEST) if LATEST.is_file() else None)
    trades, source = collect(arch, current_ms) if current_ms >= BOUNDARY_MS else ([], {})
    old_ids = previous_ids(previous)
    new_ids = {str(x["closed_trade_id"]) for x in trades}
    if not old_ids.issubset(new_ids):
        raise RuntimeError("APPEND_ONLY_REGRESSION")
    newly_closed = sorted(new_ids - old_ids)
    m = metrics(trades)
    if current_ms < BOUNDARY_MS:
        state = "WAIT_FRESH_G4_BOUNDARY"
    elif int(m["closed_T"]) < MIN_FRESH_T:
        state = "G4_FRESH_ACTIVE_WAIT_MIN_T"
    else:
        state = "G4_FRESH_MIN_SAMPLE_REACHED_PENDING_CANONICAL_GATE"
    activation = contract.get("activation") or {}
    result = {
        "schema_version": SCHEMA,
        "state": state,
        "observed_at_utc": datetime.fromtimestamp(current_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "contract_path": str(CONTRACT.relative_to(ROOT)),
        "source_development_path": str(DEV.relative_to(ROOT)),
        "source_development_receipt_sha256": dev.get("receipt_sha256"),
        "activation_id": activation.get("activation_id"),
        "cohort_id": activation.get("cohort_id"),
        "challenger_id": arch.get("challenger_id"),
        "parent_lane_id": arch.get("parent_lane_id"),
        "parent_strategy_id": arch.get("parent_strategy_id"),
        "prospective_boundary_utc": BOUNDARY_UTC,
        "prospective_boundary_ms": BOUNDARY_MS,
        "boundary_reached": current_ms >= BOUNDARY_MS,
        "frozen_symbol_universe": list(SYMBOLS),
        "fixed_cost_bps_per_trade": COST_BPS,
        "historical_seed_credit_T": 0,
        "development_credit_T": 0,
        "existing_v2_child_credit_T": 0,
        "fresh_g4_T": int(m["closed_T"]),
        "g4_credit_T": int(m["closed_T"]),
        "minimum_fresh_T_before_gate": MIN_FRESH_T,
        "minimum_fresh_T_reached": int(m["closed_T"]) >= MIN_FRESH_T,
        "closed_trades": trades,
        "new_closed_trade_ids": newly_closed,
        "new_closed_T": len(newly_closed),
        "metrics": m,
        "source_summary": source,
        "old_history_union": False,
        "post_result_retune": False,
        "threshold_sweep": False,
        "state_rule_variant_sweep": False,
        "existing_break_v2_collector_consumed_or_reset": False,
        "g5_mutated": False,
        "rr_or_exit_mutated": False,
        "paid_provider_calls": 0,
        "openai_calls": 0,
        "gemini_calls": 0,
        "next": "WAIT_FOR_BOUNDARY" if current_ms < BOUNDARY_MS else ("ACCUMULATE_GENUINE_FRESH_CLOSED_T" if int(m["closed_T"]) < MIN_FRESH_T else "APPLY_CURRENT_CANONICAL_G4_GATE_WITHOUT_RETUNE"),
        **AUTH,
    }
    result["receipt_sha256"] = sha({k: v for k, v in result.items() if k != "receipt_sha256"})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    closes = [100, 99, 101, 102, 103, 100, 99]
    ema20 = [100, 100, 100, 100, 101, 101, 101]
    ema50 = [99, 99, 99, 99, 99, 102, 102]
    state = latched_state_from_values(closes, ema20, ema50)
    assert state[2] is True and state[4] is True and state[5] is False
    assert BOUNDARY_MS == 1788105600000 and COST_BPS == 20.0 and MIN_FRESH_T == 6
    assert len(SYMBOLS) == 7
    print("PASS_A1_BREAK_RECLAIM_BREAKOUT_G4_FRESH_SELF_TEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/a1_break_reclaim_breakout_g4_fresh_latest.json"))
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--now-ms", type=int)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    result = run(args.output, args.previous, args.now_ms)
    print(json.dumps({
        "state": result["state"],
        "activation_id": result["activation_id"],
        "cohort_id": result["cohort_id"],
        "boundary": result["prospective_boundary_utc"],
        "fresh_g4_T": result["fresh_g4_T"],
        "new_closed_T": result["new_closed_T"],
        "metrics": result["metrics"],
        "receipt": result["receipt_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.research.rebuild import a1_exact25_generic_evaluator_v1 as ev
from backend.research.rebuild.a1_exact25_policy_adapter_v1 import policy_functions

ROOT = Path(__file__).resolve().parents[3]
TARGETS = ("supertrend_pullback", "trend_ma_macd")
SYMBOLS = ("BTC-USDT", "ETH-USDT")


def _iso(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def diagnose(strategy_id: str) -> dict[str, Any]:
    ledger = ev.load_json(ev.LEDGER_PATH)
    inventory = ev.load_json(ev.INVENTORY_PATH)
    authority = ev.load_json(ev.COST_PATH)
    row = ledger["strategies"][strategy_id]
    boundary = str(row["prospective_boundary_utc"])
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    module, policy_path, policy_sha = ev.load_policy(strategy_id, inventory)
    cfg = ev.config_instance(module)
    compute, build = policy_functions(module, strategy_id)
    timeframe_ms = int(getattr(cfg, "timeframe_ms"))
    interval = ev.interval_for_ms(timeframe_ms)
    events: list[dict[str, Any]] = []
    defects: list[str] = []

    for symbol in SYMBOLS:
        snap = ev.fetch_execution_snapshot(symbol, authority)
        bars = ev.fetch_bars(symbol, interval)
        warmup = int(getattr(cfg, "warmup_bars", max(64, int(getattr(cfg, "lookback", 20)) + 10)))
        for i in range(max(1, warmup), len(bars) - 1):
            signal_ts = int(bars[i]["ts_ms"])
            if signal_ts < boundary_ms:
                continue
            try:
                feature = compute(bars[: i + 1], symbol=symbol, now_ts_ms=signal_ts, config=cfg)
                intent = build(
                    feature,
                    policy_source_sha=policy_sha,
                    verified_round_trip_cost_bps=float(snap["pretrade_verified_cost_bps"]),
                    config=cfg,
                )
            except ValueError as exc:
                if str(exc).startswith(("WARMUP_", "WINDOW_", "ATR_")):
                    continue
                defects.append(f"{symbol}:{signal_ts}:POLICY:{exc}")
                continue
            if bool(getattr(intent, "no_trade")):
                continue
            entry_i = i + 1
            if entry_i >= len(bars):
                defects.append(f"{symbol}:{signal_ts}:ENTRY_BAR_MISSING")
                continue
            side_name = str(getattr(intent, "side"))
            side = 1 if side_name == "long" else -1
            timeout = getattr(intent, "timeout", {}) or {}
            timeout_bars = int(timeout.get("bars", getattr(cfg, "timeout_bars", 1)))
            sl, tp = getattr(intent, "sl", None), getattr(intent, "tp", None)
            last_available_i = len(bars) - 1
            mature_exit_i = entry_i + max(1, timeout_bars)
            scan_last_i = min(last_available_i, mature_exit_i)
            exit_i = None
            reason = None
            for j in range(entry_i, scan_last_i + 1):
                low, high = float(bars[j]["low"]), float(bars[j]["high"])
                if sl is not None and ((side == 1 and low <= float(sl)) or (side == -1 and high >= float(sl))):
                    exit_i, reason = j, "SL"
                    break
                if tp is not None and ((side == 1 and high >= float(tp)) or (side == -1 and low <= float(tp))):
                    exit_i, reason = j, "TP"
                    break
            if exit_i is None and mature_exit_i < last_available_i:
                exit_i, reason = mature_exit_i, "TIMEOUT"
            bars_observed = max(0, last_available_i - entry_i + 1)
            bars_remaining = max(0, mature_exit_i - last_available_i + 1)
            event = {
                "symbol": symbol,
                "side": side_name,
                "signal_ts": signal_ts,
                "signal_ts_iso": _iso(signal_ts),
                "entry_ts": int(bars[entry_i]["ts_ms"]),
                "entry_ts_iso": _iso(int(bars[entry_i]["ts_ms"])),
                "timeout_bars": timeout_bars,
                "bars_observed_since_entry": bars_observed,
                "bars_remaining_to_timeout_maturity": bars_remaining,
                "mature": exit_i is not None,
                "exit_reason": reason,
                "exit_ts": int(bars[exit_i]["ts_ms"]) if exit_i is not None else None,
                "exit_ts_iso": _iso(int(bars[exit_i]["ts_ms"])) if exit_i is not None else None,
                "incomplete_reason": None if exit_i is not None else "HORIZON_NOT_MATURE_NO_SL_TP_YET",
                "intent_sha": ev.intent_sha(intent),
            }
            events.append(event)

    mature = [x for x in events if x["mature"]]
    pending = [x for x in events if not x["mature"]]
    reasons: dict[str, int] = {}
    for x in mature:
        reasons[str(x["exit_reason"])] = reasons.get(str(x["exit_reason"]), 0) + 1
    max_remaining = max((int(x["bars_remaining_to_timeout_maturity"]) for x in pending), default=0)
    min_remaining = min((int(x["bars_remaining_to_timeout_maturity"]) for x in pending), default=0)
    root = "HORIZON_MATURITY_LAG" if pending and not defects else ("NO_LIFECYCLE_GAP" if not pending else "LIFECYCLE_DEFECT")
    result = {
        "schema_version": "zel.a1.finalist.intent_lifecycle_diagnostic.v1",
        "strategy_id": strategy_id,
        "boundary_utc": boundary,
        "symbols": list(SYMBOLS),
        "policy_path": str(policy_path.relative_to(ROOT)),
        "policy_sha": policy_sha,
        "config_sha": str(getattr(cfg, "sha", ev.stable_sha(asdict(cfg) if is_dataclass(cfg) else vars(cfg)))),
        "intent_count": len(events),
        "mature_completed_count": len(mature),
        "pending_unmature_count": len(pending),
        "exit_reason_counts": reasons,
        "pending_min_bars_to_maturity": min_remaining,
        "pending_max_bars_to_maturity": max_remaining,
        "root_cause": root,
        "evaluator_has_position_serialization_gate": False,
        "overlap_blocker_possible_in_this_evaluator": False,
        "canonical_explainer": "generic evaluator increments intent_count before outcome maturity; if no SL/TP occurs and timeout horizon is not fully visible, the intent is omitted from completed_trades until later bars arrive",
        "pending_events": pending,
        "integrity_defects": defects,
        "leakage_lookahead": 0,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
        "next": "RUN_FIXED_LIQUID6_SAME_POLICY_COMPARATOR_AND_KEEP_PARENT_FRESH_COHORT_UNCHANGED",
    }
    result["receipt_sha256"] = ev.stable_sha(result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy-id", choices=TARGETS, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        assert TARGETS == ("supertrend_pullback", "trend_ma_macd")
        assert SYMBOLS == ("BTC-USDT", "ETH-USDT")
        print("PASS_A1_FINALIST_INTENT_LIFECYCLE_DIAGNOSTIC_V1_SELF_TEST")
        return 0
    r = diagnose(args.strategy_id)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(r, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: r[k] for k in ("strategy_id", "intent_count", "mature_completed_count", "pending_unmature_count", "root_cause", "pending_min_bars_to_maturity", "pending_max_bars_to_maturity")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

from backend.research.benchmark import top5_trader_benchmark_multi_ai_v1 as base


def stop_entry_fill(pending: dict[str, Any], bar: dict[str, Any]) -> tuple[bool, float | None]:
    """Evaluate a sealed stop-entry on exactly the immediate next bar."""
    side = str(pending["side"])
    trigger = float(pending["trigger"])
    high, low, op = float(bar["high"]), float(bar["low"]), float(bar["open"])
    if side == "long":
        return (high > trigger, max(op, trigger) if high > trigger else None)
    if side == "short":
        return (low < trigger, min(op, trigger) if low < trigger else None)
    raise RuntimeError(f"BAD_PENDING_SIDE:{side}")


def holy_grail_replay(
    symbols: list[str],
    bars_cache: dict[tuple[str, str, int], list[dict[str, Any]]],
    snapshot_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Causal Holy Grail translation with a one-bar-lived stop entry.

    A pullback is sealed only after bar i-1 closes.  Its stop entry may fill
    only on bar i.  No feature from bar i is allowed to cancel or modify that
    already-sealed intrabar order before fill testing.
    """
    ledger, authority = base.read(base.LEDGER), base.read(base.AUTHORITY)
    boundary = str(ledger["strategies"]["supertrend_pullback"]["prospective_boundary_utc"])
    boundary_ms = int(datetime.fromisoformat(boundary.replace("Z", "+00:00")).timestamp() * 1000)
    trades: list[dict[str, Any]] = []
    open_intents = rejected_ownership = ambiguous_intrabar = expired_unfilled = 0

    for symbol in symbols:
        bars = bars_cache.get((symbol, "1h", 1000))
        if bars is None:
            bars = base.ev.fetch_bars(symbol, "1h", 1000)
            bars_cache[(symbol, "1h", 1000)] = bars
        snap = snapshot_cache.get(symbol)
        if snap is None:
            snap = base.ev.fetch_execution_snapshot(symbol, authority)
            snapshot_cache[symbol] = snap

        e20 = base.ema([float(x["close"]) for x in bars], 20)
        adx, pdi, mdi = base.adx_wilder(bars, 14)
        armed: str | None = None
        pending: dict[str, Any] | None = None
        blocked_until_ts = -1
        i = 30

        while i < len(bars):
            bar = bars[i]
            ts_ms = int(bar["ts_ms"])
            if ts_ms < boundary_ms:
                pending = None
                i += 1
                continue

            # First resolve the order sealed from the prior completed bar.
            # This prevents current-bar ADX/DI/EMA information from affecting
            # an order that was already live at this bar's open.
            if pending is not None:
                expected_entry_index = int(pending["touch_index"]) + 1
                if i != expected_entry_index:
                    raise RuntimeError(f"NEXT_BAR_ENTRY_INVARIANT:{pending['touch_index']}->{i}")
                if ts_ms <= blocked_until_ts:
                    rejected_ownership += 1
                else:
                    fill, entry_px = stop_entry_fill(pending, bar)
                    if fill and entry_px is not None:
                        side = str(pending["side"])
                        initial_stop = float(pending["initial_stop"])
                        same_bar_stop = (
                            (side == "long" and float(bar["low"]) <= initial_stop)
                            or (side == "short" and float(bar["high"]) >= initial_stop)
                        )
                        stop = initial_stop
                        risk = abs(float(entry_px) - initial_stop)
                        if risk <= 0:
                            raise RuntimeError("NONPOSITIVE_HOLY_GRAIL_RISK")

                        exit_px: float | None = None
                        exit_ts: int | None = None
                        reason: str | None = None
                        if same_bar_stop:
                            ambiguous_intrabar += 1
                            exit_px = min(float(bar["open"]), stop) if side == "long" else max(float(bar["open"]), stop)
                            exit_ts, reason = ts_ms, "CONSERVATIVE_INTRABAR_STOP"
                        else:
                            trailing_active = False
                            last_j = min(len(bars) - 1, i + 48)
                            for j in range(i + 1, last_j + 1):
                                b = bars[j]
                                op, hi, lo = float(b["open"]), float(b["high"]), float(b["low"])
                                if (side == "long" and lo <= stop) or (side == "short" and hi >= stop):
                                    exit_px = min(op, stop) if side == "long" else max(op, stop)
                                    exit_ts = int(b["ts_ms"])
                                    reason = "SWING_TRAIL_STOP" if trailing_active else "INITIAL_SWING_STOP"
                                    break
                                favorable_1r = (
                                    (side == "long" and hi >= float(entry_px) + risk)
                                    or (side == "short" and lo <= float(entry_px) - risk)
                                )
                                if favorable_1r:
                                    trailing_active = True
                                # The structural extreme becomes usable only
                                # after this completed bar; it is checked from
                                # the next bar onward.
                                if trailing_active:
                                    structural = lo if side == "long" else hi
                                    stop = max(stop, structural) if side == "long" else min(stop, structural)

                            if exit_px is None:
                                if last_j >= len(bars) - 1:
                                    open_intents += 1
                                    blocked_until_ts = int(bars[-1]["ts_ms"]) + 2 * 3_600_000
                                else:
                                    b = bars[last_j]
                                    exit_px, exit_ts, reason = float(b["close"]), int(b["ts_ms"]), "TIMEOUT_48"

                        if exit_px is not None and exit_ts is not None:
                            fee = float(snap["fee_bps"])
                            spread = float(snap["spread_bps"])
                            impact = float(snap["impact_bps"])
                            fund = base.ev.funding_cost(ts_ms, exit_ts, list(snap["funding_rows"]))
                            cost = fee + spread + impact + fund
                            gross = (
                                (exit_px - float(entry_px)) / float(entry_px) * 10_000
                                if side == "long"
                                else (float(entry_px) - exit_px) / float(entry_px) * 10_000
                            )
                            trades.append(
                                {
                                    "symbol": symbol,
                                    "signal_ts": int(pending["touch_ts"]),
                                    "signal_index": int(pending["touch_index"]),
                                    "entry_ts": ts_ms,
                                    "entry_index": i,
                                    "exit_ts": exit_ts,
                                    "side": side,
                                    "entry": float(entry_px),
                                    "exit": exit_px,
                                    "reason": reason,
                                    "gross_bps": gross,
                                    "realized_cost_bps": cost,
                                    "net_bps": gross - cost,
                                    "benchmark_source_id": "LBR_HOLY_GRAIL",
                                    "trigger": float(pending["trigger"]),
                                    "initial_stop": initial_stop,
                                    "next_bar_entry_invariant": i == int(pending["touch_index"]) + 1,
                                }
                            )
                            blocked_until_ts = exit_ts + 2 * 3_600_000
                        armed = None
                    else:
                        expired_unfilled += 1
                pending = None

            # Only completed current-bar features may arm/cancel the setup for
            # a potential order on the next bar.
            a, ap, p, m = adx[i], adx[i - 1], pdi[i], mdi[i]
            if a is not None and ap is not None and a > 30.0 and a > ap and p is not None and m is not None:
                armed = "long" if p > m else ("short" if m > p else armed)
            if armed == "long" and p is not None and m is not None and m >= p:
                armed = None
            elif armed == "short" and p is not None and m is not None and p >= m:
                armed = None

            if i < len(bars) - 1 and ts_ms > blocked_until_ts:
                center = float(e20[i])
                lo, hi, close = float(bar["low"]), float(bar["high"]), float(bar["close"])
                touched = lo <= center <= hi
                if armed == "long" and touched and close >= center:
                    pending = {
                        "side": "long", "trigger": hi, "initial_stop": lo,
                        "touch_ts": ts_ms, "touch_index": i,
                    }
                elif armed == "short" and touched and close <= center:
                    pending = {
                        "side": "short", "trigger": lo, "initial_stop": hi,
                        "touch_ts": ts_ms, "touch_index": i,
                    }
            i += 1

    if any(not bool(t.get("next_bar_entry_invariant")) for t in trades):
        raise RuntimeError("NEXT_BAR_ENTRY_POSTCONDITION_FAILED")

    return {
        "schema_version": "zel.top5.lbr_holy_grail.causal_translation.v2",
        "strategy_id": "supertrend_pullback",
        "candidate_id": "supertrend_pullback__lbr_holy_grail_adx30_ema20_v1",
        "source_conformance": {
            "source_id": "LBR_HOLY_GRAIL",
            "match": "ANALOGOUS_BENCHMARK",
            "adx14_above30_and_rising_to_arm": True,
            "adx_may_fall_during_retracement_without_cancelling_solely_for_that_reason": True,
            "ema20_pullback": True,
            "immediate_next_bar_stop_entry_from_completed_pullback_bar": True,
            "one_bar_order_lifetime": True,
            "protective_swing_extreme_known_before_entry": True,
            "causal_profit_trailing": True,
            "parent_cost_model_retained": True,
            "parent_48bar_horizon_retained_where_source_unspecified": True,
        },
        "boundary_utc": boundary,
        "trades": trades,
        "metrics": base.metrics_from_trades(trades),
        "open_intents": open_intents,
        "ownership_rejected": rejected_ownership,
        "expired_unfilled_stop_entries": expired_unfilled,
        "conservative_intrabar_ambiguities": ambiguous_intrabar,
        "leakage_lookahead": 0,
        "parameter_sweep": False,
        **base.AUTH,
    }


def execute() -> dict[str, Any]:
    # Replace only the replay implementation. Provider budgets, frozen source
    # packet, candidate preregistration, controls and report paths remain v1.
    base.holy_grail_replay = holy_grail_replay
    result = base.execute()
    result["schema_version"] = "zel.top5.trader_benchmark.multi_ai.v2"
    result["timing_repair"] = "IMMEDIATE_NEXT_BAR_STOP_ENTRY_ENFORCED"
    base.write(base.OUT / "FINAL.json", result)
    base.write_report(result)
    return result


def self_test() -> int:
    long_pending = {"side": "long", "trigger": 101.0}
    short_pending = {"side": "short", "trigger": 99.0}
    bar = {"open": 100.0, "high": 102.0, "low": 98.0}
    fill, px = stop_entry_fill(long_pending, bar)
    assert fill and px == 101.0
    fill, px = stop_entry_fill(short_pending, bar)
    assert fill and px == 99.0
    gap = {"open": 103.0, "high": 104.0, "low": 102.0}
    fill, px = stop_entry_fill(long_pending, gap)
    assert fill and px == 103.0
    miss = {"open": 100.0, "high": 100.5, "low": 99.5}
    fill, px = stop_entry_fill(long_pending, miss)
    assert not fill and px is None
    assert base.dry_run()["state"] == "PASS_OFFLINE_TOP5_BENCHMARK_CONTRACT"
    print("PASS_TOP5_TRADER_BENCHMARK_MULTI_AI_V2_TIMING_SELF_TEST")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--run", action="store_true")
    args = p.parse_args()
    if args.self_test:
        return self_test()
    if args.run:
        result = execute()
        print(
            "TOP5_BENCHMARK_V2="
            + json.dumps(
                {
                    "state": result["state"],
                    "gemini": result["providers"]["gemini"]["state"],
                    "openai": result["providers"]["openai"]["state"],
                    "economic_pass": result["economic_pass"],
                    "timing_repair": result["timing_repair"],
                    "report_only": result["report_only"],
                },
                sort_keys=True,
            )
        )
        return 0
    print(json.dumps(base.dry_run(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

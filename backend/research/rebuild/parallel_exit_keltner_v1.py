"""Frozen Keltner V2 entry/hold with one research-only causal exit hook.

No input loading, acquisition, costs, outcome selection, or operating writes.
The existing DSL computes the original bounded-history EMA, and the shared
development evaluator supplies every held-path geometry. Tail observations
are separate from the original strictly-before-end closed trade ledger.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math

from backend.research.rebuild import top5_development_repair_v1 as old

BAR = 14_400_000
HOLD = 12
LANE = "keltner_trend_main"
PARENT_ID = "keltner_replacement_trend_pull_long_4h_h12_v2"
RULE_ID = "KELTNER_TREND_INVALIDATION_EXIT_DEV_V1"
ENTRY_RULE = "ema20 > ema50 and lag('close',1) <= lag('ema20',1) and close > ema20"
PARENT_SPEC = {
    "bar_interval": "4h",
    "features": [{"name": "ema20", "formula": "ema(close,20)"},
                 {"name": "ema50", "formula": "ema(close,50)"}],
    "entry_rule": ENTRY_RULE, "side_rule": "long", "exit_rule": "time_stop",
    "max_hold_bars": HOLD, "entry_timing": "next_bar_open",
    "cost_bps_per_trade": 20.0,
}


def _validate_rows(rows, start, end):
    if (type(start) is not int or type(end) is not int or start >= end
            or start % BAR or end % BAR or not rows):
        raise RuntimeError("KELTNER_EXIT_CALENDAR_INVALID")
    # This validates each supplied row; it does not silently truncate a future
    # suffix. Warmup is source history, never a trade carried into start.
    old.common.evaluate_development_events(
        rows, [], split_start_ms=rows[0]["bar_open_ts"], split_end_ms=end,
        interval_ms=BAR, hold_bars=HOLD)
    if rows[0]["bar_open_ts"] > start or rows[-1]["bar_close_ts"] != end:
        raise RuntimeError("KELTNER_EXIT_INPUT_COVERAGE")


def build_bundle(rows, parent_spec, *, eval_start_ms, eval_end_ms):
    """Reuse the exact original EMA seed, warmup and reclaim expression."""
    if parent_spec != PARENT_SPEC:
        raise RuntimeError("KELTNER_EXIT_ORIGINAL_SPEC_DRIFT")
    _validate_rows(rows, eval_start_ms, eval_end_ms)
    arrays, engine = old.dsl._features(
        [dict(r, ts=r["bar_open_ts"]) for r in rows], parent_spec)
    signals = []
    outside = Counter()
    for i in range(239, len(rows)):
        if not bool(engine.eval(parent_spec["entry_rule"], i)):
            continue
        stamp = rows[i]["bar_close_ts"]
        if stamp < eval_start_ms:
            outside["WARMUP_SIGNAL_NOT_REPLAYED"] += 1
        elif stamp >= eval_end_ms:
            outside["END_CLOSE_HAS_NO_PERMITTED_NEXT_OPEN"] += 1
        else:
            signals.append({"signal_index": i, "signal_ts": stamp})
    return {"signals": signals, "ema20": arrays["ema20"],
            "ema50": arrays["ema50"], "audit": {
                "parent_id": PARENT_ID, "first_eligible_source_index": 239,
                "ema_calculation": "UNCHANGED_DSL_EMA_LAST_4N_VALUES_FIRST_VALUE_SEED",
                "fresh_flat_start": True, "outside_signal_counts": dict(outside)}}


def _geometry(rows, signal_index, last_held_index, end):
    # An envelope permits geometry of the last known close for an open mark.
    # It supplies no row or executable price after the actual evaluation end.
    answer = old.common.evaluate_development_events(
        rows, [signal_index], split_start_ms=rows[0]["bar_open_ts"],
        split_end_ms=end + BAR, interval_ms=BAR,
        hold_bars=last_held_index - signal_index)
    if len(answer["trades"]) != 1 or answer["exclusions"]:
        raise RuntimeError("KELTNER_EXIT_SHARED_GEOMETRY_UNAVAILABLE")
    return dict(answer["trades"][0])


def _path(rows, signal, ema20, ema50, end, enabled):
    i = signal["signal_index"]
    ei, native_exit = i + 1, i + HOLD
    trace = [{"kind": "ENTRY_NEXT_OPEN", "signal_index": i, "index": ei,
              "ts": rows[ei]["bar_open_ts"], "price": rows[ei]["open"]}]
    pending = None
    for j in range(ei, min(native_exit, len(rows) - 1) + 1):
        row = rows[j]
        # An unchanged timeout occurs at this close before any new close-based
        # order. Its strict end convention also wins at close == end.
        if j == native_exit:
            if row["bar_close_ts"] < end:
                raw = _geometry(rows, i, j, end)
                trace.append({"kind": "ORIGINAL_TIME_STOP_CLOSE", "index": j,
                              "signal_index": i, "ts": raw["exit_ts"],
                              "price": raw["exit_price"]})
                return raw, None, trace
            break
        if not enabled or ema20[j] > ema50[j]:
            continue
        pending = {"signal_ts": row["bar_close_ts"], "signal_index": j,
                   "ema20": ema20[j], "ema50": ema50[j]}
        trace.append({"kind": "TREND_INVALIDATION_CLOSE", "signal_index": i,
                      "index": j, "ts": pending["signal_ts"],
                      "ema20": ema20[j], "ema50": ema50[j]})
        xi = j + 1
        if xi >= len(rows) or rows[xi]["bar_open_ts"] >= end:
            break
        raw = _geometry(rows, i, j, end)
        price = float(rows[xi]["open"])
        gross = (price / raw["entry_price"] - 1.0) * 10_000.0
        raw.update(exit_index=xi, exit_ts=rows[xi]["bar_open_ts"],
                   exit_price=price, gross_bps=gross,
                   hold_ms=rows[xi]["bar_open_ts"] - raw["entry_ts"],
                   mfe_bps=max(raw["mfe_bps"], gross, 0.0),
                   mae_bps=min(raw["mae_bps"], gross, 0.0),
                   exit_reason="EMA20_NOT_ABOVE_EMA50_NEXT_OPEN",
                   exit_timestamp_semantics="OBSERVED_4H_OPEN",
                   excursion_semantics="HELD_COMPLETE_BARS_PLUS_EXIT_OPEN_ONLY",
                   exit_trigger=deepcopy(pending))
        trace.append({"kind": raw["exit_reason"], "signal_index": i,
                      "index": xi, "ts": raw["exit_ts"], "price": price})
        return raw, None, trace
    raw = _geometry(rows, i, len(rows) - 1, end)
    for prior, replacement in (("exit_index", "mark_index"), ("exit_ts", "mark_ts"),
                               ("exit_price", "mark_price"), ("gross_bps", "gross_mark_bps")):
        raw[replacement] = raw.pop(prior)
    exact_boundary = native_exit == len(rows) - 1
    raw.update(status="CENSORED", terminal_liquidation=False,
               native_hold_bars=HOLD,
               native_planned_exit_ts=rows[ei]["bar_open_ts"] + HOLD * BAR,
               original_protective_sl=None,
               native_geometry_scope="FROZEN_V2_FIXED_HOLD_NO_NATIVE_SL_SPECIFIED",
               censor_reason=("ORIGINAL_STRICT_END_TIMEOUT_AT_BOUNDARY"
                              if exact_boundary else "NATIVE_HOLD_UNFINISHED"),
               pending_exit_signal_ts=pending["signal_ts"] if pending else None,
               pending_exit_trigger=deepcopy(pending))
    trace.append({"kind": "TERMINAL_MARK", "signal_index": i,
                  "index": raw["mark_index"], "ts": raw["mark_ts"],
                  "price": raw["mark_price"], "censor_reason": raw["censor_reason"],
                  "pending_exit_signal_ts": raw["pending_exit_signal_ts"]})
    return None, raw, trace


def replay(rows, bundle, *, eval_start_ms, eval_end_ms, enable_change=True,
           fixed_signal_indices=None):
    """Original entries with fixed-origin or original exit-bar ownership.

    Signals at/before an accepted trade's exit index remain blocked, including
    an early exit open's bar. Fixed origins bypass this inter-position rule
    only; each individual exit still follows the same observable chronology.
    """
    if type(enable_change) is not bool:
        raise RuntimeError("KELTNER_EXIT_ENABLE_BOOL_REQUIRED")
    _validate_rows(rows, eval_start_ms, eval_end_ms)
    signals = bundle["signals"]
    ema20, ema50 = bundle["ema20"], bundle["ema50"]
    if len(ema20) != len(rows) or len(ema50) != len(rows):
        raise RuntimeError("KELTNER_EXIT_FEATURE_LENGTH")
    if any(isinstance(v, bool) or not isinstance(v, (float, int))
           or not math.isfinite(v) or v <= 0 for v in [*ema20, *ema50]):
        raise RuntimeError("KELTNER_EXIT_FEATURE_MISSING_OR_NONFINITE")
    previous = -1
    for s in signals:
        i = s.get("signal_index")
        if (type(i) is not int or not previous < i < len(rows)
                or s.get("signal_ts") != rows[i]["bar_close_ts"]
                or not eval_start_ms <= s["signal_ts"] < eval_end_ms):
            raise RuntimeError("KELTNER_EXIT_SIGNAL_INVALID_OR_FUTURE")
        previous = i
    fixed = fixed_signal_indices is not None
    if fixed:
        wanted = list(fixed_signal_indices)
        if (any(type(i) is not int for i in wanted) or len(wanted) != len(set(wanted))
                or not set(wanted) <= {s["signal_index"] for s in signals}):
            raise RuntimeError("KELTNER_EXIT_FIXED_ORIGINS_INVALID")
        signals = [s for s in signals if s["signal_index"] in set(wanted)]
    trades, opened, events, trace = [], [], [], []
    last_exit, tail_open = -1, False
    for signal in signals:
        i = signal["signal_index"]
        event = dict(signal, admission=True, status="PENDING", exclusion_reason=None)
        if not fixed and (tail_open or i <= last_exit):
            event.update(status="EXCLUDED", exclusion_reason="SIGNAL_DURING_OPEN")
        elif i + 1 >= len(rows) or rows[i + 1]["bar_open_ts"] >= eval_end_ms:
            event.update(status="EXCLUDED", exclusion_reason="NO_NEXT_OPEN_IN_CALENDAR")
        else:
            trade, observation, path_trace = _path(
                rows, signal, ema20, ema50, eval_end_ms, enable_change)
            trace.extend(path_trace)
            if trade is not None:
                trades.append(trade)
                last_exit = trade["exit_index"]
                event.update(status="COMPLETED")
            else:
                opened.append(observation)
                tail_open = True
                event.update(status="CENSORED", censor_reason=observation["censor_reason"])
        events.append(event)
    if len(trades) + len(opened) + sum(e["status"] == "EXCLUDED" for e in events) != len(events):
        raise RuntimeError("KELTNER_EXIT_OPPORTUNITY_ACCOUNTING")
    return {"trades": trades, "open_positions": opened, "events": events, "trace": trace,
            "audit": {"rule": RULE_ID, "change_enabled": enable_change,
                      "comparison_mode": "FIXED_PARENT_ORIGINS" if fixed else "FULL_CHRONOLOGICAL",
                      "raw_signals": len(signals), "completed": len(trades), "open": len(opened),
                      "excluded": sum(e["status"] == "EXCLUDED" for e in events),
                      "same_symbol_max_positions": None if fixed else 1,
                      "fixed_origins_independent_diagnostic_positions": fixed,
                      "original_signal_exit_bar_ownership_preserved": True,
                      "original_max_hold_bars": HOLD, "original_protective_sl": None,
                      "native_geometry_scope": "FROZEN_V2_FIXED_HOLD_NO_NATIVE_SL_SPECIFIED",
                      "original_closed_exit_exclusive_end_preserved": True,
                      "formerly_censored_tail_separately_marked": True,
                      "strict_boundary_timeout_marks": sum(o["censor_reason"] == "ORIGINAL_STRICT_END_TIMEOUT_AT_BOUNDARY" for o in opened),
                      "pending_exit_at_end": sum(o["pending_exit_signal_ts"] is not None for o in opened),
                      "forced_terminal_liquidations": 0, "future_economic_rows": 0,
                      "short_entries": 0, "common_end_mark_ts": eval_end_ms}}

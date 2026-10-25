#!/usr/bin/env python3
"""Bounded, READ-ONLY causal portfolio fusion / rescue experiment.

Uses two immutable *already consumed* source receipts and local BingX 1h
OHLC. Produces development-only economic arithmetic, never issues orders.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import importlib.util
import os
import json
import math
from pathlib import Path
from typing import Any, Mapping

H = 3_600_000
SCALE = 1.0 / 3.0
UTC = dt.timezone.utc
SOURCE = Path(
    os.environ.get(
        "ZEL_TRENDRIDER_FROZEN_INPUT_ROOT",
        str(Path(__file__).resolve().parent.parent / "trendrider_two_stage_v1"),
    )
)
STAGE_SOURCE = SOURCE / "stages.py"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def old_module() -> Any:
    if not STAGE_SOURCE.is_file():
        raise RuntimeError("PINNED_PARENT_STAGE_SOURCE_MISSING")
    spec = importlib.util.spec_from_file_location("zel_oldstages", STAGE_SOURCE)
    if spec is None or spec.loader is None:
        raise RuntimeError("CANNOT_IMPORT_PINNED_PARENT_STAGE")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def epoch(s: str) -> int:
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def month(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m")


def build_candidates(
    input_by_lane: Mapping[str, list[dict[str, Any]]],
    old: Any,
    market: Mapping[str, list[dict[str, Any]]],
    maps: Mapping[str, Mapping[int, int]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    old.terminal_source_parity(input_by_lane["Liquid6"], market, maps)
    old.terminal_source_parity(input_by_lane["Delayed"], market, maps)
    counters: collections.Counter[str] = collections.Counter()
    found: dict[tuple[str, str, int], dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    for origin in ("Delayed", "Liquid6"):  # liquid overwrites matching signal
        for r in input_by_lane[origin]:
            key = (str(r["symbol"]), str(r["side"]), int(r["signal_ts"]))
            if r["side"] != "long":
                raise RuntimeError("STRATEGY_CHANGED_TO_SHORT_SOURCE")
            if float(r["entry"]) <= float(r["intent_geometry"]["sl"]):
                counters["DELAYED_INVALID_NATIVE_STOP_GEOMETRY"] += 1
                rejected.append(
                    {
                        "signal_key": key,
                        "source": origin,
                        "reason": "SEALED_LONG_STOP_GE_ENTRY",
                    }
                )
                continue
            if origin == "Liquid6":
                if not math.isclose(
                    float(r.get("portfolio_risk_scale", SCALE)), SCALE, abs_tol=1e-10
                ):
                    raise RuntimeError("LIQUID6_RISK_FACTOR_CHANGED")
            else:
                if not math.isclose(
                    float(r.get("portfolio_risk_scale", 1)), 1.0, abs_tol=1e-8
                ):
                    raise RuntimeError("DELAYED_NATIVE_RISK_FACTOR_CHANGED")
            candidate = dict(r)
            origin_scale = float(r.get("portfolio_risk_scale", 1.0))
            assert origin_scale > 0.0
            factor = SCALE / origin_scale
            candidate["source_lane"] = origin
            candidate["canonical_key"] = "|".join(map(str, key))
            candidate["instrument_source_cost_bps"] = (
                float(r["realized_cost_bps"]) / origin_scale
            )
            candidate["normalized_scale"] = SCALE
            candidate["gross_bps"] = float(r["gross_bps"]) * factor
            candidate["realized_cost_bps"] = float(r["realized_cost_bps"]) * factor
            candidate["net_bps"] = (
                candidate["gross_bps"] - candidate["realized_cost_bps"]
            )
            candidate["net2_bps"] = (
                candidate["gross_bps"] - 2.0 * candidate["realized_cost_bps"]
            )
            if key in found:
                counters["EXACT_SIGNAL_DEDUPED"] += 1
            found[key] = candidate
    chosen = sorted(
        found.values(),
        key=lambda x: (int(x["entry_ts"]), str(x["symbol"]), int(x["signal_ts"])),
    )
    counters["LIQUID_SELECTED"] = sum(x["source_lane"] == "Liquid6" for x in chosen)
    counters["DELAYED_SELECTED"] = sum(x["source_lane"] == "Delayed" for x in chosen)
    if (
        counters["EXACT_SIGNAL_DEDUPED"] != 97
        or counters["DELAYED_INVALID_NATIVE_STOP_GEOMETRY"] != 4
    ):
        raise RuntimeError("ORIGINAL_FUSION_INPUT_COUNTS_CHANGED")
    if counters["LIQUID_SELECTED"] != 119:
        raise RuntimeError("UNEXPECTED_LIQUID_OWNER_COUNT")
    if len(chosen) != 119 + 249 - 4 - 97:
        raise RuntimeError("CANDIDATE_UNION_COUNT_MISMATCH")
    return chosen, {"counts": dict(counters), "invalid_examples": rejected}


def make_leg(
    *,
    side: str,
    original: Mapping[str, Any],
    entry_ts: int,
    terminal_open_ms: int,
    terminal_effective_ms: int,
    entry_px: float,
    exit_px: float,
    cost_bps: float,
    reason: str,
    kind: str,
) -> dict[str, Any]:
    sign = 1 if side == "long" else -1
    gross = SCALE * sign * (exit_px / entry_px - 1) * 10_000.0
    net2 = gross - 2 * cost_bps
    return {
        "opportunity_key": original["canonical_key"],
        "kind": kind,
        "source_lane": original["source_lane"],
        "symbol": original["symbol"],
        "side": side,
        "entry_ts": int(entry_ts),
        "exit_bar_ts": int(terminal_open_ms),
        "effective_closed_at": int(terminal_effective_ms),
        "entry": entry_px,
        "exit": exit_px,
        "reason": reason,
        "gross_bps": gross,
        "modeled_cost_bps": cost_bps,
        "Net2_bps": net2,
    }


def bailout_close_candidate(
    trade: dict[str, Any],
    bars: list[dict[str, Any]],
    ema: list[float],
    maps: Mapping[int, int],
) -> dict[str, Any] | None:
    """Never evaluate a losing outcome. Native stop has intrabar first priority.

    Uses last TWO completed candles and moves execution to NEXT bar open.
    Any original stop earlier than confirmation vetoes the bailout.
    """
    entry_idx = maps[int(trade["entry_ts"])]
    exit_idx = maps[int(trade["exit_ts"])]
    if entry_idx < 20 or exit_idx < entry_idx:
        raise RuntimeError("BAD_NATIVE_ENTRY_HOUR")
    stop = float(trade["intent_geometry"]["sl"])
    entry = float(trade["entry"])
    risk = entry - stop
    if risk <= 0.0:
        raise RuntimeError("NONPOSITIVE_NATIVE_LONG_R")
    for j in range(entry_idx, exit_idx + 1):
        bar = bars[j]
        if float(bar["low"]) <= stop:
            # Historical native strategy would stop FIRST during this bar.
            if trade["reason"] != "SL" or j != exit_idx:
                raise RuntimeError("PRE_NATURAL_STOP_PRICE_PARITY_FAIL")
            return None
        if j == exit_idx:
            return None
        if j - 1 < entry_idx:
            continue
        a, b = bars[j - 1], bar
        if not (
            float(a["close"]) < ema[j - 1]
            and float(b["close"]) < ema[j]
            and ema[j] < ema[j - 1]
            and float(b["close"]) < float(a["close"])
            and float(b["close"]) <= entry - 0.50 * risk
        ):
            continue
        if j + 1 >= len(bars) or j + 1 > exit_idx:
            continue
        return {
            "signal_bar_index": j,
            "exit_index": j + 1,
            "exit_px": float(bars[j + 1]["open"]),
            "exit_bar_ts": int(bars[j + 1]["ts_ms"]),
            "effective_closed_at": int(bars[j + 1]["ts_ms"]),
            "reason": "CAUSAL_EARLY_BEARISH_ABORT_NEXT_OPEN",
        }
    return None


def short_confirmation(
    *, last_completed_idx: int, bars: list[dict[str, Any]], ema: list[float]
) -> bool:
    j = last_completed_idx
    if j < 20:
        return False
    a, b = bars[j - 1], bars[j]
    return (
        float(a["close"]) < ema[j - 1]
        and float(b["close"]) < ema[j]
        and ema[j] < ema[j - 1]
        and float(b["close"]) < float(a["close"])
    )


def atr_14(bars: list[dict[str, Any]], last_completed_idx: int) -> float:
    j = last_completed_idx
    if j < 14:
        raise RuntimeError("INSUFFICIENT_PRIOR_ATR")
    tr = []
    for idx in range(j - 13, j + 1):
        x = bars[idx]
        prev = float(bars[idx - 1]["close"])
        tr.append(
            max(
                float(x["high"]) - float(x["low"]),
                abs(float(x["high"]) - prev),
                abs(float(x["low"]) - prev),
            )
        )
    return sum(tr) / len(tr)


def new_short_leg(
    *,
    trade: dict[str, Any],
    market: list[dict[str, Any]],
    trigger_j: int,
    latest_closed_open_ms: int,
) -> dict[str, Any] | None:
    """An independently risk-capped SHORT after long loss. No DCA or doubling.

    24 fully CLOSED hourly bars must be observed, else decline this leg.
    """
    s = trigger_j + 1
    if s < 21 or s + 24 >= len(market):
        return None
    if int(market[s + 24]["ts_ms"]) > latest_closed_open_ms:
        return None
    entry = float(market[s]["open"])
    atr = atr_14(market, trigger_j)
    native_stop = (
        max(
            float(market[trigger_j]["high"]),
            float(market[trigger_j - 1]["high"]),
        )
        + 0.25 * atr
    )
    stop = max(native_stop, entry + 1.5 * atr)
    risk = stop - entry
    if not risk > 0:
        raise RuntimeError("SHORT_NATIVE_R_NONPOSITIVE")
    lowwater = entry
    exit_price = None
    terminal_i = None
    reason = None
    for i in range(s, s + 25):
        candle = market[i]
        floor = stop
        if entry - lowwater >= risk:
            floor = min(stop, entry - 0.25 * risk, lowwater + 1.25 * risk)
        high, o = float(candle["high"]), float(candle["open"])
        if o >= floor:
            exit_price = o  # adverse gap cannot be filled at old stop
            terminal_i = i
            reason = "SHORT_STOP_GAP_OPEN"
            break
        if high >= floor:
            exit_price = floor
            terminal_i = i
            reason = "SHORT_STOP_INTRABAR"
            break
        lowwater = min(lowwater, float(candle["low"]))
    if terminal_i is None:
        terminal_i = s + 24
        exit_price = float(market[terminal_i]["close"])
        reason = "SHORT_TIME24_CLOSED"
    assert exit_price is not None and reason is not None
    holding_h = terminal_i - s + 1
    # Publisher originally supplied native cost for long source decision;
    # short actual signed funding and actual fill are UNKNOWN. This is an
    # explicit stress-model cost assumption, never a verified quote.
    instrument_roundtrip_model = max(float(trade["instrument_source_cost_bps"]), 14.0)
    cost = (instrument_roundtrip_model + 5.0 * math.ceil(holding_h / 8)) * SCALE
    leg = make_leg(
        side="short",
        original=trade,
        entry_ts=int(market[s]["ts_ms"]),
        terminal_open_ms=int(market[terminal_i]["ts_ms"]),
        terminal_effective_ms=int(market[terminal_i]["ts_ms"]) + H,
        entry_px=entry,
        exit_px=exit_price,
        cost_bps=cost,
        reason=reason,
        kind="REVERSAL_SHORT",
    )
    leg["short_initial_r_bps"] = SCALE * risk / entry * 10_000
    leg["short_R_net2"] = leg["Net2_bps"] / leg["short_initial_r_bps"]
    leg["carry_is_model_only"] = True
    leg["short_held_bar_count"] = holding_h
    return leg


def original_or_modified_long(
    trade: dict[str, Any],
    bars: list[dict[str, Any]],
    ema: list[float],
    maps: Mapping[int, int],
    old: Any,
    stage: int,
    latest_closed_open_ms: int,
) -> tuple[dict[str, Any], int | None, dict[str, Any]]:
    native_exit_i = maps[int(trade["exit_ts"])]
    exit_i = native_exit_i
    exit_px = float(trade["exit"])
    reason = str(trade["reason"])
    extra_h = 0
    effective_at = int(bars[exit_i]["ts_ms"]) + H
    trigger_j: int | None = native_exit_i if reason == "SL" else None
    debug = {"native_reason": reason, "early_abort": False, "winner_extended": False}
    early = bailout_close_candidate(trade, bars, ema, maps) if stage >= 2 else None
    if early:
        exit_i = early["exit_index"]
        exit_px = early["exit_px"]
        reason = early["reason"]
        effective_at = early["effective_closed_at"]
        trigger_j = early["signal_bar_index"]
        debug["early_abort"] = True
    elif stage >= 1 and reason == "TIMEOUT":
        outcome = old.trailing_extension(
            trade, bars, native_exit_i, ema, latest_closed_open_ms
        )
        if outcome.get("attempted"):
            exit_i = outcome["exit_index"]
            exit_px = float(outcome["exit"])
            reason = outcome["reason"]
            extra_h = outcome["extra_bars"]
            effective_at = int(bars[exit_i]["ts_ms"]) + H
            debug["winner_extended"] = True
    base_cost = float(trade["realized_cost_bps"])
    add_model = (5.0 * math.ceil(extra_h / 8)) * SCALE if extra_h else 0.0
    leg = make_leg(
        side="long",
        original=trade,
        entry_ts=int(trade["entry_ts"]),
        terminal_open_ms=int(bars[exit_i]["ts_ms"]),
        terminal_effective_ms=effective_at,
        entry_px=float(trade["entry"]),
        exit_px=exit_px,
        cost_bps=base_cost + add_model,
        reason=reason,
        kind="PRIMARY_LONG",
    )
    leg["initial_price_R_bps"] = (
        SCALE
        * (float(trade["entry"]) - float(trade["intent_geometry"]["sl"]))
        / float(trade["entry"])
        * 10000
    )
    leg["net2_R"] = leg["Net2_bps"] / leg["initial_price_R_bps"]
    leg["extra_hold_hours"] = extra_h
    return leg, trigger_j, debug


def entry_loss_streak_circuit(
    *,
    at: int,
    completed: list[dict[str, Any]],
) -> bool:
    # Uses previous FULLY COMPLETED opportunities, not the later outcome of
    # the currently candidate trade. A signal starts its six-hour pause when
    # the third loss became observable after its actual close.
    done = sorted(
        [x for x in completed if x["end_ms"] + H < at],
        key=lambda x: (x["end_ms"], x["key"]),
    )
    if len(done) < 3:
        return False
    last = done[-3:]
    return (
        all(x["Net2_bps"] < 0 for x in last)
        and at - (last[0]["end_ms"] + H) <= 36 * H
        and at - (last[-1]["end_ms"] + H) < 6 * H
    )


def run_stage(
    candidates: list[dict[str, Any]],
    market: Mapping[str, list[dict[str, Any]]],
    maps: Mapping[str, Mapping[int, int]],
    ema: Mapping[str, list[float]],
    old: Any,
    stage: int,
    latest_closed_open_ms: int,
) -> dict[str, Any]:
    admitted: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    blocked_by_symbol_until: dict[str, int] = collections.defaultdict(lambda: -1)
    active: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    stats: collections.Counter[str] = collections.Counter()
    for row in candidates:
        t = int(row["entry_ts"])
        symbol = str(row["symbol"])
        active = [a for a in active if a["end_ms"] > t]
        if t <= blocked_by_symbol_until[symbol]:
            rejected.append(
                {
                    "key": row["canonical_key"],
                    "reason": "SAME_SYMBOL_OWNERSHIP_COOLDOWN",
                }
            )
            stats["symbol_ownership_rejected"] += 1
            continue
        if len(active) >= 6:
            rejected.append(
                {"key": row["canonical_key"], "reason": "MAX6_GLOBAL_RISK_SLOTS"}
            )
            stats["global_risk_rejected"] += 1
            continue
        if stage >= 4 and entry_loss_streak_circuit(at=t, completed=completed):
            rejected.append(
                {
                    "key": row["canonical_key"],
                    "reason": "THREE_CLOSED_LOSSES_COOLDOWN6H",
                }
            )
            stats["loss_streak_circuit_rejected"] += 1
            continue
        bars = market[symbol]
        longleg, trigger_j, diag = original_or_modified_long(
            row, bars, ema[symbol], maps[symbol], old, stage, latest_closed_open_ms
        )
        if diag["winner_extended"]:
            stats["winner_extended"] += 1
        if diag["early_abort"]:
            stats["early_bailout"] += 1
        leg_list = [longleg]
        end_ms = longleg["effective_closed_at"]
        if stage >= 3 and longleg["Net2_bps"] < 0 and trigger_j is not None:
            # Stop if market has not yet CLOSED the reversal signal bar.
            if trigger_j >= len(bars):
                raise RuntimeError("REVERSAL_SIGNAL_INDEX_INVALID")
            if short_confirmation(
                last_completed_idx=trigger_j, bars=bars, ema=ema[symbol]
            ):
                short = new_short_leg(
                    trade=row,
                    market=bars,
                    trigger_j=trigger_j,
                    latest_closed_open_ms=latest_closed_open_ms,
                )
                if short is not None:
                    if short["entry_ts"] < longleg["effective_closed_at"]:
                        raise RuntimeError("REVERSE_ENTERED_BEFORE_LONG_CLOSED")
                    leg_list.append(short)
                    end_ms = short["effective_closed_at"]
                    stats["short_reversals"] += 1
                    if short["Net2_bps"] > 0:
                        stats["short_positive"] += 1
        opportunity = {
            "key": row["canonical_key"],
            "source_lane": row["source_lane"],
            "symbol": symbol,
            "signal_ts": row["signal_ts"],
            "entry_ts": t,
            "original_native_net2_bps": float(row["net2_bps"]),
            "initial_long_r_bps": longleg["initial_price_R_bps"],
            "legs": leg_list,
            "end_ms": int(end_ms),
            "Net2_bps": sum(x["Net2_bps"] for x in leg_list),
            "original_native_reason": row["reason"],
            "debug": diag,
        }
        admitted.append(opportunity)
        completed.append(opportunity)
        # One parent signal has only one capital sleeve: short replacement
        # cannot coexist with another same symbol LONG during recovery.
        blocked_by_symbol_until[symbol] = int(end_ms) + 2 * H
        active.append({"key": row["canonical_key"], "end_ms": int(end_ms)})
    if len({x["key"] for x in admitted}) != len(admitted):
        raise RuntimeError("DUPLICATE_FUSION_OPPORTUNITY")
    if any(len(x["legs"]) > 2 for x in admitted):
        raise RuntimeError("UNBOUNDED_RECOVERY_LEGS")
    stats["accepted"] = len(admitted)
    stats["rejected"] = len(rejected)
    stats["available_source_opportunities"] = len(candidates)
    if stats["accepted"] + stats["rejected"] != len(candidates):
        raise RuntimeError("ENTRY_COUNT_MISMATCH")
    return {
        "stage": stage,
        "admitted": admitted,
        "rejected": rejected,
        "stats": dict(stats),
    }


def metrics_stage(result: Mapping[str, Any]) -> dict[str, Any]:
    admitted = result["admitted"]
    legs = [leg for opportunity in admitted for leg in opportunity["legs"]]
    normalized = [float(x["Net2_bps"]) for x in admitted]
    profit = sum(x for x in normalized if x > 0)
    loss = -sum(x for x in normalized if x < 0)
    grouped_events: dict[int, float] = collections.defaultdict(float)
    for leg in legs:
        grouped_events[int(leg["effective_closed_at"])] += float(leg["Net2_bps"])
    equity = high = dd = 0.0
    for stamp in sorted(grouped_events):
        equity += grouped_events[stamp]
        high = max(high, equity)
        dd = max(dd, high - equity)
    ordered = sorted(admitted, key=lambda x: (x["end_ms"], x["key"]))
    max_streak = streak = 0
    for x in ordered:
        streak = streak + 1 if x["Net2_bps"] < 0 else 0
        max_streak = max(streak, max_streak)
    leg_ordered = sorted(
        legs, key=lambda x: (x["effective_closed_at"], x["opportunity_key"])
    )
    max_leg_streak = leg_streak = 0
    for x in leg_ordered:
        leg_streak = leg_streak + 1 if x["Net2_bps"] < 0 else 0
        max_leg_streak = max(max_leg_streak, leg_streak)
    winners = sorted((x for x in normalized if x > 0), reverse=True)
    counter = collections.Counter(x["source_lane"] for x in admitted)
    by_month = collections.defaultdict(list)
    for x in admitted:
        by_month[month(int(x["signal_ts"]))].append(float(x["Net2_bps"]))
    return {
        "accepted_opportunities": len(admitted),
        "long_legs": sum(1 for x in legs if x["side"] == "long"),
        "reverse_short_legs": sum(1 for x in legs if x["side"] == "short"),
        "total_legs": len(legs),
        "Net2_sum_trade_bps": sum(normalized),
        "PF2_opportunity": profit / loss if loss else None,
        "WR2_opportunity": len(winners) / len(normalized) if normalized else None,
        "max_loss_streak_opportunity": max_streak,
        "max_loss_streak_leg": max_leg_streak,
        "DD2_realized_exit_leg_bps": dd,
        "max_win_R_from_long_risk": max(
            (x["Net2_bps"] / x["initial_long_r_bps"] for x in admitted), default=None
        ),
        "worst_loss_R_from_long_risk": min(
            (x["Net2_bps"] / x["initial_long_r_bps"] for x in admitted), default=None
        ),
        "largest_2_opportunity_winners_bps": sum(winners[:2]),
        "Net2_excluding_top2_bps": sum(normalized) - sum(winners[:2]),
        "largest_loss_opportunity_bps": min(normalized) if normalized else None,
        "by_month_Net2": {k: sum(v) for k, v in sorted(by_month.items())},
        "accepted_by_native_lane": dict(counter),
        "sum_of_original_native_frozen_trade_bps_for_same_accepted": sum(
            float(x["original_native_net2_bps"]) for x in admitted
        ),
        "order_calls": 0,
        "formal_admission": False,
    }


def summary(path: Path) -> dict[str, Any]:
    freeze_bytes = (path / "FREEZE.json").read_bytes()
    freeze = json.loads(freeze_bytes)
    if freeze["schema"] != "zel.trendrider.unified_one_owner_causal_rescue.v1":
        raise RuntimeError("NOT_PREDECLARED_SINGLE_OWNER_EXPERIMENT")
    old_f = SOURCE / "FREEZE.json"
    old_m = SOURCE / "MARKET_1H_SNAPSHOT.json.gz"
    assert (
        sha(old_f.read_bytes())
        == freeze["parent_sources"]["fusion_prior_freeze_sha256"]
    )
    assert sha(old_m.read_bytes()) == freeze["parent_sources"]["market_1h_gzip_sha256"]
    assert (
        sha((SOURCE / "RESULT.json").read_bytes())
        == freeze["parent_sources"]["fusion_prior_result_sha256"]
    )
    old = old_module()
    src, bars = old.source(SOURCE)
    maps, ema = old.index_bars(bars)
    latest_close_open = max(int(row["ts_ms"]) for row in bars["BTC-USDT"])
    if any(int(row[-1]["ts_ms"]) != latest_close_open for row in bars.values()):
        raise RuntimeError("FROZEN_SOURCE_ASOF_MISMATCH")
    if latest_close_open > epoch(src["utc_retrieved_at"]):
        raise RuntimeError("MARKET_HISTORY_HAS_UNOBSERVED_FUTURE_BAR")
    input_rows = old.original_inputs(SOURCE, json.loads(old_f.read_text()))
    candidates, input_stats = build_candidates(input_rows, old, bars, maps)
    result: dict[str, Any] = {
        "schema": "zel.trendrider.unified_one_owner_causal_rescue.result.v1",
        "freeze_sha256": sha(freeze_bytes),
        "source_snapshot_gzip_sha256": sha(old_m.read_bytes()),
        "native_trade_receipt_inputs": {
            "liquid_sha256": freeze["parent_sources"]["original_liquid6_git"]["sha256"],
            "delayed_sha256": freeze["parent_sources"]["original_delayed_artifact"][
                "sha256"
            ],
        },
        "source_inputs": input_stats,
        "source_timing": {
            "market_1h_seen_to": latest_close_open,
            "historical_real_received_at": "UNKNOWN",
            "source_api_calls_this_eval": 0,
        },
        "stage_economics": {},
        "opportunity_comparison": {},
        "reversal_trade_audit": {},
        "access": {
            "exchange_orders": 0,
            "global_heavy": 0,
            "new_work": 0,
            "source_writes": 0,
        },
        "authority": {
            "G4": "NO_FORMAL_CREDIT",
            "G5": "NO_FORMAL_CREDIT",
            "Paper": "BLOCKED",
            "Live": "BLOCKED",
            "promotion": False,
            "selection": False,
        },
        "limitation": "USED_DEV_ONLY; source long-only model candidate receipts, historical received-at/funding/short fill unverified; rescue SHORT is a counterfactual stress-only route",
    }
    stage_sets = {}
    for stage in range(5):
        s = run_stage(candidates, bars, maps, ema, old, stage, latest_close_open)
        stage_sets[stage] = s
        score = metrics_stage(s)
        result["stage_economics"]["S" + str(stage)] = {
            **score,
            "admissions": s["stats"],
        }
        print(
            "STAGE_SCORED",
            stage,
            json.dumps(
                {
                    "T": score["accepted_opportunities"],
                    "net2": score["Net2_sum_trade_bps"],
                    "PF2": score["PF2_opportunity"],
                    "DD2": score["DD2_realized_exit_leg_bps"],
                    "max_streak": score["max_loss_streak_opportunity"],
                    "short_leg_T": score["reverse_short_legs"],
                    "by_month": score["by_month_Net2"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
    baseline = {x["key"]: x for x in stage_sets[0]["admitted"]}
    for stage in range(1, 5):
        current = {x["key"]: x for x in stage_sets[stage]["admitted"]}
        common = set(baseline) & set(current)
        winlost = sorted(set(baseline) - set(current))
        # Stable sorted summation avoids nondeterminism from Python hash seeds;
        # source economics and selected opportunities remain IDENTICAL.
        netbasecommon = sum(baseline[k]["Net2_bps"] for k in sorted(common))
        netcurrentcommon = sum(current[k]["Net2_bps"] for k in sorted(common))
        result["opportunity_comparison"]["S" + str(stage)] = {
            "common_T": len(common),
            "original_admissions_lost": len(winlost),
            "original_lost_winner_T": sum(baseline[k]["Net2_bps"] > 0 for k in winlost),
            "original_lost_winner_net2": sum(
                max(baseline[k]["Net2_bps"], 0) for k in winlost
            ),
            "new_accepted_original_opportunities_T": len(set(current) - set(baseline)),
            "common_net2_delta_bps": netcurrentcommon - netbasecommon,
            "total_net2_delta_bps": result["stage_economics"]["S" + str(stage)][
                "Net2_sum_trade_bps"
            ]
            - result["stage_economics"]["S0"]["Net2_sum_trade_bps"],
        }
    baseline_nativeloss = {k: x for k, x in baseline.items() if x["Net2_bps"] < 0}
    for stage in (3, 4):
        rows = stage_sets[stage]["admitted"]
        shorts = [leg for x in rows for leg in x["legs"] if leg["side"] == "short"]
        rescued = [
            x for x in rows if x["key"] in baseline_nativeloss and x["Net2_bps"] > 0
        ]
        original_big = [
            x
            for x in baseline_nativeloss.values()
            if x["Net2_bps"] <= -x["initial_long_r_bps"]
        ]
        rescued_big = [
            x for x in rescued if x["key"] in {y["key"] for y in original_big}
        ]
        result["reversal_trade_audit"]["S" + str(stage)] = {
            "short_leg_T": len(shorts),
            "short_T_positive": sum(x["Net2_bps"] > 0 for x in shorts),
            "short_Net2_bps": sum(x["Net2_bps"] for x in shorts),
            "short_max_R": max((x["short_R_net2"] for x in shorts), default=None),
            "short_min_R": min((x["short_R_net2"] for x in shorts), default=None),
            "original_baseline_negative_opportunities": len(baseline_nativeloss),
            "original_baseline_losses_1R_or_worse": len(original_big),
            "initially_losing_opportunities_now_positive": len(rescued),
            "initially_big_losses_now_positive": len(rescued_big),
            "initially_big_losses_now_positive_ge1R": sum(
                x["Net2_bps"] >= x["initial_long_r_bps"] for x in rescued_big
            ),
            "positive_recoveries_examples": [
                {
                    "key": x["key"],
                    "old_net2": baseline[x["key"]]["Net2_bps"],
                    "new_net2": x["Net2_bps"],
                    "R": x["Net2_bps"] / x["initial_long_r_bps"],
                }
                for x in rescued[:10]
            ],
        }
    # Source manifest to reproduce. Detailed loss ledger not a new canonical
    # ledger; keep only original signal keys and modified candidate economics.
    raw = (
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    (path / "RESULT.json").write_bytes(raw)
    details = {
        "schema": "zel.trendrider.unified.causal_exit_trace.v1",
        "freeze_sha256": sha(freeze_bytes),
        "stages": {
            "S"
            + str(stage): {
                "accepted": stage_sets[stage]["admitted"],
                "rejected": stage_sets[stage]["rejected"],
            }
            for stage in range(5)
        },
        "not_canonical_trade_ledger": True,
        "live_order_authority": "BLOCKED",
    }
    detail_raw = (
        json.dumps(details, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    (path / "TRACES.json.gz").write_bytes(
        __import__("gzip").compress(detail_raw, compresslevel=6, mtime=0)
    )
    print(
        "FROZEN_EXPERIMENT_COMPLETED",
        "RESULT_SHA",
        sha(raw),
        "TRACES_SHA",
        sha((path / "TRACES.json.gz").read_bytes()),
        flush=True,
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    summary(args.root)

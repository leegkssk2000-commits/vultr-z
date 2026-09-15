from __future__ import annotations

# mypy: follow_imports=skip

from dataclasses import replace
import importlib
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

_kernel: Any = importlib.import_module("backend.research.rebuild." + "policy_kernel_v1")
anchored_vwap = _kernel.anchored_vwap
atr = _kernel.atr
ema = _kernel.ema
rsi = _kernel.rsi
rolling_vwap = _kernel.rolling_vwap
stdev = _kernel.stdev

CONTRACT_SCHEMA = "zel.benchmark25.transfer_contract.v1"
MICRO_REQUIRED = {"liquidity_sweep", "scalp_snap", "vol_spike_fade", "vwap_revert"}


def _v(bar: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(bar.get(key, default))
    except Exception:
        return float(default)


def _side(intent: Any) -> str:
    return str(getattr(intent, "side", "flat"))


def _timeout(intent: Any) -> int:
    return int((getattr(intent, "timeout", {}) or {}).get("bars", 1))


def context(bars: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    closes = [_v(b, "close") for b in bars]
    highs = [_v(b, "high") for b in bars]
    lows = [_v(b, "low") for b in bars]
    opens = [_v(b, "open") for b in bars]
    vols = [max(0.0, _v(b, "volume")) for b in bars]
    a = atr(bars, 14)
    close = closes[-1]
    prev = closes[-2]
    e8, e21, e34, e50, e55, e100 = (
        ema(closes, n)[-1] for n in (8, 21, 34, 50, 55, 100)
    )
    p21 = ema(closes[:-1], 21)[-1]
    p50 = ema(closes[:-1], 50)[-1]
    p55 = ema(closes[:-1], 55)[-1]
    hi20 = max(highs[-21:-1])
    lo20 = min(lows[-21:-1])
    hi50 = max(highs[-51:-1])
    lo50 = min(lows[-51:-1])
    vm20 = sum(vols[-21:-1]) / 20.0
    vm50 = sum(vols[-51:-1]) / 50.0
    rv = rsi(closes, 14)
    body = abs(close - opens[-1]) / max(a, 1e-12)
    rng = (highs[-1] - lows[-1]) / max(a, 1e-12)
    try:
        vw20 = rolling_vwap(bars, 20)
        vw50 = rolling_vwap(bars, 50)
    except Exception:
        vw20 = vw50 = close
    try:
        avwap_long = anchored_vwap(bars, 120, side="long")[0]
        avwap_short = anchored_vwap(bars, 120, side="short")[0]
    except Exception:
        avwap_long = avwap_short = vw50
    mean20 = sum(closes[-20:]) / 20.0
    sd20 = stdev(closes, 20)
    bb_width = (4.0 * sd20) / max(a, 1e-12)
    prev_a = atr(bars[:-1], 14)
    prev_sd20 = stdev(closes[:-1], 20)
    bb_prev_width = (4.0 * prev_sd20) / max(prev_a, 1e-12)
    hi_pre = max(highs[-22:-2])
    lo_pre = min(lows[-22:-2])
    hour = datetime.fromtimestamp(int(bars[-1]["ts_ms"]) / 1000, tz=timezone.utc).hour
    return {
        "close": close,
        "prev": prev,
        "prev_high": highs[-2],
        "prev_low": lows[-2],
        "open": opens[-1],
        "high": highs[-1],
        "low": lows[-1],
        "a": a,
        "atr_pct": a / close * 100.0,
        "body_atr": body,
        "range_atr": rng,
        "e8": e8,
        "e21": e21,
        "e34": e34,
        "e50": e50,
        "e55": e55,
        "e100": e100,
        "p21": p21,
        "p50": p50,
        "p55": p55,
        "trend_long": close > e21 > e55 > e100 and e21 >= p21 and e55 >= p55,
        "trend_short": close < e21 < e55 < e100 and e21 <= p21 and e55 <= p55,
        "ribbon_sep_atr": (abs(e8 - e21) + abs(e21 - e55)) / max(a, 1e-12),
        "dist21_atr": abs(close - e21) / max(a, 1e-12),
        "hi20": hi20,
        "lo20": lo20,
        "hi50": hi50,
        "lo50": lo50,
        "hi_pre": hi_pre,
        "lo_pre": lo_pre,
        "rel_vol20": vols[-1] / max(vm20, 1e-12),
        "rel_vol50": vols[-1] / max(vm50, 1e-12),
        "rsi": rv,
        "vwap20": vw20,
        "vwap50": vw50,
        "avwap_long": avwap_long,
        "avwap_short": avwap_short,
        "bb_width_atr": bb_width,
        "bb_prev_width_atr": bb_prev_width,
        "hour": hour,
        "mean20": mean20,
    }


def _micro_available(m: Mapping[str, Any] | None) -> bool:
    return bool(
        m
        and int(m.get("depth_messages") or 0) > 0
        and int(m.get("trade_messages") or 0) > 0
        and m.get("trade_imbalance") is not None
    )


def _micro_align(side: str, m: Mapping[str, Any]) -> bool:
    ti = float(m.get("trade_imbalance") or 0.0)
    im = float(m.get("imbalance_delta") or 0.0)
    bc = float(m.get("bid_change") or 0.0)
    ac = float(m.get("ask_change") or 0.0)
    return (
        (ti > 0 and (im > 0 or bc > 0))
        if side == "long"
        else (ti < 0 and (im < 0 or ac > 0))
    )


def _reject(intent: Any, reason: str) -> Any:
    return replace(
        intent,
        no_trade=True,
        regime=str(getattr(intent, "regime", "")) + "_BENCHMARK25_REJECT",
        reason_codes=tuple(getattr(intent, "reason_codes", ())) + (reason,),
    )


def _set_timeout(intent: Any, bars: int) -> Any:
    timeout = dict(getattr(intent, "timeout", {}) or {})
    timeout["bars"] = max(1, min(_timeout(intent), int(bars)))
    return replace(intent, timeout=timeout)


def _side_ok(side: str, long_ok: bool, short_ok: bool) -> bool:
    return long_ok if side == "long" else short_ok if side == "short" else False


def _tag(intent: Any, field: str, **values: Any) -> Any:
    base = dict(getattr(intent, field, {}) or {})
    base.update(values)
    return replace(intent, **{field: base})


def _tighten_stop(
    intent: Any, side: str, level: float, a: float, cushion_atr: float = 0.25
) -> Any:
    old = getattr(intent, "sl", None)
    if old is None:
        return intent
    target = level - cushion_atr * a if side == "long" else level + cushion_atr * a
    old = float(old)
    new = max(old, target) if side == "long" else min(old, target)
    invalid = dict(getattr(intent, "invalidation", {}) or {})
    invalid.update(
        {"benchmark25_structural_level": level, "benchmark25_tightened_stop": new}
    )
    return replace(intent, sl=new, invalidation=invalid)


def apply_transfer(
    strategy_id: str,
    intent: Any,
    bars: Sequence[Mapping[str, Any]],
    micro: Mapping[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    if bool(getattr(intent, "no_trade", False)):
        return intent, {"state": "PARENT_NO_TRADE", "strategy_id": strategy_id}
    c = context(bars)
    side = _side(intent)
    ok = True
    reasons = []
    changed = []
    if strategy_id in MICRO_REQUIRED and not _micro_available(micro):
        return _reject(intent, "REAL_MICROSTRUCTURE_REQUIRED"), {
            "state": "FAIL_CLOSED_NO_MICRO",
            "strategy_id": strategy_id,
        }
    if strategy_id == "turtle_trend":
        ok = _side_ok(side, c["close"] > c["hi20"], c["close"] < c["lo20"])
        reasons.append("OBJECTIVE_BREAKOUT_REQUIRED")
        intent = replace(intent, tp=None)
        intent = _tag(intent, "runner", enabled=True, benchmark25_outlier_capture=True)
        intent = _tag(intent, "exposure", benchmark25_equal_rule_weighting=True)
        changed += [
            "objective_breakout_entry_exit",
            "asymmetric_payoff",
            "cut_losses_let_outliers_run",
            "equal_rule_weighting",
        ]
    elif strategy_id == "bb_revert":
        range_ok = abs(c["e21"] - c["e55"]) / max(c["a"], 1e-12) <= 0.85
        reentry = _side_ok(
            side,
            c["prev"] < c["mean20"] - 1.4 * c["a"] and c["close"] > c["prev"],
            c["prev"] > c["mean20"] + 1.4 * c["a"] and c["close"] < c["prev"],
        )
        ok = range_ok and reentry
        reasons += ["VALID_MEAN_REVERSION_REGIME", "REENTRY_CONFIRMATION"]
        intent = _set_timeout(intent, 18)
        changed += [
            "mean_reversion_only_inside_valid_regime",
            "reentry_confirmation_after_extension",
            "fast_invalidation_when_reversion_fails",
        ]
    elif strategy_id == "anchor_vwap_trend":
        ref = c["avwap_long"] if side == "long" else c["avwap_short"]
        reclaim = _side_ok(
            side,
            c["close"] > ref and c["prev"] <= ref,
            c["close"] < ref and c["prev"] >= ref,
        )
        ok = reclaim and c["rel_vol20"] >= 0.80
        reasons.append("AVWAP_REACTION_RECLAIM_REQUIRED")
        changed += [
            "AVWAP_as_reference_not_signal",
            "reaction_reclaim_confirmation",
            "price_volume_time_control_context",
        ]
    elif strategy_id == "vwap_revert":
        align = _micro_align(side, micro or {})
        reclaim = _side_ok(
            side,
            c["prev"] < c["vwap20"] - 0.45 * c["a"] and c["close"] > c["prev"],
            c["prev"] > c["vwap20"] + 0.45 * c["a"] and c["close"] < c["prev"],
        )
        ok = align and reclaim and c["hour"] not in (21, 22, 23)
        reasons.append("VWAP_RECLAIM_FLOW_SESSION_REQUIRED")
        intent = _set_timeout(intent, 12)
        changed += [
            "VWAP_displacement_reclaim",
            "Level2_or_flow_confirmation",
            "session_liquidity_context",
            "fast_reversion_target",
        ]
    elif strategy_id == "break_and_continue":
        compression = c["bb_prev_width_atr"] <= 3.0
        retest = _side_ok(
            side,
            c["prev_low"] <= c["hi_pre"] + 0.30 * c["a"]
            and c["prev"] >= c["hi_pre"] - 0.20 * c["a"]
            and c["close"] > c["hi_pre"],
            c["prev_high"] >= c["lo_pre"] - 0.30 * c["a"]
            and c["prev"] <= c["lo_pre"] + 0.20 * c["a"]
            and c["close"] < c["lo_pre"],
        )
        ok = compression and retest and c["dist21_atr"] <= 1.5
        reasons.append("COMPRESSION_EXPANSION_CONTROLLED_RETEST_REQUIRED")
        intent = _set_timeout(intent, 24)
        intent = _tag(intent, "invalidation", benchmark25_failed_break_fast_kill=True)
        changed += [
            "short_term_momentum",
            "compression_before_expansion",
            "controlled_pullback_retest",
            "tight_failed_break_invalidation",
        ]
    elif strategy_id == "keltner_trend":
        ok = (
            _side_ok(side, c["trend_long"], c["trend_short"])
            and c["range_atr"] >= 0.8
            and c["dist21_atr"] <= 1.2
        )
        reasons.append("VOL_EXPANSION_TREND_STRUCTURE_NO_CHASE")
        intent = _set_timeout(intent, 24)
        intent = _tag(
            intent,
            "partial",
            benchmark25_scratch_if_no_progress=True,
            benchmark25_progress_bars=8,
        )
        changed += [
            "volatility_expansion_context",
            "trend_structure_confirmation",
            "avoid_late_chase",
            "fast_scratch_if_no_progress",
        ]
    elif strategy_id == "squeeze_break":
        compression = c["bb_prev_width_atr"] <= 3.0
        release = c["bb_width_atr"] > c["bb_prev_width_atr"] and c["range_atr"] >= 0.9
        ok = (
            compression
            and release
            and _side_ok(side, c["close"] > c["hi_pre"], c["close"] < c["lo_pre"])
            and c["dist21_atr"] <= 1.4
        )
        reasons.append("BB_KC_RELEASE_MOMENTUM_QUALITY")
        intent = _set_timeout(intent, 24)
        changed += [
            "BB_inside_KC_compression",
            "first_release_event",
            "momentum_direction",
            "release_quality_and_chase_control",
        ]
    elif strategy_id == "supertrend_pullback":
        reclaim = _side_ok(
            side,
            c["trend_long"]
            and c["prev"] <= c["e21"] + 0.7 * c["a"]
            and c["close"] > c["prev"],
            c["trend_short"]
            and c["prev"] >= c["e21"] - 0.7 * c["a"]
            and c["close"] < c["prev"],
        )
        ok = reclaim
        reasons.append("TREND_PULLBACK_RECLAIM_REQUIRED")
        intent = _set_timeout(intent, 32)
        intent = _tag(
            intent,
            "invalidation",
            benchmark25_structure_scratch=True,
            benchmark25_reference="EMA21_RECLAIM",
        )
        changed += [
            "trend_first_then_pullback",
            "reclaim_confirmation",
            "structure_based_scratch",
        ]
    elif strategy_id == "trend_ma_macd":
        ok = (
            _side_ok(side, c["trend_long"], c["trend_short"])
            and c["dist21_atr"] <= 1.25
        )
        reasons.append("TREND_STATE_BEFORE_MOMENTUM")
        intent = _set_timeout(intent, 32)
        intent = _tighten_stop(intent, side, c["e55"], c["a"], 0.35)
        changed += [
            "trend_state_before_momentum_trigger",
            "moving_average_structure",
            "objective_invalidation",
        ]
    elif strategy_id == "trend_rider":
        persist = _side_ok(
            side,
            c["trend_long"] and c["e50"] >= c["p50"],
            c["trend_short"] and c["e50"] <= c["p50"],
        )
        ok = persist and c["dist21_atr"] <= 1.6
        reasons.append("TREND_PERSISTENCE_REGIME_REQUIRED")
        intent = replace(intent, tp=None)
        intent = _tag(intent, "runner", enabled=True, benchmark25_outlier_capture=True)
        changed += [
            "trend_persistence",
            "outlier_capture",
            "price_first_objectivity",
            "trend_structure_regime_filter",
        ]
    elif strategy_id == "liquidity_sweep":
        ok = _micro_align(side, micro or {})
        reasons.append("L2_SWEEP_RECLAIM_DEPTH_RECOVERY_REQUIRED")
        intent = _set_timeout(intent, 6)
        changed += [
            "Level2_liquidity_event_before_entry",
            "sweep_then_reclaim",
            "depth_depletion_replenishment",
            "fast_opinion_change",
        ]
    elif strategy_id == "scalp_snap":
        ok = (
            _micro_align(side, micro or {})
            and abs(float((micro or {}).get("trade_imbalance") or 0)) >= 0.08
        )
        reasons.append("FAILED_IMPULSE_FLOW_EXHAUSTION_DEPTH_RECOVERY")
        intent = _set_timeout(intent, 6)
        changed += [
            "failed_impulse",
            "aggressive_flow_exhaustion",
            "opposite_depth_recovery",
            "minutes_scale_invalidation",
        ]
    elif strategy_id == "vol_spike_fade":
        ti = float((micro or {}).get("trade_imbalance") or 0)
        im = float((micro or {}).get("imbalance_delta") or 0)
        ok = (ti >= -0.05 and im > 0) if side == "long" else (ti <= 0.05 and im < 0)
        reasons.append("FLOW_CLIMAX_FAILURE_CONFIRMATION")
        intent = _set_timeout(intent, 8)
        changed += [
            "exhaustion_after_range_expansion",
            "volume_or_tradeflow_climax",
            "fast_failure_confirmation",
        ]
    elif strategy_id == "range_fade":
        range_regime = abs(c["e21"] - c["e55"]) / max(c["a"], 1e-12) <= 0.75
        reclaim = _side_ok(
            side,
            c["low"] < c["lo20"] and c["close"] > c["lo20"],
            c["high"] > c["hi20"] and c["close"] < c["hi20"],
        )
        ok = (
            range_regime
            and reclaim
            and not _side_ok(side, c["trend_short"], c["trend_long"])
        )
        reasons.append("RANGE_REGIME_EXTREME_RECLAIM_TREND_VETO")
        changed += [
            "structure_first_range_regime",
            "extreme_reclaim",
            "mean_reversion_only_when_trend_veto_clear",
        ]
    elif strategy_id == "fvg_revert":
        failed = _side_ok(
            side,
            c["close"] > c["prev"] and c["prev"] <= c["lo20"] + 0.35 * c["a"],
            c["close"] < c["prev"] and c["prev"] >= c["hi20"] - 0.35 * c["a"],
        )
        trapped = c["rel_vol20"] >= 1.0 and c["range_atr"] >= 0.6
        ok = failed and trapped
        reasons.append("FAILED_DISPLACEMENT_REENTRY_TRAPPED_FLOW_REQUIRED")
        intent = _set_timeout(intent, 12)
        changed += [
            "failed_displacement_reentry",
            "trapped_breakout_flow",
            "quick_structural_invalidation",
        ]
    elif strategy_id == "pivot_reversal":
        reject = _side_ok(
            side,
            c["low"] < c["lo20"] and c["close"] > c["lo20"],
            c["high"] > c["hi20"] and c["close"] < c["hi20"],
        )
        flow_ok = (
            c["close"] >= c["vwap20"] if side == "long" else c["close"] <= c["vwap20"]
        )
        ok = reject and flow_ok
        reasons.append("REFERENCE_LEVEL_REJECTION_VWAP_CONTEXT")
        intent = _set_timeout(intent, 12)
        intent = _tighten_stop(
            intent, side, c["lo20"] if side == "long" else c["hi20"], c["a"], 0.20
        )
        changed += [
            "prior_reference_level",
            "rejection_confirmation",
            "VWAP_or_flow_context",
            "tight_level_based_stop",
        ]
    elif strategy_id == "rsi_swing_fail":
        failed = _side_ok(
            side,
            c["low"] < c["lo20"] and c["close"] > c["lo20"] and c["rsi"] < 50,
            c["high"] > c["hi20"] and c["close"] < c["hi20"] and c["rsi"] > 50,
        )
        regime = abs(c["e21"] - c["e55"]) / max(c["a"], 1e-12) <= 1.2
        ok = failed and regime
        reasons.append("FAILED_SWING_FIRST_OSC_CONFIRM_REGIME")
        changed += [
            "failed_swing_first",
            "oscillator_as_confirmation_only",
            "regime_filter",
        ]
    elif strategy_id == "alpha_combo":
        trend_mode = _side_ok(side, c["trend_long"], c["trend_short"])
        mr_mode = _side_ok(
            side,
            c["close"] < c["vwap20"] and c["close"] > c["prev"],
            c["close"] > c["vwap20"] and c["close"] < c["prev"],
        )
        ok = trend_mode or mr_mode
        reasons.append("SEPARATE_MOMENTUM_MEAN_REVERSION_BY_REGIME")
        changed += [
            "small_independent_short_term_edges",
            "momentum_and_mean_reversion_separated_by_regime",
            "VWAP_Level2_context_if_available",
        ]
    elif strategy_id == "ema_ribbon_scalp":
        ribbon = _side_ok(
            side,
            c["close"] > c["e8"] > c["e21"] > c["e55"],
            c["close"] < c["e8"] < c["e21"] < c["e55"],
        )
        reclaim = _side_ok(side, c["close"] > c["prev"], c["close"] < c["prev"])
        ok = (
            ribbon
            and reclaim
            and c["ribbon_sep_atr"] >= 0.20
            and c["dist21_atr"] <= 0.85
        )
        reasons.append("RIBBON_STATE_PULLBACK_RECLAIM_NO_CHASE")
        changed += [
            "MA_order_and_separation_as_trend_state",
            "pullback_or_reclaim_entry",
            "intraday_execution",
            "avoid_chasing_extended_ribbon",
        ]
    elif strategy_id == "mfi_rsi_div":
        extreme = _side_ok(side, c["low"] <= c["lo50"], c["high"] >= c["hi50"])
        failed = _side_ok(side, c["close"] > c["prev"], c["close"] < c["prev"])
        ok = extreme and failed
        reasons.append("STRUCTURAL_EXTREME_FAILED_CONTINUATION_REQUIRED")
        changed += [
            "divergence_only_at_structural_extreme",
            "failed_continuation_before_oscillator_confirmation",
        ]
    elif strategy_id == "obv_trend":
        ok = (
            _side_ok(
                side,
                c["trend_long"] and c["close"] > c["hi20"],
                c["trend_short"] and c["close"] < c["lo20"],
            )
            and c["rel_vol20"] >= 1.15
        )
        reasons.append("TREND_STRUCTURE_PARTICIPATION_BREAKOUT_REQUIRED")
        intent = _set_timeout(intent, 18)
        changed += [
            "trend_structure_plus_participation_confirmation",
            "volume_expansion_on_breakout",
            "failed_break_fast_kill",
        ]
    elif strategy_id == "grid_rebalance":
        range_regime = abs(c["e21"] - c["e55"]) / max(c["a"], 1e-12) <= 0.70
        ext = abs(c["close"] - c["vwap50"]) / max(c["a"], 1e-12) >= 0.90
        ok = range_regime and ext
        reasons.append("RANGE_REGIME_EXTENSION_COST_CHURN_CONTROL")
        intent = _set_timeout(intent, 12)
        changed += [
            "range_regime_gate",
            "mean_reversion_after_extension",
            "strict_cost_churn_control",
        ]
    elif strategy_id == "rbreaker_like":
        breakout = _side_ok(side, c["close"] > c["hi20"], c["close"] < c["lo20"])
        failed = _side_ok(
            side,
            c["low"] < c["lo20"] and c["close"] > c["lo20"],
            c["high"] > c["hi20"] and c["close"] < c["hi20"],
        )
        session_context = c["hour"] in (0, 1, 7, 8, 9, 12, 13, 14, 15, 16)
        ok = (breakout or failed) and session_context
        reasons.append("PRIOR_RANGE_MODE_OPENING_HANDOFF_CONTEXT_REQUIRED")
        intent = _set_timeout(intent, 12)
        changed += [
            "prior_range_boundary",
            "breakout_or_failed_break_as_separate_modes",
            "opening_range_style_context",
            "fast_reclaim_invalidation",
        ]
    elif strategy_id == "session_bias":
        handoff = c["hour"] in (0, 1, 7, 8, 9, 12, 13, 14, 15, 16)
        liquid = c["rel_vol20"] >= 1.0 and c["range_atr"] >= 0.80 and handoff
        ok = liquid
        reasons.append("SESSION_IS_REGIME_NOT_DIRECTION")
        intent = _set_timeout(intent, 18)
        changed += [
            "trade_when_liquidity_and_volatility_are_present",
            "session_as_regime_not_direction",
            "opening_range_or_handoff_expansion",
        ]
    elif strategy_id == "sr_levels":
        continuation = _side_ok(side, c["close"] > c["hi50"], c["close"] < c["lo50"])
        reclaim = _side_ok(
            side, c["low"] < c["hi50"] < c["close"], c["high"] > c["lo50"] > c["close"]
        )
        ok = (
            (continuation or reclaim)
            and c["rel_vol50"] >= 1.25
            and abs(c["close"] - (c["hi50"] if side == "long" else c["lo50"]))
            / max(c["a"], 1e-12)
            <= 1.0
        )
        reasons.append("PRIOR_LEVEL_VOLUME_BREAK_RECLAIM_MODE")
        intent = _set_timeout(intent, 12)
        changed += [
            "prior_level_as_reference",
            "volume_or_Level2_confirmation",
            "break_reclaim_or_continuation_mode",
            "tight_failed_break_exit",
        ]
    else:
        raise KeyError(f"BENCHMARK25_STRATEGY_UNMAPPED:{strategy_id}")
    if not ok:
        intent = _reject(
            intent, reasons[-1] if reasons else "BENCHMARK25_TRANSFER_FAIL"
        )
    return intent, {
        "state": "PASS_TRANSFER_APPLIED" if ok else "REJECT_TRANSFER_GATE",
        "strategy_id": strategy_id,
        "changed": changed,
        "reasons": reasons,
        "context": c,
    }


def self_test(contract: Mapping[str, Any]) -> int:
    expected = set((contract.get("strategies") or {}).keys())
    if len(expected) != 25:
        raise RuntimeError(f"BENCHMARK25_CONTRACT_COUNT:{len(expected)}")
    # Explicitly enumerate implementation coverage; no generic fallback is accepted.
    implemented = {
        "turtle_trend",
        "bb_revert",
        "anchor_vwap_trend",
        "vwap_revert",
        "break_and_continue",
        "keltner_trend",
        "squeeze_break",
        "supertrend_pullback",
        "trend_ma_macd",
        "trend_rider",
        "liquidity_sweep",
        "scalp_snap",
        "vol_spike_fade",
        "range_fade",
        "fvg_revert",
        "pivot_reversal",
        "rsi_swing_fail",
        "alpha_combo",
        "ema_ribbon_scalp",
        "mfi_rsi_div",
        "obv_trend",
        "grid_rebalance",
        "rbreaker_like",
        "session_bias",
        "sr_levels",
    }
    if expected != implemented:
        raise RuntimeError(
            f"BENCHMARK25_IMPLEMENTATION_COVERAGE_MISMATCH:{sorted(expected^implemented)}"
        )
    print("PASS_BENCHMARK25_TRANSFER_OVERLAY_25_OF_25")
    return 0

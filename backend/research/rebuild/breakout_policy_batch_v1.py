from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild.policy_kernel_v1 import (
    DecisionIntent,
    atr,
    digest,
    ema,
    evaluator_adapter_sha,
    f,
    hold_intent,
    risk_geometry,
    sma,
    stdev,
    ts,
    validate_authority,
    validate_bars,
)

HOUR_MS = 3_600_000


@dataclass(frozen=True)
class BreakoutPolicyConfig:
    timeframe_ms: int = HOUR_MS
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
    breakout_lookback: int = 20
    box_lookback: int = 8
    keltner_ema_len: int = 20
    keltner_atr_mult: float = 1.5
    squeeze_bb_len: int = 20
    squeeze_bb_mult: float = 2.0
    max_stale_intervals: int = 2
    risk_fraction_of_equity: float = 0.005
    max_notional_fraction_of_equity: float = 0.15
    min_cost_budget_ratio: float = 1.25
    timeout_bars: int = 48

    @property
    def sha(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class FeatureSnapshot:
    strategy_id: str
    symbol: str
    signal_ts: int
    fresh: bool
    close: float
    atr: float
    values: Mapping[str, Any]
    feature_sha: str


EVIDENCE = {
    "break_and_continue": (
        "HIST_SOURCE_BREAK_AND_CONTINUE_R7",
        "SSRN_447361",
        "TSMOM_CAUSAL_SEPARATION",
        "BINGX_FEE_SCHEDULE",
    ),
    "keltner_trend": (
        "HIST_SOURCE_KELTNER_TREND_R7",
        "SSRN_2786955",
        "TSMOM_CAUSAL_SEPARATION",
        "BINGX_FEE_SCHEDULE",
    ),
    "squeeze_break": (
        "HIST_SOURCE_SQUEEZE_BREAK_R7",
        "VOLATILITY_COMPRESSION_RELEASE_ARCHITECTURE",
        "SSRN_2786955",
        "BINGX_FEE_SCHEDULE",
    ),
}


def _fresh(signal_ts: int, now_ts_ms: int, cfg: BreakoutPolicyConfig) -> bool:
    return 0 <= int(now_ts_ms) - int(signal_ts) <= cfg.max_stale_intervals * cfg.timeframe_ms


def _base(bars: Sequence[Mapping[str, Any]], cfg: BreakoutPolicyConfig) -> tuple[list[float], float, list[float], list[float]]:
    validate_bars(bars, minimum=max(cfg.ema_slow_len + 3, cfg.breakout_lookback + 3, 64))
    closes = [f(b, "close") for b in bars]
    a = atr(bars, cfg.atr_len)
    fast = ema(closes, cfg.ema_fast_len)
    slow = ema(closes, cfg.ema_slow_len)
    return closes, a, fast, slow


def _snapshot(strategy_id: str, symbol: str, bars: Sequence[Mapping[str, Any]], now_ts_ms: int,
              close: float, a: float, values: Mapping[str, Any], cfg: BreakoutPolicyConfig) -> FeatureSnapshot:
    signal_ts = ts(bars[-1])
    body = {"strategy_id": strategy_id, "symbol": symbol, "signal_ts": signal_ts,
            "close": close, "atr": a, "values": values}
    return FeatureSnapshot(strategy_id, symbol, signal_ts, _fresh(signal_ts, now_ts_ms, cfg),
                           close, a, values, digest(body))


def compute_break_and_continue_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
                                       config: BreakoutPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or BreakoutPolicyConfig()
    closes, a, fast, slow = _base(bars, cfg)
    prior = bars[-(cfg.breakout_lookback + 1):-1]
    prior_high = max(f(b, "high") for b in prior)
    prior_low = min(f(b, "low") for b in prior)
    box = bars[-(cfg.box_lookback + 1):-1]
    box_high = max(f(b, "high") for b in box)
    box_low = min(f(b, "low") for b in box)
    box_height_atr = (box_high - box_low) / a
    close = closes[-1]
    long_break = close > prior_high and close > fast[-1] > slow[-1]
    short_break = close < prior_low and close < fast[-1] < slow[-1]
    chase_atr = max((close - prior_high) / a, (prior_low - close) / a, 0.0)
    values = {
        "prior_high": prior_high, "prior_low": prior_low, "box_high": box_high, "box_low": box_low,
        "box_height_atr": box_height_atr, "long_break": long_break, "short_break": short_break,
        "ema_fast": fast[-1], "ema_slow": slow[-1], "chase_atr": chase_atr,
    }
    return _snapshot("break_and_continue", symbol, bars, now_ts_ms, close, a, values, cfg)


def compute_keltner_trend_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
                                  config: BreakoutPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or BreakoutPolicyConfig()
    closes, a, fast, slow = _base(bars, cfg)
    center_series = ema(closes, cfg.keltner_ema_len)
    center = center_series[-1]
    prev_a = atr(bars[:-1], cfg.atr_len)
    upper = center + cfg.keltner_atr_mult * a
    lower = center - cfg.keltner_atr_mult * a
    close = closes[-1]
    expansion = a / max(prev_a, 1e-12)
    long_break = close > upper and fast[-1] > slow[-1] and fast[-1] >= fast[-2]
    short_break = close < lower and fast[-1] < slow[-1] and fast[-1] <= fast[-2]
    chase_atr = max((close - upper) / a, (lower - close) / a, 0.0)
    values = {
        "center": center, "upper": upper, "lower": lower, "expansion_ratio": expansion,
        "long_break": long_break, "short_break": short_break, "chase_atr": chase_atr,
        "ema_fast": fast[-1], "ema_slow": slow[-1],
    }
    return _snapshot("keltner_trend", symbol, bars, now_ts_ms, close, a, values, cfg)


def compute_squeeze_break_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
                                  config: BreakoutPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or BreakoutPolicyConfig()
    closes, a, fast, slow = _base(bars, cfg)
    mid = sma(closes, cfg.squeeze_bb_len)
    sigma = stdev(closes, cfg.squeeze_bb_len)
    bb_upper = mid + cfg.squeeze_bb_mult * sigma
    bb_lower = mid - cfg.squeeze_bb_mult * sigma
    kc_center = ema(closes, cfg.keltner_ema_len)[-1]
    kc_upper = kc_center + cfg.keltner_atr_mult * a
    kc_lower = kc_center - cfg.keltner_atr_mult * a

    prev = bars[:-1]
    prev_closes = closes[:-1]
    prev_a = atr(prev, cfg.atr_len)
    prev_mid = sma(prev_closes, cfg.squeeze_bb_len)
    prev_sigma = stdev(prev_closes, cfg.squeeze_bb_len)
    prev_bb_upper = prev_mid + cfg.squeeze_bb_mult * prev_sigma
    prev_bb_lower = prev_mid - cfg.squeeze_bb_mult * prev_sigma
    prev_kc_center = ema(prev_closes, cfg.keltner_ema_len)[-1]
    prev_kc_upper = prev_kc_center + cfg.keltner_atr_mult * prev_a
    prev_kc_lower = prev_kc_center - cfg.keltner_atr_mult * prev_a
    prev_squeeze = prev_bb_upper <= prev_kc_upper and prev_bb_lower >= prev_kc_lower
    now_squeeze = bb_upper <= kc_upper and bb_lower >= kc_lower
    close = closes[-1]
    impulse_atr = abs(close - closes[-2]) / a
    long_release = prev_squeeze and not now_squeeze and close > bb_upper and fast[-1] > slow[-1]
    short_release = prev_squeeze and not now_squeeze and close < bb_lower and fast[-1] < slow[-1]
    values = {
        "bb_upper": bb_upper, "bb_lower": bb_lower, "kc_upper": kc_upper, "kc_lower": kc_lower,
        "prev_squeeze": prev_squeeze, "now_squeeze": now_squeeze, "long_release": long_release,
        "short_release": short_release, "impulse_atr": impulse_atr,
        "ema_fast": fast[-1], "ema_slow": slow[-1],
    }
    return _snapshot("squeeze_break", symbol, bars, now_ts_ms, close, a, values, cfg)


def _build(feature: FeatureSnapshot, *, policy_source_sha: str, verified_round_trip_cost_bps: float,
           config: BreakoutPolicyConfig | None = None) -> DecisionIntent:
    cfg = config or BreakoutPolicyConfig()
    validate_authority(policy_source_sha=policy_source_sha,
                       verified_round_trip_cost_bps=verified_round_trip_cost_bps)
    sid = feature.strategy_id
    if sid not in EVIDENCE:
        raise ValueError("UNKNOWN_STRATEGY")
    schema = f"zel.{sid}.policy.v1"
    entry_rule = {
        "break_and_continue": "closed_bar_prior_range_break_with_ema_alignment_and_anti_chase",
        "keltner_trend": "closed_bar_keltner_break_with_channel_expansion_and_ema_alignment",
        "squeeze_break": "closed_bar_bb_kc_squeeze_release_with_directional_alignment",
    }[sid]
    strength_norm = "breakout_or_release_impulse_over_atr_clipped_0_2_then_divide_2"
    if not feature.fresh:
        return hold_intent(strategy_id=sid, policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization=strength_norm, regime="NO_TRADE_STALE",
                           reasons=("STALE_SOURCE_FAIL_CLOSED",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)

    v = feature.values
    if sid == "break_and_continue":
        long_ok = bool(v["long_break"] and float(v["box_height_atr"]) <= 4.0 and float(v["chase_atr"]) <= 1.0)
        short_ok = bool(v["short_break"] and float(v["box_height_atr"]) <= 4.0 and float(v["chase_atr"]) <= 1.0)
        strength_raw = max(0.0, 1.0 - min(float(v["chase_atr"]), 1.0)) + 0.5
        regime = "BREAKOUT_CONTINUATION_ALIGNED"
    elif sid == "keltner_trend":
        long_ok = bool(v["long_break"] and float(v["expansion_ratio"]) >= 1.0 and float(v["chase_atr"]) <= 1.0)
        short_ok = bool(v["short_break"] and float(v["expansion_ratio"]) >= 1.0 and float(v["chase_atr"]) <= 1.0)
        strength_raw = min(2.0, float(v["expansion_ratio"]))
        regime = "KELTNER_EXPANSION_TREND"
    else:
        long_ok = bool(v["long_release"] and float(v["impulse_atr"]) >= 0.25 and float(v["impulse_atr"]) <= 2.5)
        short_ok = bool(v["short_release"] and float(v["impulse_atr"]) >= 0.25 and float(v["impulse_atr"]) <= 2.5)
        strength_raw = min(2.0, float(v["impulse_atr"]))
        regime = "VOLATILITY_COMPRESSION_RELEASE"

    if long_ok == short_ok:
        return hold_intent(strategy_id=sid, policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization=strength_norm, regime="NO_TRADE",
                           reasons=("NO_UNAMBIGUOUS_ENTRY",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)

    side = "long" if long_ok else "short"
    entry = feature.close
    stop = entry - 1.25 * feature.atr if side == "long" else entry + 1.25 * feature.atr
    notional, risk_distance_bps = risk_geometry(entry=entry, stop=stop,
                                                 risk_fraction=cfg.risk_fraction_of_equity,
                                                 exposure_cap=cfg.max_notional_fraction_of_equity)
    move_budget_bps = risk_distance_bps * 2.0
    ratio = move_budget_bps / verified_round_trip_cost_bps
    if ratio < cfg.min_cost_budget_ratio:
        return hold_intent(strategy_id=sid, policy_schema=schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization=strength_norm, regime="NO_TRADE_COST",
                           reasons=("STRUCTURAL_COST_BUDGET_BELOW_MIN",), verified_cost_bps=verified_round_trip_cost_bps,
                           timeout_bars=cfg.timeout_bars, risk_fraction=cfg.risk_fraction_of_equity,
                           exposure_cap=cfg.max_notional_fraction_of_equity)

    strength = min(1.0, max(0.0, strength_raw) / 2.0)
    return DecisionIntent(
        schema_version=schema, strategy_id=sid, source_sha=policy_source_sha, config_sha=cfg.sha,
        feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[sid], symbol=feature.symbol, side=side,
        signal_ts=feature.signal_ts, entry_rule=entry_rule, entry_strength=strength,
        strength_normalization=strength_norm, regime=regime, no_trade=False,
        invalidation={"initial_stop": stop, "hard_no_adverse_add": True},
        risk_size={"risk_fraction_of_equity": cfg.risk_fraction_of_equity,
                   "risk_distance_bps": risk_distance_bps},
        exposure={"notional_fraction_of_equity": notional, "cap": cfg.max_notional_fraction_of_equity},
        sl=stop, tp=None, timeout={"bars": cfg.timeout_bars}, partial={"enabled": False},
        trailing={"enabled": True, "type": "atr_structure_after_favorable_progress"},
        runner={"enabled": True, "take_profit_owned_by_policy": False},
        pyramiding={"enabled": False, "adverse_add": False},
        cooldown={"bars": 2, "one_entry_per_transition": True},
        turnover={"duplicate_transition_forbidden": True, "max_new_entries_per_bar": 1},
        reason_codes=("ENTRY_POLICY_PASS",),
        verified_round_trip_cost_bps=float(verified_round_trip_cost_bps),
        move_budget_bps=move_budget_bps, cost_budget_ratio=ratio,
    )


def build_break_and_continue_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "break_and_continue":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)


def build_keltner_trend_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "keltner_trend":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)


def build_squeeze_break_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "squeeze_break":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)


__all__ = [
    "BreakoutPolicyConfig", "FeatureSnapshot",
    "compute_break_and_continue_feature", "compute_keltner_trend_feature", "compute_squeeze_break_feature",
    "build_break_and_continue_intent", "build_keltner_trend_intent", "build_squeeze_break_intent",
    "evaluator_adapter_sha",
]

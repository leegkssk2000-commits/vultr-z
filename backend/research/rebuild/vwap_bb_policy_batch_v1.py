from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild.policy_kernel_v1 import (
    DecisionIntent,
    anchored_vwap,
    atr,
    control_delayed_entry,
    control_direction_flip,
    control_time_placebo,
    digest,
    ema,
    evaluator_adapter_sha,
    f,
    hold_intent,
    risk_geometry,
    rolling_vwap,
    rsi,
    sma,
    stdev,
    ts,
    validate_authority,
    validate_bars,
)

HOUR_MS = 3_600_000


@dataclass(frozen=True)
class CommonPolicyConfig:
    timeframe_ms: int = HOUR_MS
    atr_len: int = 14
    ema_fast_len: int = 21
    ema_slow_len: int = 55
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
    "anchor_vwap_trend": (
        "HISTORICAL_OWNER_SHA_37712baa33d8ccb8588c4ac7ddf7b17b143d83d4a0050ca164fb9f1655db32e3",
        "EVIDENCE_AVWAP_PRIOR_V1",
        "BINGX_FEE_SCHEDULE",
    ),
    "vwap_revert": (
        "HISTORICAL_OWNER_RESTORE25_VWAP_REVERT",
        "ARXIV_2111.11609_MEAN_REVERSION",
        "BINGX_FEE_SCHEDULE",
    ),
    "bb_revert": (
        "HISTORICAL_OWNER_SHA_7bbf728f3624eb2960ab37245ab39762918e1ed3512b1c1d3ae1d595e8977f3c",
        "ARXIV_1410.5513_INTRADAY_MEAN_REVERSION",
        "BINGX_FEE_SCHEDULE",
    ),
}


def _base_arrays(bars: Sequence[Mapping[str, Any]], cfg: CommonPolicyConfig) -> tuple[list[float], list[float], list[float], float, list[float], list[float]]:
    validate_bars(bars, minimum=max(cfg.ema_slow_len + 3, cfg.atr_len + 3, 64))
    closes = [f(b, "close") for b in bars]
    highs = [f(b, "high") for b in bars]
    lows = [f(b, "low") for b in bars]
    a = atr(bars, cfg.atr_len)
    fast = ema(closes, cfg.ema_fast_len)
    slow = ema(closes, cfg.ema_slow_len)
    return closes, highs, lows, a, fast, slow


def _fresh(signal_ts: int, now_ts_ms: int, cfg: CommonPolicyConfig) -> bool:
    return 0 <= int(now_ts_ms) - int(signal_ts) <= cfg.max_stale_intervals * cfg.timeframe_ms


def compute_anchor_vwap_trend_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
                                      config: CommonPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or CommonPolicyConfig()
    closes, _, _, a, fast, slow = _base_arrays(bars, cfg)
    avwap_long, anchor_low_ts = anchored_vwap(bars, 120, side="long")
    avwap_short, anchor_high_ts = anchored_vwap(bars, 120, side="short")
    close, prev = closes[-1], closes[-2]
    long_cross = prev <= avwap_long and close > avwap_long
    short_cross = prev >= avwap_short and close < avwap_short
    trend_long = close > fast[-1] > slow[-1] and fast[-1] >= fast[-2]
    trend_short = close < fast[-1] < slow[-1] and fast[-1] <= fast[-2]
    dist_long = (close - avwap_long) / a
    dist_short = (avwap_short - close) / a
    signal_ts = ts(bars[-1])
    values = {
        "avwap_long": avwap_long, "avwap_short": avwap_short,
        "anchor_low_ts": anchor_low_ts, "anchor_high_ts": anchor_high_ts,
        "ema_fast": fast[-1], "ema_slow": slow[-1],
        "long_cross": long_cross, "short_cross": short_cross,
        "trend_long": trend_long, "trend_short": trend_short,
        "dist_long_atr": dist_long, "dist_short_atr": dist_short,
    }
    body = {"strategy_id":"anchor_vwap_trend","symbol":symbol,"signal_ts":signal_ts,"close":close,"atr":a,"values":values}
    return FeatureSnapshot("anchor_vwap_trend", symbol, signal_ts, _fresh(signal_ts, now_ts_ms, cfg), close, a, values, digest(body))


def compute_vwap_revert_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
                                config: CommonPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or CommonPolicyConfig()
    closes, _, _, a, fast, slow = _base_arrays(bars, cfg)
    vwap_now = rolling_vwap(bars, 48)
    prev_vwap = rolling_vwap(bars[:-1], 48)
    close, prev = closes[-1], closes[-2]
    ext = (close - vwap_now) / a
    prev_ext = (prev - prev_vwap) / a
    r = rsi(closes, 14)
    long_reclaim = prev_ext <= -1.5 and ext > prev_ext and r <= 42.0
    short_reclaim = prev_ext >= 1.5 and ext < prev_ext and r >= 58.0
    strong_down = close < fast[-1] < slow[-1] and abs(close - slow[-1]) / close > 0.04
    strong_up = close > fast[-1] > slow[-1] and abs(close - slow[-1]) / close > 0.04
    signal_ts = ts(bars[-1])
    values = {
        "vwap":vwap_now,"extension_atr":ext,"prev_extension_atr":prev_ext,"rsi":r,
        "long_reclaim":long_reclaim,"short_reclaim":short_reclaim,
        "trend_veto_long":strong_down,"trend_veto_short":strong_up,
    }
    body = {"strategy_id":"vwap_revert","symbol":symbol,"signal_ts":signal_ts,"close":close,"atr":a,"values":values}
    return FeatureSnapshot("vwap_revert", symbol, signal_ts, _fresh(signal_ts, now_ts_ms, cfg), close, a, values, digest(body))


def compute_bb_revert_feature(bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
                              config: CommonPolicyConfig | None = None) -> FeatureSnapshot:
    cfg = config or CommonPolicyConfig()
    closes, _, _, a, fast, slow = _base_arrays(bars, cfg)
    mid = sma(closes, 20)
    sigma = stdev(closes, 20)
    upper, lower = mid + 2.0 * sigma, mid - 2.0 * sigma
    prev_mid = sma(closes[:-1], 20)
    prev_sigma = stdev(closes[:-1], 20)
    prev_upper, prev_lower = prev_mid + 2.0 * prev_sigma, prev_mid - 2.0 * prev_sigma
    close, prev = closes[-1], closes[-2]
    r = rsi(closes, 14)
    long_reclaim = prev < prev_lower and close > lower and r <= 42.0
    short_reclaim = prev > prev_upper and close < upper and r >= 58.0
    trend_veto_long = close < fast[-1] < slow[-1] and abs(close - slow[-1]) / close > 0.04
    trend_veto_short = close > fast[-1] > slow[-1] and abs(close - slow[-1]) / close > 0.04
    band_width_atr = (upper - lower) / a
    signal_ts = ts(bars[-1])
    values = {
        "mid":mid,"upper":upper,"lower":lower,"rsi":r,
        "long_reclaim":long_reclaim,"short_reclaim":short_reclaim,
        "trend_veto_long":trend_veto_long,"trend_veto_short":trend_veto_short,
        "band_width_atr":band_width_atr,
    }
    body = {"strategy_id":"bb_revert","symbol":symbol,"signal_ts":signal_ts,"close":close,"atr":a,"values":values}
    return FeatureSnapshot("bb_revert", symbol, signal_ts, _fresh(signal_ts, now_ts_ms, cfg), close, a, values, digest(body))


def _build(feature: FeatureSnapshot, *, policy_source_sha: str, verified_round_trip_cost_bps: float,
           config: CommonPolicyConfig | None = None) -> DecisionIntent:
    cfg = config or CommonPolicyConfig()
    validate_authority(policy_source_sha=policy_source_sha, verified_round_trip_cost_bps=verified_round_trip_cost_bps)
    strategy_id = feature.strategy_id
    policy_schema = f"zel.{strategy_id}.policy.v1"
    entry_rule = {
        "anchor_vwap_trend":"closed_bar_anchored_vwap_reclaim_with_ema_trend_alignment",
        "vwap_revert":"closed_bar_vwap_extension_reclaim_with_rsi_and_trend_veto",
        "bb_revert":"closed_bar_bollinger_reentry_with_rsi_and_trend_veto",
    }[strategy_id]
    strength_norm = "distance_or_extension_over_atr_clipped_0_3_then_divide_3"
    if not feature.fresh:
        return hold_intent(strategy_id=strategy_id, policy_schema=policy_schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[strategy_id],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization=strength_norm, regime="NO_TRADE_STALE", reasons=("STALE_SOURCE_FAIL_CLOSED",),
                           verified_cost_bps=verified_round_trip_cost_bps, timeout_bars=cfg.timeout_bars,
                           risk_fraction=cfg.risk_fraction_of_equity, exposure_cap=cfg.max_notional_fraction_of_equity)

    v = feature.values
    if strategy_id == "anchor_vwap_trend":
        long_ok = bool(v["long_cross"] and v["trend_long"] and 0.0 < v["dist_long_atr"] <= 1.25)
        short_ok = bool(v["short_cross"] and v["trend_short"] and 0.0 < v["dist_short_atr"] <= 1.25)
        target = None
        strength_raw = max(float(v["dist_long_atr"]), float(v["dist_short_atr"]), 0.0)
        regime = "TREND_RECLAIM_ALIGNED"
    elif strategy_id == "vwap_revert":
        long_ok = bool(v["long_reclaim"] and not v["trend_veto_long"])
        short_ok = bool(v["short_reclaim"] and not v["trend_veto_short"])
        target = float(v["vwap"])
        strength_raw = abs(float(v["prev_extension_atr"]))
        regime = "MEAN_REVERSION_EXTENSION_RECLAIM"
    else:
        long_ok = bool(v["long_reclaim"] and not v["trend_veto_long"] and float(v["band_width_atr"]) >= 1.0)
        short_ok = bool(v["short_reclaim"] and not v["trend_veto_short"] and float(v["band_width_atr"]) >= 1.0)
        target = float(v["mid"])
        strength_raw = max(1.0, float(v["band_width_atr"]) / 2.0)
        regime = "RANGE_REENTRY_NON_TREND"

    if long_ok == short_ok:
        return hold_intent(strategy_id=strategy_id, policy_schema=policy_schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[strategy_id],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization=strength_norm, regime="NO_TRADE", reasons=("NO_UNAMBIGUOUS_ENTRY",),
                           verified_cost_bps=verified_round_trip_cost_bps, timeout_bars=cfg.timeout_bars,
                           risk_fraction=cfg.risk_fraction_of_equity, exposure_cap=cfg.max_notional_fraction_of_equity)

    side = "long" if long_ok else "short"
    entry = feature.close
    stop = entry - 1.25 * feature.atr if side == "long" else entry + 1.25 * feature.atr
    notional, risk_distance_bps = risk_geometry(entry=entry, stop=stop, risk_fraction=cfg.risk_fraction_of_equity,
                                                 exposure_cap=cfg.max_notional_fraction_of_equity)
    if target is None:
        move_budget_bps = risk_distance_bps * 2.0
        tp = None
        trailing = {"enabled":True,"type":"anchored_vwap_or_ema_structure"}
        runner = {"enabled":True,"take_profit_owned_by_policy":False}
    else:
        target_distance_bps = abs(target - entry) / entry * 10_000.0
        move_budget_bps = max(target_distance_bps, risk_distance_bps * 1.25)
        tp = target if ((side == "long" and target > entry) or (side == "short" and target < entry)) else None
        trailing = {"enabled":True,"type":"breakeven_after_half_mean_reversion"}
        runner = {"enabled":False}
    ratio = move_budget_bps / verified_round_trip_cost_bps
    if ratio < cfg.min_cost_budget_ratio:
        return hold_intent(strategy_id=strategy_id, policy_schema=policy_schema, source_sha=policy_source_sha,
                           config_sha=cfg.sha, feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[strategy_id],
                           symbol=feature.symbol, signal_ts=feature.signal_ts, entry_rule=entry_rule,
                           strength_normalization=strength_norm, regime="NO_TRADE_COST", reasons=("STRUCTURAL_COST_BUDGET_BELOW_MIN",),
                           verified_cost_bps=verified_round_trip_cost_bps, timeout_bars=cfg.timeout_bars,
                           risk_fraction=cfg.risk_fraction_of_equity, exposure_cap=cfg.max_notional_fraction_of_equity)

    strength = min(1.0, max(0.0, strength_raw) / 3.0)
    return DecisionIntent(
        schema_version=policy_schema, strategy_id=strategy_id, source_sha=policy_source_sha, config_sha=cfg.sha,
        feature_sha=feature.feature_sha, evidence_ids=EVIDENCE[strategy_id], symbol=feature.symbol, side=side,
        signal_ts=feature.signal_ts, entry_rule=entry_rule, entry_strength=strength,
        strength_normalization=strength_norm, regime=regime, no_trade=False,
        invalidation={"initial_stop":stop,"hard_no_adverse_add":True},
        risk_size={"risk_fraction_of_equity":cfg.risk_fraction_of_equity,"risk_distance_bps":risk_distance_bps},
        exposure={"notional_fraction_of_equity":notional,"cap":cfg.max_notional_fraction_of_equity},
        sl=stop, tp=tp, timeout={"bars":cfg.timeout_bars}, partial={"enabled":False}, trailing=trailing,
        runner=runner, pyramiding={"enabled":False,"adverse_add":False}, cooldown={"bars":2,"one_entry_per_transition":True},
        turnover={"duplicate_transition_forbidden":True,"max_new_entries_per_bar":1}, reason_codes=("ENTRY_POLICY_PASS",),
        verified_round_trip_cost_bps=float(verified_round_trip_cost_bps), move_budget_bps=move_budget_bps,
        cost_budget_ratio=ratio,
    )


def build_anchor_vwap_trend_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "anchor_vwap_trend":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)


def build_vwap_revert_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "vwap_revert":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)


def build_bb_revert_intent(feature: FeatureSnapshot, **kwargs: Any) -> DecisionIntent:
    if feature.strategy_id != "bb_revert":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return _build(feature, **kwargs)


__all__ = [
    "CommonPolicyConfig", "FeatureSnapshot", "compute_anchor_vwap_trend_feature", "compute_vwap_revert_feature",
    "compute_bb_revert_feature", "build_anchor_vwap_trend_intent", "build_vwap_revert_intent", "build_bb_revert_intent",
    "control_direction_flip", "control_time_placebo", "control_delayed_entry", "evaluator_adapter_sha",
]

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from math import sqrt
from typing import Any, Mapping, Sequence


STRATEGY_ID = "bb_revert"
FEATURE_SCHEMA_VERSION = "zel.bb_revert.features.v2"
POLICY_SCHEMA_VERSION = "zel.bb_revert.policy.v2"
EVIDENCE_IDS = (
    "ARXIV_1212.4890",
    "LEDGER_2021_213",
    "SSRN_5775962",
    "BINGX_PERP_FEE_VIP0",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BbRevertPolicyConfig:
    timeframe_ms: int = 3_600_000
    mean_len: int = 20
    band_std_mult: float = 2.0
    atr_len: int = 14
    trend_len: int = 55
    max_abs_trend_slope_atr: float = 0.18
    max_stale_intervals: int = 2
    stop_atr_mult: float = 0.75
    timeout_bars: int = 8
    cooldown_bars: int = 2
    risk_fraction_of_equity: float = 0.005
    max_notional_fraction_of_equity: float = 0.15
    min_cost_budget_ratio: float = 1.5

    def validate(self) -> None:
        if min(self.timeframe_ms, self.mean_len, self.atr_len, self.trend_len, self.max_stale_intervals, self.timeout_bars, self.cooldown_bars) <= 0:
            raise ValueError("CONFIG_POSITIVE_REQUIRED")
        if self.band_std_mult <= 0 or self.stop_atr_mult <= 0:
            raise ValueError("CONFIG_GEOMETRY_INVALID")
        if not 0 < self.risk_fraction_of_equity <= 0.02:
            raise ValueError("CONFIG_RISK_FRACTION_INVALID")
        if not 0 < self.max_notional_fraction_of_equity <= 1:
            raise ValueError("CONFIG_EXPOSURE_CAP_INVALID")
        if self.min_cost_budget_ratio < 1:
            raise ValueError("CONFIG_COST_BUDGET_INVALID")

    @property
    def warmup_bars(self) -> int:
        return max(self.mean_len + 3, self.atr_len + 3, self.trend_len + 3)

    @property
    def sha(self) -> str:
        return _sha(asdict(self))


@dataclass(frozen=True)
class FeatureSnapshot:
    schema_version: str
    symbol: str
    signal_ts: int
    timeframe_ms: int
    close: float
    prev_close: float
    mean: float
    prev_mean: float
    std: float
    upper: float
    lower: float
    prev_upper: float
    prev_lower: float
    atr: float
    trend_slope_atr: float
    prev_z: float
    z: float
    reclaim_long: bool
    reclaim_short: bool
    non_trending: bool
    excursion_low: float
    excursion_high: float
    fresh: bool
    feature_sha: str


@dataclass(frozen=True)
class DecisionIntent:
    schema_version: str
    strategy_id: str
    source_sha: str
    config_sha: str
    feature_sha: str
    evidence_ids: tuple[str, ...]
    symbol: str
    side: str
    signal_ts: int
    entry_rule: str
    entry_strength: float
    strength_normalization: str
    regime: str
    no_trade: bool
    invalidation: Mapping[str, Any]
    risk_size: Mapping[str, Any]
    exposure: Mapping[str, Any]
    sl: float | None
    tp: float | None
    timeout: Mapping[str, Any]
    partial: Mapping[str, Any]
    trailing: Mapping[str, Any]
    runner: Mapping[str, Any]
    pyramiding: Mapping[str, Any]
    cooldown: Mapping[str, Any]
    turnover: Mapping[str, Any]
    reason_codes: tuple[str, ...]
    verified_round_trip_cost_bps: float
    move_budget_bps: float
    cost_budget_ratio: float

    @property
    def sha(self) -> str:
        return _sha(_jsonable(asdict(self)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_jsonable(x) for x in value]
    if isinstance(value, list):
        return [_jsonable(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def _float(bar: Mapping[str, Any], key: str) -> float:
    try:
        value = float(bar[key])
    except Exception as exc:
        raise ValueError(f"BAR_FIELD_INVALID:{key}") from exc
    if not (value == value) or value <= 0:
        raise ValueError(f"BAR_FIELD_NONPOSITIVE_OR_NAN:{key}")
    return value


def _ts(bar: Mapping[str, Any]) -> int:
    try:
        return int(bar["ts_ms"])
    except Exception as exc:
        raise ValueError("BAR_TS_INVALID") from exc


def _validate_bars(bars: Sequence[Mapping[str, Any]], cfg: BbRevertPolicyConfig) -> None:
    if len(bars) < cfg.warmup_bars:
        raise ValueError("WARMUP_INSUFFICIENT")
    last_ts: int | None = None
    for bar in bars:
        ts = _ts(bar)
        if last_ts is not None and ts <= last_ts:
            raise ValueError("BAR_TS_NON_MONOTONIC_OR_DUPLICATE")
        o, h, l, c = (_float(bar, k) for k in ("open", "high", "low", "close"))
        if h < max(o, c) or l > min(o, c) or h < l:
            raise ValueError("BAR_OHLC_INTEGRITY_FAIL")
        last_ts = ts


def _sma(values: Sequence[float], length: int, end_exclusive: int | None = None) -> float:
    seq = values if end_exclusive is None else values[:end_exclusive]
    window = seq[-length:]
    if len(window) != length:
        raise ValueError("WINDOW_INSUFFICIENT")
    return sum(window) / length


def _std(values: Sequence[float], length: int, end_exclusive: int | None = None) -> float:
    seq = values if end_exclusive is None else values[:end_exclusive]
    window = seq[-length:]
    if len(window) != length:
        raise ValueError("WINDOW_INSUFFICIENT")
    mean = sum(window) / length
    variance = sum((x - mean) ** 2 for x in window) / length
    return sqrt(variance)


def _ema(values: Sequence[float], length: int) -> list[float]:
    alpha = 2.0 / (length + 1.0)
    out: list[float] = []
    current = values[0]
    out.append(current)
    for value in values[1:]:
        current = alpha * value + (1.0 - alpha) * current
        out.append(current)
    return out


def _true_ranges(bars: Sequence[Mapping[str, Any]]) -> list[float]:
    out: list[float] = []
    prev_close: float | None = None
    for bar in bars:
        h, l, c = (_float(bar, k) for k in ("high", "low", "close"))
        out.append(h - l if prev_close is None else max(h - l, abs(h - prev_close), abs(l - prev_close)))
        prev_close = c
    return out


def _wilder_atr(trs: Sequence[float], length: int) -> float:
    if len(trs) < length:
        raise ValueError("ATR_UNAVAILABLE")
    current = sum(trs[:length]) / length
    for value in trs[length:]:
        current = ((length - 1) * current + value) / length
    if current <= 0:
        raise ValueError("ATR_UNAVAILABLE")
    return current


def compute_feature_snapshot(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: BbRevertPolicyConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or BbRevertPolicyConfig()
    cfg.validate()
    _validate_bars(bars, cfg)
    closes = [_float(b, "close") for b in bars]
    lows = [_float(b, "low") for b in bars]
    highs = [_float(b, "high") for b in bars]
    close = closes[-1]
    prev_close = closes[-2]
    mean = _sma(closes, cfg.mean_len)
    prev_mean = _sma(closes, cfg.mean_len, -1)
    std = _std(closes, cfg.mean_len)
    prev_std = _std(closes, cfg.mean_len, -1)
    if std <= 0 or prev_std <= 0:
        raise ValueError("VARIANCE_UNAVAILABLE")
    upper = mean + cfg.band_std_mult * std
    lower = mean - cfg.band_std_mult * std
    prev_upper = prev_mean + cfg.band_std_mult * prev_std
    prev_lower = prev_mean - cfg.band_std_mult * prev_std
    atr = _wilder_atr(_true_ranges(bars), cfg.atr_len)
    trend = _ema(closes, cfg.trend_len)
    trend_slope_atr = (trend[-1] - trend[-2]) / atr
    prev_z = (prev_close - prev_mean) / prev_std
    z = (close - mean) / std
    reclaim_long = prev_close < prev_lower and close > lower and close > prev_close
    reclaim_short = prev_close > prev_upper and close < upper and close < prev_close
    non_trending = abs(trend_slope_atr) <= cfg.max_abs_trend_slope_atr
    signal_ts = _ts(bars[-1])
    fresh = 0 <= int(now_ts_ms) - signal_ts <= cfg.max_stale_intervals * cfg.timeframe_ms
    raw = {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "symbol": symbol,
        "signal_ts": signal_ts,
        "timeframe_ms": cfg.timeframe_ms,
        "close": close,
        "prev_close": prev_close,
        "mean": mean,
        "prev_mean": prev_mean,
        "std": std,
        "upper": upper,
        "lower": lower,
        "prev_upper": prev_upper,
        "prev_lower": prev_lower,
        "atr": atr,
        "trend_slope_atr": trend_slope_atr,
        "prev_z": prev_z,
        "z": z,
        "reclaim_long": reclaim_long,
        "reclaim_short": reclaim_short,
        "non_trending": non_trending,
        "excursion_low": min(lows[-2:]),
        "excursion_high": max(highs[-2:]),
        "fresh": fresh,
    }
    return FeatureSnapshot(**raw, feature_sha=_sha(raw))


def build_decision_intent(
    feature: FeatureSnapshot,
    *,
    policy_source_sha: str,
    verified_round_trip_cost_bps: float,
    config: BbRevertPolicyConfig | None = None,
) -> DecisionIntent:
    cfg = config or BbRevertPolicyConfig()
    cfg.validate()
    if verified_round_trip_cost_bps <= 0:
        raise ValueError("VERIFIED_COST_AUTHORITY_REQUIRED")
    side = "none"
    reasons: list[str] = []
    if feature.reclaim_long:
        side = "long"
    elif feature.reclaim_short:
        side = "short"
    else:
        reasons.append("NO_CONFIRMED_RECLAIM")
    if not feature.fresh:
        reasons.append("STALE_SOURCE_FAIL_CLOSED")
    if not feature.non_trending:
        reasons.append("TREND_REGIME_BLOCK")
    move_budget_bps = abs(feature.mean - feature.close) / feature.close * 10_000.0
    cost_budget_ratio = move_budget_bps / verified_round_trip_cost_bps
    if cost_budget_ratio < cfg.min_cost_budget_ratio:
        reasons.append("STRUCTURAL_COST_BUDGET_BELOW_MIN")
    no_trade = bool(reasons) or side == "none"
    if side == "long":
        sl = min(feature.excursion_low, feature.close - cfg.stop_atr_mult * feature.atr)
        tp = feature.mean if feature.mean > feature.close else None
        strength = max(0.0, -feature.prev_z)
    elif side == "short":
        sl = max(feature.excursion_high, feature.close + cfg.stop_atr_mult * feature.atr)
        tp = feature.mean if feature.mean < feature.close else None
        strength = max(0.0, feature.prev_z)
    else:
        sl = None
        tp = None
        strength = 0.0
    if side != "none" and tp is None:
        reasons.append("MEAN_TARGET_NOT_FAVORABLE")
        no_trade = True
    risk_distance = abs(feature.close - sl) if sl is not None else 0.0
    risk_size = {
        "mode": "fixed_fraction_by_stop_distance",
        "risk_fraction_of_equity": cfg.risk_fraction_of_equity,
        "risk_distance_price": risk_distance,
    }
    return DecisionIntent(
        schema_version=POLICY_SCHEMA_VERSION,
        strategy_id=STRATEGY_ID,
        source_sha=str(policy_source_sha),
        config_sha=cfg.sha,
        feature_sha=feature.feature_sha,
        evidence_ids=EVIDENCE_IDS,
        symbol=feature.symbol,
        side=side,
        signal_ts=feature.signal_ts,
        entry_rule="previous_closed_bar_outside_2sigma_then_current_closed_bar_reclaims_inside",
        entry_strength=float(strength),
        strength_normalization="absolute_previous_standardized_deviation",
        regime="non_trending_local_equilibrium" if feature.non_trending else "directional_blocked",
        no_trade=no_trade,
        invalidation={"mode": "excursion_extreme_or_atr", "stop_atr_mult": cfg.stop_atr_mult},
        risk_size=risk_size,
        exposure={"max_notional_fraction_of_equity": cfg.max_notional_fraction_of_equity},
        sl=sl,
        tp=tp,
        timeout={"bars": cfg.timeout_bars, "reason": "reversion_decay"},
        partial={"enabled": False},
        trailing={"enabled": False},
        runner={"enabled": False},
        pyramiding={"enabled": False, "profitable_only": False, "adverse_add": False},
        cooldown={"bars": cfg.cooldown_bars},
        turnover={"new_intent_per_reclaim_event": 1},
        reason_codes=tuple(reasons or ["CONFIRMED_RECLAIM_NON_TRENDING_COST_OK"]),
        verified_round_trip_cost_bps=float(verified_round_trip_cost_bps),
        move_budget_bps=float(move_budget_bps),
        cost_budget_ratio=float(cost_budget_ratio),
    )


def evaluator_adapter_sha(intent: DecisionIntent) -> str:
    return _sha(_jsonable(asdict(intent)))


def direction_flip_control(intent: DecisionIntent) -> DecisionIntent:
    side = "short" if intent.side == "long" else "long" if intent.side == "short" else intent.side
    return replace(intent, side=side, reason_codes=intent.reason_codes + ("CONTROL_DIRECTION_FLIP",))


def time_placebo_control(intent: DecisionIntent, offset_ms: int) -> DecisionIntent:
    return replace(intent, signal_ts=intent.signal_ts + int(offset_ms), reason_codes=intent.reason_codes + ("CONTROL_TIME_PLACEBO",))


def regime_permutation_control(intent: DecisionIntent) -> DecisionIntent:
    regime = "directional_blocked" if intent.regime == "non_trending_local_equilibrium" else "non_trending_local_equilibrium"
    return replace(intent, regime=regime, reason_codes=intent.reason_codes + ("CONTROL_REGIME_PERMUTATION",))


def delayed_entry_control(intent: DecisionIntent, bars: int, timeframe_ms: int) -> DecisionIntent:
    return replace(intent, signal_ts=intent.signal_ts + int(bars) * int(timeframe_ms), reason_codes=intent.reason_codes + ("CONTROL_DELAYED_ENTRY",))

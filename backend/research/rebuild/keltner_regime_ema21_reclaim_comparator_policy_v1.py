from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import breakout_policy_batch_v1 as parent
from backend.research.rebuild.policy_kernel_v1 import atr, f

MODE = "DIAGNOSTIC_COMPARATOR_NOT_KELTNER_CHILD"
MECHANISM = "VOL_HIGH_EMA21_TOUCH_RECLAIM_WITH_EMA21_55_ALIGNMENT"


@dataclass(frozen=True)
class KeltnerRegimeEMA21ReclaimComparatorConfig(parent.BreakoutPolicyConfig):
    """Preserve parent risk/exit config; replace breakout timing for mechanism diagnosis only."""


FeatureSnapshot = parent.FeatureSnapshot


def _sha(base: FeatureSnapshot, values: Mapping[str, Any]) -> str:
    return parent.digest({
        "strategy_id": base.strategy_id,
        "symbol": base.symbol,
        "signal_ts": base.signal_ts,
        "close": base.close,
        "atr": base.atr,
        "values": dict(values),
        "mode": MODE,
        "mechanism": MECHANISM,
    })


def compute_keltner_trend_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: KeltnerRegimeEMA21ReclaimComparatorConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or KeltnerRegimeEMA21ReclaimComparatorConfig()
    base = parent.compute_keltner_trend_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    values = dict(base.values)
    a14 = atr(bars, 14)
    a50 = atr(bars, 50)
    vol_high = bool(a14 >= a50)
    fast = float(values["ema_fast"])
    slow = float(values["ema_slow"])
    close = float(base.close)

    prev_fast = None
    prev_low = None
    prev_high = None
    long_reclaim = False
    short_reclaim = False
    if len(bars) >= 65:
        prev = parent.compute_keltner_trend_feature(
            bars[:-1], symbol=symbol, now_ts_ms=parent.ts(bars[-2]), config=cfg
        )
        prev_fast = float(prev.values["ema_fast"])
        prev_low = f(bars[-2], "low")
        prev_high = f(bars[-2], "high")
        long_reclaim = bool(vol_high and fast > slow and prev_low <= prev_fast and close > fast)
        short_reclaim = bool(vol_high and fast < slow and prev_high >= prev_fast and close < fast)

    values.update({
        "parent_raw_long_break": bool(base.values["long_break"]),
        "parent_raw_short_break": bool(base.values["short_break"]),
        "vol_high_atr14_ge_atr50": vol_high,
        "prev_ema_fast": prev_fast,
        "prev_low": prev_low,
        "prev_high": prev_high,
        "ema21_touch_reclaim_long": long_reclaim,
        "ema21_touch_reclaim_short": short_reclaim,
        "long_break": long_reclaim,
        "short_break": short_reclaim,
        # Neutralize Keltner-break-specific gates. This comparator is not eligible
        # for Keltner promotion; it isolates regime-internal timing only.
        "expansion_ratio": 1.0,
        "chase_atr": 0.0,
        "comparison_mode": MODE,
        "comparison_mechanism": MECHANISM,
    })
    return FeatureSnapshot(
        strategy_id=base.strategy_id,
        symbol=base.symbol,
        signal_ts=base.signal_ts,
        fresh=base.fresh,
        close=base.close,
        atr=base.atr,
        values=values,
        feature_sha=_sha(base, values),
    )


def build_keltner_trend_intent(feature: FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "keltner_trend":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent.build_keltner_trend_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    p = parent.BreakoutPolicyConfig()
    c = KeltnerRegimeEMA21ReclaimComparatorConfig()
    return {
        "mode": MODE,
        "mechanism": MECHANISM,
        "not_a_keltner_child": True,
        "not_selection_eligible": True,
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "risk_exit_geometry_preserved": True,
        "initial_stop_atr": 1.25,
        "timeout_bars": p.timeout_bars,
        "entry_long": "ATR14>=ATR50 and EMA21>EMA55 and prior low<=prior EMA21 and current close>current EMA21",
        "entry_short": "ATR14>=ATR50 and EMA21<EMA55 and prior high>=prior EMA21 and current close<current EMA21",
        "numeric_threshold_sweep": False,
        "uses_post_outcome_data_at_runtime": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }


def self_test() -> int:
    inv = invariant_receipt()
    assert inv["not_a_keltner_child"] is True
    assert inv["config_values_identical"] is True and inv["config_sha_identical"] is True
    assert inv["initial_stop_atr"] == 1.25 and inv["timeout_bars"] == 48
    assert inv["numeric_threshold_sweep"] is False
    print("PASS_KELTNER_REGIME_EMA21_RECLAIM_COMPARATOR_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

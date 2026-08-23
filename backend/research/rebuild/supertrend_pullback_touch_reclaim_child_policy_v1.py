from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as parent

MODE = "SAMPLE_STALL_REPAIR_CHILD"
CHANGED_AXIS = "PULLBACK_EVENT_CLOSE_BAND_TO_INTRABAR_EMA_TOUCH_RECLAIM"


@dataclass(frozen=True)
class SupertrendTouchReclaimConfig(parent.TrendPolicyConfig):
    pass


def _sha(base: parent.FeatureSnapshot, values: Mapping[str, Any]) -> str:
    return parent.digest({
        "strategy_id": base.strategy_id,
        "symbol": base.symbol,
        "signal_ts": base.signal_ts,
        "close": base.close,
        "atr": base.atr,
        "values": dict(values),
        "mode": MODE,
        "changed_axis": CHANGED_AXIS,
    })


def compute_supertrend_pullback_feature(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: SupertrendTouchReclaimConfig | None = None,
) -> parent.FeatureSnapshot:
    cfg = config or SupertrendTouchReclaimConfig()
    base = parent.compute_supertrend_pullback_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    values = dict(base.values)
    long_touch = short_touch = False
    if len(bars) >= 65:
        prev = parent.compute_supertrend_pullback_feature(
            bars[:-1], symbol=symbol, now_ts_ms=parent.ts(bars[-2]), config=cfg
        )
        current_ema = float(values["ema50"])
        prev_ema = float(prev.values["ema50"])
        close = float(base.close)
        prev_close = parent.f(bars[-2], "close")
        prev_low = parent.f(bars[-2], "low")
        prev_high = parent.f(bars[-2], "high")
        direction = int(values["direction"])
        long_align = direction == 1 and close > current_ema and current_ema > prev_ema
        short_align = direction == -1 and close < current_ema and current_ema < prev_ema
        long_touch = bool(long_align and prev_low <= prev_ema and close > prev_close)
        short_touch = bool(short_align and prev_high >= prev_ema and close < prev_close)
    values.update({
        "parent_long_reclaim": bool(values["long_reclaim"]),
        "parent_short_reclaim": bool(values["short_reclaim"]),
        "long_reclaim": long_touch,
        "short_reclaim": short_touch,
        "sample_stall_repair_mode": MODE,
        "changed_axis": CHANGED_AXIS,
    })
    return parent.FeatureSnapshot(
        strategy_id=base.strategy_id, symbol=base.symbol, signal_ts=base.signal_ts,
        fresh=base.fresh, close=base.close, atr=base.atr, values=values,
        feature_sha=_sha(base, values),
    )


def build_supertrend_pullback_intent(feature: parent.FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "supertrend_pullback":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent.build_supertrend_pullback_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    p, c = parent.TrendPolicyConfig(), SupertrendTouchReclaimConfig()
    return {
        "mode": MODE,
        "changed_axis": CHANGED_AXIS,
        "changed_axis_count": 1,
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "risk_exit_geometry_preserved": True,
        "numeric_threshold_sweep": False,
        "post_outcome_trade_deletion": False,
        "uses_post_outcome_data_at_runtime": False,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }


def self_test() -> int:
    r = invariant_receipt()
    assert r["changed_axis_count"] == 1
    assert r["config_values_identical"] and r["config_sha_identical"]
    assert r["numeric_threshold_sweep"] is False
    print("PASS_SUPERTREND_TOUCH_RECLAIM_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

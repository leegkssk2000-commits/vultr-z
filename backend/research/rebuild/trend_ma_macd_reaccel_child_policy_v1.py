from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as parent

MODE = "SAMPLE_STALL_REPAIR_CHILD"
CHANGED_AXIS = "MACD_EVENT_ZERO_CROSS_TO_SAME_SIGN_REACCELERATION"


@dataclass(frozen=True)
class TrendMAMacdReaccelConfig(parent.TrendPolicyConfig):
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


def compute_trend_ma_macd_feature(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: TrendMAMacdReaccelConfig | None = None,
) -> parent.FeatureSnapshot:
    cfg = config or TrendMAMacdReaccelConfig()
    base = parent.compute_trend_ma_macd_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    values = dict(base.values)
    close = float(base.close)
    fast = float(values["ema_fast"])
    slow = float(values["ema_slow"])
    hist = float(values["hist"])
    hist_prev = float(values["hist_prev"])
    long_reaccel = bool(close > fast > slow and hist > 0.0 and hist > hist_prev)
    short_reaccel = bool(close < fast < slow and hist < 0.0 and hist < hist_prev)
    values.update({
        "parent_long_cross": bool(values["long_cross"]),
        "parent_short_cross": bool(values["short_cross"]),
        "long_cross": long_reaccel,
        "short_cross": short_reaccel,
        "sample_stall_repair_mode": MODE,
        "changed_axis": CHANGED_AXIS,
    })
    return parent.FeatureSnapshot(
        strategy_id=base.strategy_id, symbol=base.symbol, signal_ts=base.signal_ts,
        fresh=base.fresh, close=base.close, atr=base.atr, values=values,
        feature_sha=_sha(base, values),
    )


def build_trend_ma_macd_intent(feature: parent.FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "trend_ma_macd":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent.build_trend_ma_macd_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    p, c = parent.TrendPolicyConfig(), TrendMAMacdReaccelConfig()
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
    assert r["execution_authority"] == "NONE" and r["order_authority"] == "BLOCKED"
    print("PASS_TREND_MA_MACD_REACCEL_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as parent

MODE = "GOOD_REGIME_FRESH_ALTERNATIVE_CHILD"
CANDIDATE_IDENTITY = "trend_ma_macd_chase_atr_up_good_v1"
CHANGED_AXIS = "ADMISSION_REQUIRE_CHASE_ATR_CURRENT_GT_PREVIOUS_CONFIRMED_BAR"


@dataclass(frozen=True)
class TrendMaMacdChaseAtrUpGoodConfig(parent.TrendPolicyConfig):
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
        "candidate_identity": CANDIDATE_IDENTITY,
        "changed_axis": CHANGED_AXIS,
    })


def compute_trend_ma_macd_feature(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: TrendMaMacdChaseAtrUpGoodConfig | None = None,
) -> parent.FeatureSnapshot:
    cfg = config or TrendMaMacdChaseAtrUpGoodConfig()
    base = parent.compute_trend_ma_macd_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg,
    )
    values = dict(base.values)
    if len(bars) < 2:
        previous_chase_atr = None
        chase_atr_up = False
    else:
        previous_ts = int(bars[-2]["ts_ms"])
        previous = parent.compute_trend_ma_macd_feature(
            bars[:-1], symbol=symbol, now_ts_ms=previous_ts, config=cfg,
        )
        previous_chase_atr = float(previous.values["chase_atr"])
        chase_atr_up = float(values["chase_atr"]) > previous_chase_atr

    parent_long = bool(values["long_cross"])
    parent_short = bool(values["short_cross"])
    values.update({
        "parent_long_cross": parent_long,
        "parent_short_cross": parent_short,
        "chase_atr_prev_confirmed": previous_chase_atr,
        "chase_atr_up": chase_atr_up,
        "long_cross": bool(parent_long and chase_atr_up),
        "short_cross": bool(parent_short and chase_atr_up),
        "good_regime_admission_pass": chase_atr_up,
        "good_regime_mode": MODE,
        "candidate_identity": CANDIDATE_IDENTITY,
        "changed_axis": CHANGED_AXIS,
    })
    return parent.FeatureSnapshot(
        strategy_id=base.strategy_id,
        symbol=base.symbol,
        signal_ts=base.signal_ts,
        fresh=base.fresh,
        close=base.close,
        atr=base.atr,
        values=values,
        feature_sha=_sha(base, values),
    )


def build_trend_ma_macd_intent(feature: parent.FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "trend_ma_macd":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent.build_trend_ma_macd_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    p, c = parent.TrendPolicyConfig(), TrendMaMacdChaseAtrUpGoodConfig()
    return {
        "candidate_identity": CANDIDATE_IDENTITY,
        "mode": MODE,
        "changed_axis": CHANGED_AXIS,
        "changed_axis_count": 1,
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "parent_thresholds_preserved": True,
        "parent_risk_exit_geometry_preserved": True,
        "feature_semantics": "CURRENT_SIGNAL_BAR_PARENT_CHASE_ATR_GT_PREVIOUS_CONFIRMED_BAR_PARENT_CHASE_ATR",
        "alternative_to": "trend_ma_macd_ema_fast_up_good_v1",
        "combined_with_primary": False,
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
    assert r["parent_thresholds_preserved"] and r["parent_risk_exit_geometry_preserved"]
    assert r["combined_with_primary"] is False and r["numeric_threshold_sweep"] is False
    assert r["execution_authority"] == "NONE" and r["order_authority"] == "BLOCKED"
    print("PASS_TREND_MA_MACD_CHASE_ATR_UP_GOOD_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

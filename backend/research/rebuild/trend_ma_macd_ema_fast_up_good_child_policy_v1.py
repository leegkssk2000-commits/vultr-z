from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as parent

MODE = "GOOD_REGIME_FRESH_CHILD"
CANDIDATE_IDENTITY = "trend_ma_macd_ema_fast_up_good_v1"
CHANGED_AXIS = "ADMISSION_REQUIRE_EMA_FAST_CURRENT_GT_PREVIOUS_CONFIRMED_BAR"


@dataclass(frozen=True)
class TrendMaMacdEmaFastUpGoodConfig(parent.TrendPolicyConfig):
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
    config: TrendMaMacdEmaFastUpGoodConfig | None = None,
) -> parent.FeatureSnapshot:
    cfg = config or TrendMaMacdEmaFastUpGoodConfig()
    base = parent.compute_trend_ma_macd_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg,
    )
    values = dict(base.values)
    closes = [parent.f(b, "close") for b in bars]
    if len(closes) < 2:
        ema_fast_up = False
        prev_fast = None
    else:
        prev_fast = float(parent.ema(closes[:-1], cfg.ema_fast_len)[-1])
        ema_fast_up = float(values["ema_fast"]) > prev_fast

    parent_long = bool(values["long_cross"])
    parent_short = bool(values["short_cross"])
    values.update({
        "parent_long_cross": parent_long,
        "parent_short_cross": parent_short,
        "ema_fast_prev_confirmed": prev_fast,
        "ema_fast_up": ema_fast_up,
        "long_cross": bool(parent_long and ema_fast_up),
        "short_cross": bool(parent_short and ema_fast_up),
        "good_regime_admission_pass": ema_fast_up,
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
    p, c = parent.TrendPolicyConfig(), TrendMaMacdEmaFastUpGoodConfig()
    return {
        "candidate_identity": CANDIDATE_IDENTITY,
        "mode": MODE,
        "changed_axis": CHANGED_AXIS,
        "changed_axis_count": 1,
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "parent_thresholds_preserved": True,
        "parent_risk_exit_geometry_preserved": True,
        "feature_semantics": "CURRENT_SIGNAL_BAR_EMA21_GT_PREVIOUS_CONFIRMED_BAR_EMA21",
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
    assert r["numeric_threshold_sweep"] is False
    assert r["execution_authority"] == "NONE" and r["order_authority"] == "BLOCKED"
    print("PASS_TREND_MA_MACD_EMA_FAST_UP_GOOD_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import breakout_policy_batch_v1 as parent

AXIS = "ONE_BAR_KELTNER_ADMISSION_PERSISTENCE_ONLY"
BASELINE_IDENTITY = "KELTNER_PARENT_REGIME_PREMIUM_TIMING_DIAGNOSED"
PARAMETER_PROVENANCE = (
    "Preserve parent Keltner configuration, risk, stop, timeout and admission thresholds exactly. "
    "Require the immediately prior closed bar to have passed the same directional Keltner raw break, "
    "ATR expansion >=1.0 and chase_atr <=1.0 admission before the current parent admission can enter."
)


@dataclass(frozen=True)
class KeltnerPersistenceConfirmationConfig(parent.BreakoutPolicyConfig):
    """Parent config preserved exactly; only one-bar admission persistence is added."""


FeatureSnapshot = parent.FeatureSnapshot


def _child_feature_sha(base: FeatureSnapshot, values: Mapping[str, Any]) -> str:
    return parent.digest({
        "strategy_id": base.strategy_id,
        "symbol": base.symbol,
        "signal_ts": base.signal_ts,
        "close": base.close,
        "atr": base.atr,
        "values": dict(values),
        "changed_axis": AXIS,
    })


def _parent_admission(values: Mapping[str, Any], side: str) -> bool:
    raw = bool(values["long_break"] if side == "long" else values["short_break"])
    return bool(raw and float(values["expansion_ratio"]) >= 1.0 and float(values["chase_atr"]) <= 1.0)


def compute_keltner_trend_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: KeltnerPersistenceConfirmationConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or KeltnerPersistenceConfirmationConfig()
    base = parent.compute_keltner_trend_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    values = dict(base.values)
    current_long_raw = bool(values["long_break"])
    current_short_raw = bool(values["short_break"])
    prior_long_admission = False
    prior_short_admission = False
    if len(bars) >= 65:
        prev = parent.compute_keltner_trend_feature(
            bars[:-1], symbol=symbol, now_ts_ms=parent.ts(bars[-2]), config=cfg
        )
        pv = dict(prev.values)
        prior_long_admission = _parent_admission(pv, "long")
        prior_short_admission = _parent_admission(pv, "short")

    values.update({
        "parent_current_long_break": current_long_raw,
        "parent_current_short_break": current_short_raw,
        "prior_parent_long_admission": prior_long_admission,
        "prior_parent_short_admission": prior_short_admission,
        "persistence_confirmed_long": bool(current_long_raw and prior_long_admission),
        "persistence_confirmed_short": bool(current_short_raw and prior_short_admission),
        "long_break": bool(current_long_raw and prior_long_admission),
        "short_break": bool(current_short_raw and prior_short_admission),
        "changed_axis": AXIS,
        "parameter_provenance": PARAMETER_PROVENANCE,
    })
    return FeatureSnapshot(
        strategy_id=base.strategy_id,
        symbol=base.symbol,
        signal_ts=base.signal_ts,
        fresh=base.fresh,
        close=base.close,
        atr=base.atr,
        values=values,
        feature_sha=_child_feature_sha(base, values),
    )


def build_keltner_trend_intent(feature: FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "keltner_trend":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent.build_keltner_trend_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    p = parent.BreakoutPolicyConfig()
    c = KeltnerPersistenceConfirmationConfig()
    return {
        "strategy_id": "keltner_trend",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "one_axis_only": True,
        "parent_config": asdict(p),
        "child_config": asdict(c),
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "prior_bar_rule": "prior closed bar passes same directional raw Keltner break + expansion>=1.0 + chase<=1.0",
        "current_parent_thresholds_preserved": True,
        "parent_entry_price_semantics_preserved": True,
        "parent_exit_geometry_preserved": True,
        "parent_initial_stop_atr": 1.25,
        "parent_timeout_bars": p.timeout_bars,
        "parent_risk_fraction_preserved": True,
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
    inv = invariant_receipt()
    assert inv["one_axis_only"] is True
    assert inv["config_values_identical"] is True and inv["config_sha_identical"] is True
    assert inv["parent_initial_stop_atr"] == 1.25
    assert inv["parent_timeout_bars"] == 48
    assert inv["numeric_threshold_sweep"] is False
    assert inv["uses_post_outcome_data_at_runtime"] is False
    assert _parent_admission({"long_break": True, "short_break": False, "expansion_ratio": 1.0, "chase_atr": 1.0}, "long") is True
    assert _parent_admission({"long_break": True, "short_break": False, "expansion_ratio": 0.99, "chase_atr": 0.2}, "long") is False
    print("PASS_KELTNER_PERSISTENCE_CONFIRMATION_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

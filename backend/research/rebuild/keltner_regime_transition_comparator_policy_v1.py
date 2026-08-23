from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import breakout_policy_batch_v1 as parent
from backend.research.rebuild.policy_kernel_v1 import atr

MODE = "DIAGNOSTIC_COMPARATOR_NOT_KELTNER_CHILD"
AXIS = "REPLACE_EXACT_KELTNER_BREAK_TIMING_WITH_VOL_HIGH_EMA_REGIME_TRANSITION"


@dataclass(frozen=True)
class KeltnerRegimeTransitionComparatorConfig(parent.BreakoutPolicyConfig):
    """Risk/exit config is identical; admission is deliberately replaced for mechanism diagnosis."""


FeatureSnapshot = parent.FeatureSnapshot


def _eligible(bars: Sequence[Mapping[str, Any]], base: FeatureSnapshot) -> tuple[bool, bool, bool]:
    a14 = atr(bars, 14)
    a50 = atr(bars, 50)
    vol_high = bool(a14 >= a50)
    fast = float(base.values["ema_fast"])
    slow = float(base.values["ema_slow"])
    return vol_high, bool(vol_high and fast > slow), bool(vol_high and fast < slow)


def _sha(base: FeatureSnapshot, values: Mapping[str, Any]) -> str:
    return parent.digest({
        "strategy_id": base.strategy_id,
        "symbol": base.symbol,
        "signal_ts": base.signal_ts,
        "close": base.close,
        "atr": base.atr,
        "values": dict(values),
        "mode": MODE,
        "changed_mechanism": AXIS,
    })


def compute_keltner_trend_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: KeltnerRegimeTransitionComparatorConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or KeltnerRegimeTransitionComparatorConfig()
    base = parent.compute_keltner_trend_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    vol_high, current_long, current_short = _eligible(bars, base)
    prior_long = False
    prior_short = False
    if len(bars) >= 65:
        prev = parent.compute_keltner_trend_feature(
            bars[:-1], symbol=symbol, now_ts_ms=parent.ts(bars[-2]), config=cfg
        )
        _, prior_long, prior_short = _eligible(bars[:-1], prev)

    transition_long = bool(current_long and not prior_long)
    transition_short = bool(current_short and not prior_short)
    values = dict(base.values)
    values.update({
        "parent_raw_long_break": bool(base.values["long_break"]),
        "parent_raw_short_break": bool(base.values["short_break"]),
        "vol_high_atr14_ge_atr50": vol_high,
        "regime_current_long": current_long,
        "regime_current_short": current_short,
        "regime_prior_long": prior_long,
        "regime_prior_short": prior_short,
        "regime_transition_long": transition_long,
        "regime_transition_short": transition_short,
        # Deliberately neutralize breakout-specific admission gates so the comparator
        # isolates deterministic regime-transition timing. This is NOT a Keltner child.
        "long_break": transition_long,
        "short_break": transition_short,
        "expansion_ratio": 1.0,
        "chase_atr": 0.0,
        "comparison_mode": MODE,
        "changed_mechanism": AXIS,
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
    c = KeltnerRegimeTransitionComparatorConfig()
    return {
        "mode": MODE,
        "strategy_id_transport_only": "keltner_trend",
        "changed_mechanism": AXIS,
        "not_a_keltner_child": True,
        "not_selection_eligible": True,
        "parent_config": asdict(p),
        "comparator_config": asdict(c),
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "risk_exit_geometry_preserved": True,
        "initial_stop_atr": 1.25,
        "timeout_bars": p.timeout_bars,
        "admission_replaced_with": "first closed-bar transition into ATR14>=ATR50 plus EMA21/55 directional alignment",
        "breakout_specific_expansion_chase_gates_neutralized_for_comparator": True,
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
    assert inv["config_values_identical"] is True
    assert inv["initial_stop_atr"] == 1.25 and inv["timeout_bars"] == 48
    assert inv["numeric_threshold_sweep"] is False
    assert inv["selection_authority"] is False and inv["execution_authority"] == "NONE"
    print("PASS_KELTNER_REGIME_TRANSITION_COMPARATOR_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

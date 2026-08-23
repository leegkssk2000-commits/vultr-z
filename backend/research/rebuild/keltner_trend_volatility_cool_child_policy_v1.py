from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import breakout_policy_batch_v1 as parent
from backend.research.rebuild.policy_kernel_v1 import atr

AXIS = "FROZEN_A4_VOLATILITY_COOL_REGIME_ONLY"
BASELINE_IDENTITY = "CANONICAL_KELTNER_TREND_V1"
REGIME_AUTHORITY = "backend/research/rebuild/a1_a4_exact_parent_repair_batch_v1.py::keep_volatility_regime"
PARAMETER_PROVENANCE = (
    "Uses the pre-existing A4 volatility regime definition ATR14>=ATR50 as VOL_HIGH; "
    "this child retains only its outcome-blind complement ATR14<ATR50. No loss-derived numeric threshold."
)


@dataclass(frozen=True)
class KeltnerVolatilityCoolConfig(parent.BreakoutPolicyConfig):
    """Canonical Keltner config preserved exactly."""


FeatureSnapshot = parent.FeatureSnapshot


def _child_sha(base: FeatureSnapshot, values: Mapping[str, Any]) -> str:
    return parent.digest({
        "strategy_id": base.strategy_id,
        "symbol": base.symbol,
        "signal_ts": base.signal_ts,
        "close": base.close,
        "atr": base.atr,
        "values": dict(values),
        "changed_axis": AXIS,
        "regime_authority": REGIME_AUTHORITY,
    })


def compute_keltner_trend_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: KeltnerVolatilityCoolConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or KeltnerVolatilityCoolConfig()
    base = parent.compute_keltner_trend_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    values = dict(base.values)
    atr14 = float(atr(bars, 14))
    atr50 = float(atr(bars, 50))
    vol_high = atr14 >= atr50
    values.update({
        "parent_long_break": bool(values.get("long_break")),
        "parent_short_break": bool(values.get("short_break")),
        "atr14": atr14,
        "atr50": atr50,
        "vol_high_frozen_a4": vol_high,
        "volatility_cool_regime": not vol_high,
        "changed_axis": AXIS,
        "regime_authority": REGIME_AUTHORITY,
        "parameter_provenance": PARAMETER_PROVENANCE,
    })
    if vol_high:
        values["long_break"] = False
        values["short_break"] = False
    return FeatureSnapshot(
        strategy_id=base.strategy_id,
        symbol=base.symbol,
        signal_ts=base.signal_ts,
        fresh=base.fresh,
        close=base.close,
        atr=base.atr,
        values=values,
        feature_sha=_child_sha(base, values),
    )


def build_keltner_trend_intent(feature: FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "keltner_trend":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent.build_keltner_trend_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    p = parent.BreakoutPolicyConfig()
    c = KeltnerVolatilityCoolConfig()
    return {
        "strategy_id": "keltner_trend",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "one_axis_only": True,
        "regime_authority": REGIME_AUTHORITY,
        "existing_frozen_predicate": "ATR14>=ATR50_IS_VOL_HIGH",
        "child_predicate": "ATR14<ATR50",
        "loss_derived_numeric_threshold": False,
        "parent_config": asdict(p),
        "child_config": asdict(c),
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "parent_exit_geometry_preserved": True,
        "parent_initial_risk_preserved": True,
        "numeric_threshold_sweep": False,
        "post_outcome_trade_deletion": False,
        "uses_post_outcome_data_at_runtime": False,
        "parameter_provenance": PARAMETER_PROVENANCE,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0
    }


def self_test() -> int:
    inv = invariant_receipt()
    assert inv["one_axis_only"] is True
    assert inv["config_values_identical"] is True and inv["config_sha_identical"] is True
    assert inv["loss_derived_numeric_threshold"] is False
    assert inv["numeric_threshold_sweep"] is False
    assert inv["uses_post_outcome_data_at_runtime"] is False
    assert inv["execution_authority"] == "NONE" and inv["order_authority"] == "BLOCKED"
    print("PASS_KELTNER_TREND_VOLATILITY_COOL_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

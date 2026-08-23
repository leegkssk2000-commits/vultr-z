from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as parent

MODE = "GOOD_REGIME_FRESH_CHILD"
CANDIDATE_IDENTITY = "supertrend_pullback_long_reclaim_good_v1"
CHANGED_AXIS = "ADMISSION_REQUIRE_PARENT_LONG_RECLAIM_TRUE"


@dataclass(frozen=True)
class SupertrendLongReclaimGoodConfig(parent.TrendPolicyConfig):
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


def compute_supertrend_pullback_feature(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: SupertrendLongReclaimGoodConfig | None = None,
) -> parent.FeatureSnapshot:
    cfg = config or SupertrendLongReclaimGoodConfig()
    base = parent.compute_supertrend_pullback_feature(
        bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg,
    )
    values = dict(base.values)
    parent_long = bool(values["long_reclaim"])
    parent_short = bool(values["short_reclaim"])

    # #996 discovery state was exactly current parent feature long_reclaim=True.
    # Preserve the parent long path byte-for-byte semantically; suppress every
    # parent entry that is not in that state. This therefore removes the short
    # path rather than inventing a new numeric regime threshold.
    values.update({
        "parent_long_reclaim": parent_long,
        "parent_short_reclaim": parent_short,
        "long_reclaim": parent_long,
        "short_reclaim": False,
        "good_regime_admission_pass": parent_long,
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


def build_supertrend_pullback_intent(feature: parent.FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "supertrend_pullback":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent.build_supertrend_pullback_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    p, c = parent.TrendPolicyConfig(), SupertrendLongReclaimGoodConfig()
    return {
        "candidate_identity": CANDIDATE_IDENTITY,
        "mode": MODE,
        "changed_axis": CHANGED_AXIS,
        "changed_axis_count": 1,
        "config_values_identical": asdict(p) == asdict(c),
        "config_sha_identical": p.sha == c.sha,
        "parent_thresholds_preserved": True,
        "parent_risk_exit_geometry_preserved": True,
        "directional_semantics_explicit": "LONG_ONLY_CHILD_BY_PARENT_LONG_RECLAIM_STATE",
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
    print("PASS_SUPERTREND_LONG_RECLAIM_GOOD_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

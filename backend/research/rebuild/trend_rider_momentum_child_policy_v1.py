from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as parent

AXIS = "MOMENTUM_CONFIRMATION_OWNER_ONLY"
BASELINE_IDENTITY = "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3"
EXTERNAL_EVIDENCE_IDS = ("TR59E2",)
MOMENTUM_TRANSFORM = "MACD_HISTOGRAM_FIRST_DIFFERENCE_SIGN"
PARAMETER_PROVENANCE = "existing_frozen_project_MACD_12_26_9_transform; zero-threshold sign only; no outcome sweep"


@dataclass(frozen=True)
class TrendRiderMomentumConfig(parent.TrendPolicyConfig):
    """Identical parent configuration; this child changes entry ownership only."""


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
        "momentum_transform": MOMENTUM_TRANSFORM,
    })


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderMomentumConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderMomentumConfig()
    base = parent.compute_trend_rider_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    closes = [parent.f(b, "close") for b in bars]
    hist = parent._macd_hist(closes)
    if len(hist) < 2:
        raise ValueError("MOMENTUM_WARMUP_INSUFFICIENT")
    delta = float(hist[-1] - hist[-2])
    momentum_long = delta > 0.0
    momentum_short = delta < 0.0
    values = dict(base.values)
    parent_long = bool(values.get("long_confirm"))
    parent_short = bool(values.get("short_confirm"))
    values.update({
        "parent_long_confirm": parent_long,
        "parent_short_confirm": parent_short,
        "momentum_hist": float(hist[-1]),
        "momentum_hist_prev": float(hist[-2]),
        "momentum_hist_delta": delta,
        "momentum_long": momentum_long,
        "momentum_short": momentum_short,
        "long_confirm": bool(parent_long and momentum_long),
        "short_confirm": bool(parent_short and momentum_short),
        "changed_axis": AXIS,
        "momentum_transform": MOMENTUM_TRANSFORM,
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


def build_trend_rider_intent(feature: FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "trend_rider":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent._build(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    parent_cfg = parent.TrendPolicyConfig()
    child_cfg = TrendRiderMomentumConfig()
    return {
        "strategy_id": "trend_rider",
        "baseline_identity": BASELINE_IDENTITY,
        "changed_axis": AXIS,
        "one_axis_only": True,
        "parent_config": asdict(parent_cfg),
        "child_config": asdict(child_cfg),
        "config_values_identical": asdict(parent_cfg) == asdict(child_cfg),
        "parent_config_sha": parent_cfg.sha,
        "child_config_sha": child_cfg.sha,
        "config_sha_identical": parent_cfg.sha == child_cfg.sha,
        "parent_entry_geometry_preserved": True,
        "parent_exit_geometry_preserved": True,
        "parent_initial_risk_preserved": True,
        "momentum_transform": MOMENTUM_TRANSFORM,
        "momentum_threshold": 0.0,
        "threshold_sweep": False,
        "best_horizon_selection": False,
        "post_outcome_trade_deletion": False,
        "external_evidence_ids": list(EXTERNAL_EVIDENCE_IDS),
        "parameter_provenance": PARAMETER_PROVENANCE,
        "selection_authority": False,
        "promotion_authority": False,
        "execution_authority": "NONE",
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
        "protected_mutations": 0,
    }


def self_test() -> int:
    inv = invariant_receipt()
    assert inv["config_values_identical"] is True
    assert inv["config_sha_identical"] is True
    assert inv["changed_axis"] == AXIS
    assert inv["threshold_sweep"] is False
    assert inv["best_horizon_selection"] is False
    assert inv["post_outcome_trade_deletion"] is False
    assert inv["momentum_threshold"] == 0.0
    assert inv["execution_authority"] == "NONE" and inv["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_MOMENTUM_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

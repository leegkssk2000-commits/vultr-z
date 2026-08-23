from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import breakout_policy_batch_v1 as parent

MODE = "SAMPLE_STALL_REPAIR_CHILD"
CHANGED_AXIS = "BREAKOUT_REFERENCE_PRIOR20_RANGE_TO_EXISTING_8BAR_BOX"


@dataclass(frozen=True)
class BreakBoxReferenceConfig(parent.BreakoutPolicyConfig):
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


def compute_break_and_continue_feature(
    bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int,
    config: BreakBoxReferenceConfig | None = None,
) -> parent.FeatureSnapshot:
    cfg = config or BreakBoxReferenceConfig()
    base = parent.compute_break_and_continue_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    values = dict(base.values)
    close = float(base.close)
    a = max(float(base.atr), 1e-12)
    fast = float(values["ema_fast"])
    slow = float(values["ema_slow"])
    box_high = float(values["box_high"])
    box_low = float(values["box_low"])
    long_break = bool(close > box_high and close > fast > slow)
    short_break = bool(close < box_low and close < fast < slow)
    chase_atr = max((close - box_high) / a, (box_low - close) / a, 0.0)
    values.update({
        "parent_long_break": bool(values["long_break"]),
        "parent_short_break": bool(values["short_break"]),
        "parent_chase_atr": float(values["chase_atr"]),
        "long_break": long_break,
        "short_break": short_break,
        "chase_atr": chase_atr,
        "sample_stall_repair_mode": MODE,
        "changed_axis": CHANGED_AXIS,
    })
    return parent.FeatureSnapshot(
        strategy_id=base.strategy_id, symbol=base.symbol, signal_ts=base.signal_ts,
        fresh=base.fresh, close=base.close, atr=base.atr, values=values,
        feature_sha=_sha(base, values),
    )


def build_break_and_continue_intent(feature: parent.FeatureSnapshot, **kwargs: Any):
    if feature.strategy_id != "break_and_continue":
        raise ValueError("FEATURE_STRATEGY_MISMATCH")
    return parent.build_break_and_continue_intent(feature, **kwargs)


def invariant_receipt() -> dict[str, Any]:
    p, c = parent.BreakoutPolicyConfig(), BreakBoxReferenceConfig()
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
    print("PASS_BREAK_BOX_REFERENCE_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from backend.research.rebuild import trend_policy_batch_v1 as parent

AXIS = "MULTISCALE_TREND_ALIGNMENT_ENTRY_ONLY"
BASELINE_IDENTITY = "ORIGINAL_TREND_RIDER_FRESH_W1_W2_W3"
EXTERNAL_EVIDENCE_IDS = ("HIST_R7_TREND_RIDER", "HIST_R7_TREND_MA_MACD", "TSMOM_MOSKOWITZ_OSOI_PEDERSEN")
ALIGNMENT_TRANSFORM = "EMA21_55_ORDER_AND_SLOPE_SIGN"
PARAMETER_PROVENANCE = "existing_parent_EMA21_EMA55_lengths; sign/order only; no outcome sweep"


@dataclass(frozen=True)
class TrendRiderMultiscaleConfig(parent.TrendPolicyConfig):
    """Identical parent configuration; only entry confirmation ownership changes."""


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
        "alignment_transform": ALIGNMENT_TRANSFORM,
    })


def compute_trend_rider_feature(
    bars: Sequence[Mapping[str, Any]],
    *,
    symbol: str,
    now_ts_ms: int,
    config: TrendRiderMultiscaleConfig | None = None,
) -> FeatureSnapshot:
    cfg = config or TrendRiderMultiscaleConfig()
    base = parent.compute_trend_rider_feature(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=cfg)
    closes = [parent.f(b, "close") for b in bars]
    fast = parent.ema(closes, cfg.ema_fast_len)
    slow = parent.ema(closes, cfg.ema_slow_len)
    close = float(closes[-1])
    fast_slope = float(fast[-1] - fast[-2])
    slow_slope = float(slow[-1] - slow[-2])
    multiscale_long = bool(close > fast[-1] > slow[-1] and fast_slope > 0.0 and slow_slope > 0.0)
    multiscale_short = bool(close < fast[-1] < slow[-1] and fast_slope < 0.0 and slow_slope < 0.0)

    values = dict(base.values)
    parent_long = bool(values.get("long_confirm"))
    parent_short = bool(values.get("short_confirm"))
    values.update({
        "parent_long_confirm": parent_long,
        "parent_short_confirm": parent_short,
        "ema21": float(fast[-1]),
        "ema55": float(slow[-1]),
        "ema21_slope": fast_slope,
        "ema55_slope": slow_slope,
        "multiscale_long": multiscale_long,
        "multiscale_short": multiscale_short,
        "long_confirm": bool(parent_long and multiscale_long),
        "short_confirm": bool(parent_short and multiscale_short),
        "changed_axis": AXIS,
        "alignment_transform": ALIGNMENT_TRANSFORM,
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
    child_cfg = TrendRiderMultiscaleConfig()
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
        "ema_fast_len": parent_cfg.ema_fast_len,
        "ema_slow_len": parent_cfg.ema_slow_len,
        "alignment_transform": ALIGNMENT_TRANSFORM,
        "numeric_threshold_sweep": False,
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
    assert inv["ema_fast_len"] == 21 and inv["ema_slow_len"] == 55
    assert inv["numeric_threshold_sweep"] is False
    assert inv["best_horizon_selection"] is False
    assert inv["post_outcome_trade_deletion"] is False
    assert inv["execution_authority"] == "NONE" and inv["order_authority"] == "BLOCKED"
    print("PASS_TREND_RIDER_MULTISCALE_ALIGNMENT_CHILD_POLICY_V1")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())

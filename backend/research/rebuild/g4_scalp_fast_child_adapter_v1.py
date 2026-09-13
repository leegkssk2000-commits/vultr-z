from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.research.rebuild import breakout_policy_batch_v1 as breakout
from backend.research.rebuild import trend_policy_batch_v1 as trend
from backend.research.rebuild import vwap_bb_policy_batch_v1 as vwap
from backend.research.rebuild.policy_kernel_v1 import DecisionIntent

ROOT = Path(__file__).resolve().parents[3]
FREEZE_PATH = ROOT / "research/development_evidence/G4_SCALP_INTRADAY_REBASE_V1/FAST_CHILD_FREEZE_V1.json"


@dataclass(frozen=True)
class FastChildSpec:
    child_id: str
    parent_id: str
    family: str
    timeframe_ms: int
    timeout_bars: int


SPECS: dict[str, FastChildSpec] = {
    "bb_revert_fast_v1": FastChildSpec("bb_revert_fast_v1", "bb_revert", "vwap", 300_000, 24),
    "anchor_vwap_trend_fast_v1": FastChildSpec("anchor_vwap_trend_fast_v1", "anchor_vwap_trend", "vwap", 300_000, 24),
    "vwap_revert_fast_v1": FastChildSpec("vwap_revert_fast_v1", "vwap_revert", "vwap", 300_000, 18),
    "break_and_continue_fast_v1": FastChildSpec("break_and_continue_fast_v1", "break_and_continue", "breakout", 300_000, 24),
    "squeeze_break_fast_v1": FastChildSpec("squeeze_break_fast_v1", "squeeze_break", "breakout", 300_000, 24),
    "keltner_trend_fast_v1": FastChildSpec("keltner_trend_fast_v1", "keltner_trend", "breakout", 900_000, 32),
    "supertrend_pullback_fast_v1": FastChildSpec("supertrend_pullback_fast_v1", "supertrend_pullback", "trend", 900_000, 32),
    "trend_ma_macd_fast_v1": FastChildSpec("trend_ma_macd_fast_v1", "trend_ma_macd", "trend", 900_000, 32),
    "trend_rider_fast_v1": FastChildSpec("trend_rider_fast_v1", "trend_rider", "trend", 900_000, 32),
}


def _family(spec: FastChildSpec) -> Any:
    return {"vwap": vwap, "breakout": breakout, "trend": trend}[spec.family]


def _default_config(spec: FastChildSpec) -> Any:
    if spec.family == "vwap":
        return vwap.CommonPolicyConfig()
    if spec.family == "breakout":
        return breakout.BreakoutPolicyConfig()
    return trend.TrendPolicyConfig()


def config_for(child_id: str) -> Any:
    spec = SPECS[child_id]
    return replace(_default_config(spec), timeframe_ms=spec.timeframe_ms, timeout_bars=spec.timeout_bars)


def compute_child_feature(child_id: str, bars: Sequence[Mapping[str, Any]], *, symbol: str, now_ts_ms: int) -> Any:
    spec = SPECS[child_id]
    module = _family(spec)
    compute = getattr(module, f"compute_{spec.parent_id}_feature")
    return compute(bars, symbol=symbol, now_ts_ms=now_ts_ms, config=config_for(child_id))


def _rewrite_identity(intent: DecisionIntent, child_id: str) -> DecisionIntent:
    return replace(
        intent,
        schema_version=f"zel.{child_id}.policy.v1",
        strategy_id=child_id,
        reason_codes=tuple(intent.reason_codes) + ("FAST_CHILD_TIME_COMPRESSION_V1",),
    )


def build_child_intent(
    child_id: str,
    feature: Any,
    *,
    policy_source_sha: str,
    verified_round_trip_cost_bps: float,
) -> DecisionIntent:
    spec = SPECS[child_id]
    module = _family(spec)
    build = getattr(module, f"build_{spec.parent_id}_intent")
    parent_intent = build(
        feature,
        policy_source_sha=policy_source_sha,
        verified_round_trip_cost_bps=verified_round_trip_cost_bps,
        config=config_for(child_id),
    )
    return _rewrite_identity(parent_intent, child_id)


def assert_freeze_parity() -> None:
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    children = freeze["children"]
    if set(children) != set(SPECS):
        raise RuntimeError("FAST_CHILD_SET_DRIFT")
    for child_id, spec in SPECS.items():
        frozen = children[child_id]
        if frozen["parent_strategy_id"] != spec.parent_id:
            raise RuntimeError(f"FAST_CHILD_PARENT_DRIFT:{child_id}")
        if int(frozen["timeframe_ms"]) != spec.timeframe_ms:
            raise RuntimeError(f"FAST_CHILD_TIMEFRAME_DRIFT:{child_id}")
        if int(frozen["timeout_bars"]) != spec.timeout_bars:
            raise RuntimeError(f"FAST_CHILD_TIMEOUT_DRIFT:{child_id}")
        parent = asdict(_default_config(spec))
        child = asdict(config_for(child_id))
        changed = {k for k in parent if parent[k] != child[k]}
        if changed != {"timeframe_ms", "timeout_bars"}:
            raise RuntimeError(f"FAST_CHILD_NON_TIME_MUTATION:{child_id}:{sorted(changed)}")


def manifest() -> dict[str, Any]:
    assert_freeze_parity()
    return {
        "schema_version": "zel.g4_scalp.fast_child_adapter.v1",
        "state": "FROZEN_FAST_CHILD_ADAPTER_READY",
        "children": {
            child_id: {
                "parent_id": spec.parent_id,
                "family": spec.family,
                "timeframe_ms": spec.timeframe_ms,
                "timeout_bars": spec.timeout_bars,
                "config": asdict(config_for(child_id)),
            }
            for child_id, spec in SPECS.items()
        },
        "strategy_rule_mutation_beyond_time_compression": False,
        "benchmark_transfer_applied": False,
        "selection_authority": False,
        "promotion_authority": False,
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


if __name__ == "__main__":
    print(json.dumps(manifest(), indent=2, sort_keys=True))

from __future__ import annotations

from typing import Any


def policy_functions(module: Any, strategy_id: str) -> tuple[Any, Any]:
    """Return evaluator-compatible policy callables without changing policy logic."""
    compute = getattr(module, f"compute_{strategy_id}_feature", None) or getattr(module, "compute_feature_snapshot", None)
    build = getattr(module, f"build_{strategy_id}_intent", None) or getattr(module, "build_decision_intent", None)
    if callable(compute) and callable(build):
        return compute, build

    generic_compute = getattr(module, "compute_feature", None)
    generic_build = getattr(module, "build_intent", None)
    if callable(generic_compute) and callable(generic_build):
        def compute_adapter(bars: Any, *, symbol: str, now_ts_ms: int, config: Any) -> Any:
            return generic_compute(strategy_id, bars, symbol=symbol, now_ts_ms=now_ts_ms, config=config)

        def build_adapter(feature: Any, *, policy_source_sha: str, verified_round_trip_cost_bps: float, config: Any) -> Any:
            return generic_build(
                feature,
                policy_source_sha=policy_source_sha,
                verified_round_trip_cost_bps=verified_round_trip_cost_bps,
                config=config,
            )

        return compute_adapter, build_adapter

    final_compute = getattr(module, "features", None)
    final_build = getattr(module, "intent_from_snapshot", None)
    if callable(final_compute) and callable(final_build):
        def compute_adapter(bars: Any, *, symbol: str, now_ts_ms: int, config: Any) -> Any:
            return final_compute(strategy_id, bars, symbol=symbol, now_ms=now_ts_ms, config=config)

        def build_adapter(feature: Any, *, policy_source_sha: str, verified_round_trip_cost_bps: float, config: Any) -> Any:
            return final_build(
                feature,
                policy_source_sha=policy_source_sha,
                verified_round_trip_cost_bps=verified_round_trip_cost_bps,
                config=config,
            )

        return compute_adapter, build_adapter

    raise RuntimeError("POLICY_ADAPTER_MISSING")

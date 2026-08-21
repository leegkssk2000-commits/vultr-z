from __future__ import annotations

from typing import Any

from backend.research.architecture_factory import a1_external_research_exact8_through_a3_v1 as core


_ORIGINAL_POLICY_FUNCTIONS = core.ev.policy_functions


def parent_policy_functions(module: Any, strategy_id: str) -> tuple[Any, Any]:
    """Resolve both single-strategy and batch-parent policy APIs without changing policy logic."""
    try:
        return _ORIGINAL_POLICY_FUNCTIONS(module, strategy_id)
    except RuntimeError as exc:
        if str(exc) != "POLICY_ADAPTER_MISSING":
            raise

    compute_feature = getattr(module, "compute_feature", None)
    build_intent = getattr(module, "build_intent", None)
    if callable(compute_feature) and callable(build_intent):
        def compute(bars: Any, *, symbol: str, now_ts_ms: int, config: Any = None) -> Any:
            return compute_feature(strategy_id, bars, symbol=symbol, now_ts_ms=now_ts_ms, config=config)
        return compute, build_intent

    features = getattr(module, "features", None)
    intent_from_snapshot = getattr(module, "intent_from_snapshot", None)
    if callable(features) and callable(intent_from_snapshot):
        def compute(bars: Any, *, symbol: str, now_ts_ms: int, config: Any = None) -> Any:
            return features(strategy_id, bars, symbol=symbol, now_ms=now_ts_ms, config=config)
        return compute, intent_from_snapshot

    raise RuntimeError(f"PARENT_POLICY_ADAPTER_MISSING:{strategy_id}:{module.__name__}")


def validate_parent_dispatch() -> None:
    spec = core.read(core.SPEC_PATH)
    for parent_id in core.SOURCE_READY:
        parent_path = core.ROOT / str(spec["specs"][parent_id]["parent_policy"])
        module = core._load_parent(parent_path, parent_id)
        compute, build = parent_policy_functions(module, parent_id)
        if not callable(compute) or not callable(build):
            raise RuntimeError(f"PARENT_POLICY_DISPATCH_INVALID:{parent_id}")


core.ev.policy_functions = parent_policy_functions


if __name__ == "__main__":
    validate_parent_dispatch()
    raise SystemExit(core.main())

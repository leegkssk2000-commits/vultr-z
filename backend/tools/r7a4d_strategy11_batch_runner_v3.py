from __future__ import annotations

"""Read-only V3.5 wrapper around the lineage-locked V2 batch runner.

Only subprocess timeout contracts change. Strategy logic, registry, routing,
runtime and execution authorities remain untouched.
"""

from typing import Any

from backend.tools import r7a4d_strategy11_batch_runner_v2 as base

# Measured from immutable-input isolation run 30222085317:
# supertrend_pullback A/B = 2032s / 2021s
# trend_rider A/B = 2006s / 1978s
# Contracts retain roughly 45% and 50% headroom respectively.
TIMEOUT_OVERRIDES_SECONDS = {
    "supertrend_pullback": 3000,
    "trend_rider": 3000,
}

_original_run_one = base._run_one


def _run_one_with_override(
    root: Any,
    replay: str,
    phase: str,
    batch_index: int,
    strategy_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    requested = int(timeout_seconds)
    effective = max(requested, int(TIMEOUT_OVERRIDES_SECONDS.get(strategy_id, requested)))
    print(
        f"TIMEOUT_CONTRACT strategy={strategy_id} requested={requested} effective={effective}",
        flush=True,
    )
    result = _original_run_one(
        root,
        replay,
        phase,
        batch_index,
        strategy_id,
        effective,
    )
    result["requested_timeout_seconds"] = requested
    result["effective_timeout_seconds"] = effective
    result["timeout_override_applied"] = effective != requested
    return result


base._run_one = _run_one_with_override


if __name__ == "__main__":
    raise SystemExit(base.main())

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from backend.tools import r7a4d_strategy11_supertrend_seed_repair_v1 as core

core.STRATEGY_ID = "trend_rider"
core.VERSION = "R7A4D_STRATEGY11_TREND_RIDER_SEED_REPAIR_V1"


def trend_rider_reason_trace(
    strategy: Any,
    symbols: tuple[str, ...],
    frames: Mapping[tuple[str, str], Any],
    warmup_bars: int,
    history_bars: int,
) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    calls = 0
    for window_id in core.repair.FRESH_ROLES:
        for symbol in symbols:
            frame = frames[(window_id, symbol)]
            for index in range(warmup_bars, len(frame) - 1):
                history = frame.iloc[max(0, index - history_bars + 1): index + 1].copy()
                result = core.exact._call_strategy(
                    strategy,
                    history,
                    {
                        "position_side": "",
                        "position_qty": 0.0,
                        "avg_entry": 0.0,
                        "add_count": 0,
                        "last_add_price": 0.0,
                    },
                )
                calls += 1
                reasons[str(result.get("why") or result.get("reason") or "UNSPECIFIED")] += 1
                actions[str(result.get("action") or "hold").lower()] += 1
    return {
        "call_count": calls,
        "reason_counts": dict(reasons.most_common()),
        "action_counts": dict(sorted(actions.items())),
        "indicator_nan_count": reasons.get("trend_rider_indicator_nan", 0),
    }


core.reason_trace = trend_rider_reason_trace


if __name__ == "__main__":
    raise SystemExit(core.main())

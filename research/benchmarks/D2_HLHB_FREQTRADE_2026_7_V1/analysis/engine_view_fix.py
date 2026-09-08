"""Post-indicator engine-view alignment; UNEXECUTED_ON_MARKET_DATA.

This repairs input coordinates at the offline harness boundary only. It does
not alter indicators, signal/entry/exit rules, economic results, or FT methods
on disk. All strategy indicators and D2 reference state are first computed on
the canonical prefix by the frozen harness. A transient invocation wrapper
then gives FT the calendar-aligned view its cache/cursor contract expects.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import offline_engine as frozen_harness

BAR = 14_400_000
STATUS = 'UNEXECUTED_ON_MARKET_DATA'


def aligned_view(processed, start_ms, required_startup):
    """Retain original feature/origin indices; crop only the engine/cache view."""
    if required_startup < 0:
        raise ValueError('NEGATIVE_STARTUP')
    cutoff_ms = start_ms - (int(required_startup) + 1) * BAR
    cutoff = datetime.fromtimestamp(cutoff_ms / 1000, timezone.utc)
    result = {}
    for pair, frame in processed.items():
        view = frame.loc[frame['date'] >= cutoff].copy()
        if len(view) <= required_startup + 1:
            raise ValueError('ALIGNED_VIEW_INSUFFICIENT_BARS:' + pair)
        result[pair] = view
    return result


def run_frame_aligned(strategy_class, frames, start_ms, end_ms, workdir):
    """Serial boundary wrapper around the frozen harness, for synthetic QA.

    Production integration should insert aligned_view immediately after full
    advise_all_indicators and before Backtesting.backtest. The temporary
    method wrapper here intercepts only that call's argument; the original
    installed FT backtester executes without a rule or matching modification.
    """
    original = frozen_harness.Backtesting.backtest

    def invoke(backtester, processed, start_date, end_date):
        view = aligned_view(processed, start_ms, backtester.required_startup)
        return original(backtester, view, start_date, end_date)

    with patch.object(frozen_harness.Backtesting, 'backtest', invoke):
        return frozen_harness.run_frame(strategy_class, frames, start_ms, end_ms, workdir)

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "q4r3_route_a_raschke_second_holdout.py"
spec = importlib.util.spec_from_file_location("q4r3_raschke_second_holdout_tested", MODULE_PATH)
assert spec is not None and spec.loader is not None
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)


def test_second_window_is_exact_and_non_overlapping() -> None:
    current_start = 1_800_000_000_000
    start, end, rows = MODULE.second_window_from_current_start(current_start, 129_600)
    assert rows == 129_600
    assert end == current_start - MODULE.MINUTE_MS
    assert start == end - (rows - 1) * MODULE.MINUTE_MS
    assert end < current_start
    assert (end - start) // MODULE.MINUTE_MS + 1 == rows


def test_frozen_contract_and_modes_are_exact() -> None:
    assert MODULE.FROZEN_MODES == ("source_core", "candle_direction")
    assert MODULE.FROZEN_CONTRACT == {
        "target_R": 2.0,
        "loss_cap_R": -0.50,
        "timeout_min": 480,
        "cooldown_min": 60,
    }
    canonical = json.dumps(
        {
            "modes": list(MODULE.FROZEN_MODES),
            "contract": MODULE.FROZEN_CONTRACT,
        },
        sort_keys=True,
    )
    assert "body_close" not in canonical
    assert "trend_strength" not in canonical
    assert "pdm_proxy_v1" not in canonical


def _report(*, events: int, avg: float, pf: float, mdd: float, symbols: int) -> dict:
    return {
        "events": events,
        "avg_net_R": avg,
        "profit_factor_R": pf,
        "max_drawdown_R": mdd,
        "positive_symbols": symbols,
    }


def test_mode_verdict_requires_hard_gate_and_cost_survival() -> None:
    hard = _report(events=60, avg=0.16, pf=1.3, mdd=7.0, symbols=4)
    survives = _report(events=60, avg=0.02, pf=1.05, mdd=9.0, symbols=3)
    costs = {
        "cost_0.15": {"second_holdout_90d": hard},
        "cost_0.20": {"second_holdout_90d": survives},
    }
    assert MODULE.mode_verdict(costs) == "SECOND_HOLDOUT_ROBUST_PASS"


def test_mode_verdict_rejects_cost_fragility() -> None:
    hard = _report(events=60, avg=0.16, pf=1.3, mdd=7.0, symbols=4)
    fragile = _report(events=60, avg=-0.01, pf=0.98, mdd=9.0, symbols=3)
    costs = {
        "cost_0.15": {"second_holdout_90d": hard},
        "cost_0.20": {"second_holdout_90d": fragile},
    }
    assert MODULE.mode_verdict(costs) == "SECOND_HOLDOUT_HARD_GATE_COST_FRAGILE"


def test_cost_survival_needs_three_positive_symbols() -> None:
    report = _report(events=60, avg=0.03, pf=1.1, mdd=9.0, symbols=2)
    assert MODULE.cost_survival(report) is False

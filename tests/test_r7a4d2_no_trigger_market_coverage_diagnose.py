#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_COVERAGE_DIAG"])
    spec = importlib.util.spec_from_file_location("coverage_diag", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(*, admitted: bool, state: str, regime: str = "trend_down", action: str = "enter"):
    return {
        "admitted": admitted,
        "candidate_state": state,
        "regime": regime,
        "legacy_action": action,
        "strategy_id": "fixture",
    }


def test_single_allowed_enter_routes_to_frequency_closure() -> None:
    module = load_module()
    classes, next_stage = module.classify_trace(
        [row(admitted=True, state="FLAT_ENTER")],
        closed_trades=1,
    )
    assert "ALLOWED_REGIME_SINGLE_ENTER_ONLY" in classes
    assert next_stage.endswith("SHORT_SIGNAL_FREQUENCY_AND_ADMISSION_CLOSURE")


def test_zero_allowed_enter_routes_to_market_regime_redesign() -> None:
    module = load_module()
    classes, next_stage = module.classify_trace(
        [row(admitted=False, state="FLAT_ENTER", regime="trend_up")],
        closed_trades=0,
    )
    assert "ALLOWED_REGIME_FLAT_ENTER_ZERO" in classes
    assert "BLOCKED_REGIME_CONTAINS_FLAT_ENTER" in classes
    assert next_stage.endswith("SHORT_MARKET_REGIME_COVERAGE_REDESIGN")


def test_enter_without_closed_trade_routes_to_execution_closure() -> None:
    module = load_module()
    classes, next_stage = module.classify_trace(
        [row(admitted=True, state="FLAT_ENTER")],
        closed_trades=0,
    )
    assert "ENTER_TO_CLOSED_TRADE_EXECUTION_GAP" in classes
    assert next_stage.endswith("SHORT_ENTRY_EXECUTION_CLOSURE")


def test_orphan_management_is_reported() -> None:
    module = load_module()
    classes, _ = module.classify_trace(
        [
            row(admitted=True, state="ORPHAN_MANAGEMENT", action="reduce"),
            row(admitted=True, state="FLAT_ENTER"),
        ],
        closed_trades=1,
    )
    assert "ALLOWED_REGIME_ORPHAN_MANAGEMENT" in classes

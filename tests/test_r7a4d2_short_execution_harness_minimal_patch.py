from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pandas as pd


RUNNER_PATH = Path(os.environ["R7A4D2_DUAL_RUNNER"])
spec = importlib.util.spec_from_file_location("r7a4d2_dual_runner_test", RUNNER_PATH)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
sys.modules["r7a4d2_dual_runner_test"] = runner
spec.loader.exec_module(runner)


class ShortFixture:
    def __init__(self) -> None:
        self.emitted = False

    def run(self, ctx):
        payload = ctx.signal.payload
        if not self.emitted and not payload.get("position_side"):
            self.emitted = True
            return runner.AttrBox(
                ok=True,
                intent="hold",
                confidence=0.8,
                target_qty=0.5,
                target_price=100.0,
                reason="fixture_short_entry",
                payload={
                    "legacy_signal": {
                        "side": "short",
                        "action": "enter",
                        "size": 0.5,
                        "entry": 100.0,
                        "sl": 105.0,
                        "tp": 95.0,
                        "why": "fixture_short_entry",
                    }
                },
            )
        return runner.AttrBox(
            ok=True,
            intent="hold",
            confidence=0.0,
            target_qty=0.0,
            target_price=0.0,
            reason="hold",
            payload={"legacy_signal": {"side": "", "action": "hold"}},
        )


def frame() -> pd.DataFrame:
    rows = []
    for index in range(80):
        low = 94.0 if index == 65 else 99.0
        rows.append(
            {
                "timestamp": 1_700_000_000_000 + index * 60_000,
                "open": 100.0,
                "high": 101.0,
                "low": low,
                "close": 100.0,
                "volume": 1.0,
                "symbol": "BTCUSDT",
                "timeframe": "1m",
                "__timestamp": 1_700_000_000_000 + index * 60_000,
            }
        )
    value = pd.DataFrame(rows)
    value.attrs["evaluation_start_index"] = 0
    value.attrs["indicator_preroll_bars"] = 0
    value.attrs["evaluation_bars"] = 80
    return value


def contract(enabled: bool) -> dict:
    return {
        "minimum_call_bars": 64,
        "maximum_position_qty": 1.0,
        "allowed_intents": ["hold", "block", "enter_long", "reduce", "exit_long"],
        "short_execution_enabled": enabled,
        "short_target_strategy_ids": ["fixture"],
    }


def scenario() -> dict:
    return {
        "scenario_id": "fixture.1",
        "strategy_id": "fixture",
        "segment_id": "segment.1",
        "regime": "trend_down",
        "fold": 0,
        "cost_profile": "cost_profile_0",
        "perturbation": "perturbation_0",
    }


def cost() -> dict:
    return {
        "fee_bps_per_side": 0.0,
        "slippage_bps_per_side": 0.0,
        "latency_bars": 0,
        "funding_bps_per_8h": 0.0,
    }


def perturbation() -> dict:
    return {"additional_entry_delay_bars": 0, "additional_exit_delay_bars": 0}


def test_short_execution_default_is_disabled() -> None:
    assert runner.SHORT_EXECUTION_HARNESS_V1 is True
    result = runner.simulate_scenario(
        scenario(), frame(), ShortFixture, "run", cost(), perturbation(), contract(False)
    )
    assert result["short_enter_signal_count"] == 0
    assert result["short_closed_trade_count"] == 0
    assert result["trade_count"] == 0


def test_short_entry_and_take_profit_are_executable() -> None:
    result = runner.simulate_scenario(
        scenario(), frame(), ShortFixture, "run", cost(), perturbation(), contract(True)
    )
    assert result["short_enter_signal_count"] == 1
    assert result["short_closed_trade_count"] == 1
    assert result["short_invalid_geometry_count"] == 0
    assert result["trade_sample"][0]["side"] == "short"
    assert result["trade_sample"][0]["exit_reason"] == "take_profit"
    assert result["trade_sample"][0]["net_pnl_pct"] > 0


def test_short_lineage_requires_same_strategy_entry() -> None:
    valid = {
        "side": "short",
        "entry_strategy_id": "fixture",
        "entry_event": "fixture_short_entry",
    }
    assert runner.lineage_allows_add("fixture", valid) is True
    assert runner.lineage_allows_add("other", valid) is False
    assert runner.lineage_allows_add("fixture", {**valid, "entry_event": ""}) is False


def test_short_geometry_direction_is_fail_closed() -> None:
    class InvalidShort(ShortFixture):
        def run(self, ctx):
            value = super().run(ctx)
            legacy = value.payload.get("legacy_signal", {})
            if legacy.get("action") == "enter":
                legacy["sl"] = 95.0
                legacy["tp"] = 105.0
            return value

    result = runner.simulate_scenario(
        scenario(), frame(), InvalidShort, "run", cost(), perturbation(), contract(True)
    )
    assert result["short_closed_trade_count"] == 0
    assert result["short_invalid_geometry_count"] == 1

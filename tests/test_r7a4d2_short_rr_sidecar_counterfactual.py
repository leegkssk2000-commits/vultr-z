from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pandas as pd


RUNNER_PATH = Path(os.environ["R7A4D2_RR_RUNNER"])
spec = importlib.util.spec_from_file_location("r7a4d2_rr_runner_test", RUNNER_PATH)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
sys.modules["r7a4d2_rr_runner_test"] = runner
spec.loader.exec_module(runner)


class ShortFixture:
    def __init__(self) -> None:
        self.entered = False

    def run(self, ctx):
        payload = ctx.signal.payload
        if not self.entered and not payload.get("position_side"):
            self.entered = True
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
                        "sl": 102.0,
                        "tp": 99.0,
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


class ReduceFixture(ShortFixture):
    def run(self, ctx):
        value = super().run(ctx)
        if self.entered and ctx.signal.payload.get("position_side") == "short":
            return runner.AttrBox(
                ok=True,
                intent="hold",
                confidence=0.7,
                target_qty=0.0,
                target_price=100.0,
                reason="fixture_reduce",
                payload={"legacy_signal": {"side": "short", "action": "reduce", "why": "fixture_reduce"}},
            )
        return value


def frame() -> pd.DataFrame:
    rows = []
    for index in range(80):
        low = 94.0 if index == 70 else 99.0
        rows.append(
            {
                "timestamp": 1_700_000_000_000 + index * 60_000,
                "open": 100.0,
                "high": 100.5,
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


def contract(enabled: bool = True) -> dict:
    return {
        "minimum_call_bars": 64,
        "maximum_position_qty": 1.0,
        "allowed_intents": ["hold", "block", "enter_long", "reduce", "exit_long"],
        "short_execution_enabled": enabled,
        "short_target_strategy_ids": ["fixture"],
        "short_rr_sidecar_enabled": True,
        "short_policy_loss_cap_r": 0.75,
        "short_policy_full_tp_r": 2.5,
    }


def scenario(regime: str = "trend_down") -> dict:
    return {
        "scenario_id": "fixture.1",
        "strategy_id": "fixture",
        "segment_id": "segment.1",
        "regime": regime,
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


def test_exact_2_5r_take_profit_and_raw_geometry_are_preserved() -> None:
    result = runner.simulate_scenario(
        scenario(), frame(), ShortFixture, "run", cost(), perturbation(), contract()
    )
    assert result["short_closed_trade_count"] == 1
    trade = result["short_trade_detail"][0]
    assert trade["raw_strategy_stop"] == 102.0
    assert trade["raw_strategy_tp"] == 99.0
    assert abs(float(trade["pnl_r"]) - 2.5) < 1e-9
    assert trade["exit_reason"] == "take_profit"


def test_trend_up_short_is_fail_closed() -> None:
    result = runner.simulate_scenario(
        scenario("trend_up"), frame(), ShortFixture, "run", cost(), perturbation(), contract()
    )
    assert result["short_closed_trade_count"] == 0
    assert result["short_policy_regime_block_count"] >= 1


def test_full_tp_profile_suppresses_reduce() -> None:
    result = runner.simulate_scenario(
        scenario(), frame(), ReduceFixture, "run", cost(), perturbation(), contract()
    )
    assert result["short_policy_reduce_suppressed_count"] > 0
    assert result["short_trade_detail"][0]["exit_reason"] == "take_profit"


def test_sidecar_disabled_short_execution_keeps_zero_short_trades() -> None:
    value = contract(False)
    result = runner.simulate_scenario(
        scenario(), frame(), ShortFixture, "run", cost(), perturbation(), value
    )
    assert result["short_closed_trade_count"] == 0
    assert result["trade_count"] == 0

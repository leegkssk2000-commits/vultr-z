from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


MODULE_PATH = Path(__file__).parents[1] / "tools/r7a4d_historical_simulation_3600.py"
spec = importlib.util.spec_from_file_location("r7a4d_sim_test", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def prior_status() -> dict:
    return {
        "official_stage": "R7.A4C",
        "state": "PASS",
        "blocker_count": 0,
        "strategy_count": 25,
        "historical_segment_selected_count": 24,
        "regime_coverage_count": 4,
        "trend_up_fold_count": 6,
        "range_fold_count": 6,
        "trend_down_fold_count": 6,
        "shock_recovery_fold_count": 6,
        "execution_cost_axis_coverage_count": 4,
        "scenario_plan_count": 3600,
        "historical_simulation_execution_count": 0,
        "active_entry_count": 0,
        "canonical_mutation_count": 0,
        "protected_change_count": 0,
        "router_mutation_count": 0,
        "service_mutation_count": 0,
        "paper_live_order_count": 0,
        "next_stage": "R7.A4D_HISTORICAL_SIMULATION_3600",
        "lineage_id": "lineage",
    }


def test_prior_gate_is_exact() -> None:
    status = prior_status()
    assert module.prior_gate(status, 25, 24, 3600) is True
    status["historical_simulation_execution_count"] = 1
    assert module.prior_gate(status, 25, 24, 3600) is False


def build_array_rows(count: int = 400) -> list[list[float]]:
    rows: list[list[float]] = []
    previous = 100.0
    for index in range(count):
        timestamp = 1_700_000_000_000 + index * 60_000
        open_ = previous
        close = open_ + ((index % 7) - 3) * 0.02
        high = max(open_, close) + 0.3
        low = min(open_, close) - 0.25
        volume = 1000.0 + index
        rows.append([timestamp, open_, high, low, close, volume])
        previous = close
    return rows


def test_array_schema_inference_rejects_volume_as_price() -> None:
    rows = []
    for timestamp, open_, high, low, close, volume in build_array_rows():
        rows.append([timestamp, open_, volume, low, close, high])
    assert module.infer_ohlcv_array_schema(rows) == {
        "timestamp": 0,
        "open": 1,
        "high": 5,
        "low": 3,
        "close": 4,
        "volume": 2,
    }


def build_frame(collision: bool = False) -> pd.DataFrame:
    rows = []
    for index in range(12):
        open_ = 100.0
        high = 100.4
        low = 99.6
        close = 100.0
        if index == 6:
            high = 103.0
            low = 98.0 if collision else 99.5
            close = 101.0
        rows.append(
            {
                "timestamp": 1_700_000_000_000 + index * 60_000,
                "__timestamp": 1_700_000_000_000 + index * 60_000,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1000.0,
                "symbol": "BTCUSDT",
                "timeframe": "1m",
            }
        )
    return pd.DataFrame(rows)


class EnterOnceStrategy:
    def decide(self, ctx):
        bars = list(ctx.signal.payload["ohlcv"])
        if len(bars) == 6 and not ctx.signal.payload.get("position_qty"):
            return SimpleNamespace(
                ok=True,
                intent="enter_long",
                confidence=0.8,
                target_qty=0.5,
                target_price=100.0,
                reason="test_enter",
                payload={
                    "legacy_signal": {
                        "side": "long",
                        "action": "enter",
                        "size": 0.5,
                        "entry": 100.0,
                        "sl": 99.0,
                        "tp": 102.0,
                    }
                },
            )
        return SimpleNamespace(
            ok=True,
            intent="hold",
            confidence=0.0,
            target_qty=0.0,
            target_price=100.0,
            reason="hold",
            payload={"legacy_signal": {"side": None, "action": "hold"}},
        )


def contract() -> dict:
    return {
        "minimum_call_bars": 6,
        "maximum_position_qty": 1.0,
        "allowed_intents": ["hold", "enter_long", "exit_long", "reduce", "block"],
    }


def cost() -> dict:
    return {
        "id": "cost_profile_0",
        "fee_bps_per_side": 5.0,
        "slippage_bps_per_side": 1.0,
        "latency_bars": 0,
        "funding_bps_per_8h": 1.0,
    }


def perturbation() -> dict:
    return {
        "id": "perturbation_0",
        "additional_entry_delay_bars": 0,
        "additional_exit_delay_bars": 0,
    }


def scenario() -> dict:
    return {
        "scenario_id": "scenario",
        "strategy_id": "test",
        "segment_id": "segment",
        "regime": "trend_up",
        "fold": 0,
        "cost_profile": "cost_profile_0",
        "perturbation": "perturbation_0",
    }


def test_next_bar_fill_and_take_profit_are_applied() -> None:
    result = module.simulate_scenario(
        scenario(), build_frame(collision=False), EnterOnceStrategy, "decide", cost(), perturbation(), contract()
    )
    assert result["completed"] is True
    assert result["trade_count"] == 1
    assert result["trade_exit_histogram"] == {"take_profit": 1}
    assert result["net_return_pct"] > 0
    assert result["total_cost_pct"] > 0


def test_intrabar_collision_is_stop_first() -> None:
    result = module.simulate_scenario(
        scenario(), build_frame(collision=True), EnterOnceStrategy, "decide", cost(), perturbation(), contract()
    )
    assert result["trade_count"] == 1
    assert result["trade_exit_histogram"] == {"stop_collision": 1}
    assert result["net_return_pct"] < 0


def test_simulation_is_deterministic() -> None:
    first = module.simulate_scenario(
        scenario(), build_frame(collision=False), EnterOnceStrategy, "decide", cost(), perturbation(), contract()
    )
    second = module.simulate_scenario(
        scenario(), build_frame(collision=False), EnterOnceStrategy, "decide", cost(), perturbation(), contract()
    )
    assert first == second


def test_side_effect_guard_blocks_strategy_writes(tmp_path: Path) -> None:
    attempts: list[str] = []
    target = tmp_path / "blocked.txt"
    with pytest.raises(module.SideEffectBlocked):
        with module.side_effect_guard(attempts):
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("x")
    assert attempts
    assert not target.exists()


def test_summary_does_not_promote_zero_trade_rows() -> None:
    summary = module.summarize_rows(
        [
            {"completed": True, "trade_count": 0, "net_return_pct": 0.0, "max_drawdown_pct": 0.0, "expectancy_r": 0.0},
            {"completed": True, "trade_count": 1, "net_return_pct": 1.0, "max_drawdown_pct": -0.5, "expectancy_r": 1.2},
        ]
    )
    assert summary["scenario_count"] == 2
    assert summary["active_scenario_count"] == 1
    assert summary["active_scenario_rate_pct"] == 50.0

import json
from pathlib import Path

import pytest

from backend.production.zel_production_alpha_signal_runner_v1 import run_once


def factory(tmp_path):
    return {
        "schema_version": "zel.production_alpha_factory.v1",
        "state": "NO_ECONOMIC_SURVIVOR_SAFE_IDLE",
        "mode": "PAPER",
        "economic_survivor_count": 0,
        "executable_family_count": 0,
        "families": {
            "trend_momentum": {
                "strategy_id": "trend_momentum_v1",
                "status": "TERMINAL_REJECT_DO_NOT_REACTIVATE",
                "selection_authority": False,
                "promotion_authority": False,
                "execution_authority": "NONE",
                "reactivation_allowed": False,
            }
        },
        "active_authority_path": str(tmp_path / "authority.json"),
        "active_signal_path": str(tmp_path / "signal.json"),
        "order_authority": "BLOCKED",
        "live_trade_authority": "BLOCKED",
    }


def executable_authority(strategy_id="trend_momentum_v1"):
    return {
        "alpha_state": "SURVIVOR_ACTIVE",
        "research_only": False,
        "promotion_authority": True,
        "execution_allowed": True,
        "runtime_bound": True,
        "strategy_id": strategy_id,
        "alpha_id": "alpha.seed.v1",
        "symbol": "BTCUSDT",
        "runtime_authority": {
            "execution_authority": "PAPER_SIM_ONLY",
            "order_authority": "BLOCKED",
            "live_trade_authority": "BLOCKED",
        },
    }


def write(path: Path, row):
    path.write_text(json.dumps(row), encoding="utf-8")


def test_missing_authority_is_o1_hold_and_does_not_call_generator(tmp_path):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("network/generator must not be called")

    cfg = factory(tmp_path)
    result = run_once(factory=cfg, now_ms=10_000, signal_generator=forbidden)
    assert result["state"] == "HOLD_NO_EXECUTABLE_ALPHA"
    assert result["reason"] == "ALPHA_AUTHORITY_MISSING"
    assert result["network_called"] is False
    assert result["signal_written"] is False
    assert calls == []
    assert not Path(cfg["active_signal_path"]).exists()


def test_non_executable_authority_holds_without_touching_existing_signal(tmp_path):
    cfg = factory(tmp_path)
    authority = executable_authority("alpha_future_survivor_v1")
    authority["promotion_authority"] = False
    write(Path(cfg["active_authority_path"]), authority)
    signal_path = Path(cfg["active_signal_path"])
    signal_path.write_text("preserve-me", encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("network/generator must not be called")

    result = run_once(factory=cfg, now_ms=10_000, signal_generator=forbidden)
    assert result["reason"] == "ALPHA_AUTHORITY_NON_EXECUTABLE"
    assert result["network_called"] is False
    assert result["signal_written"] is False
    assert signal_path.read_text() == "preserve-me"


def test_stale_terminal_trend_survivor_authority_is_forced_to_safe_idle(tmp_path):
    cfg = factory(tmp_path)
    write(Path(cfg["active_authority_path"]), executable_authority("trend_momentum_v1"))
    signal_path = Path(cfg["active_signal_path"])
    signal_path.write_text("preserve-terminal-signal", encoding="utf-8")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("terminal strategy generator/network must not be called")

    result = run_once(factory=cfg, now_ms=10_000, signal_generator=forbidden)
    assert result["state"] == "HOLD_NO_EXECUTABLE_ALPHA"
    assert result["reason"] == "ALPHA_AUTHORITY_NON_EXECUTABLE"
    assert result["network_called"] is False
    assert result["signal_written"] is False
    assert calls == []
    assert signal_path.read_text() == "preserve-terminal-signal"


def test_unsupported_future_executable_strategy_fails_closed_before_generator(tmp_path):
    cfg = factory(tmp_path)
    write(Path(cfg["active_authority_path"]), executable_authority("carry_flow_v1"))

    def forbidden(*args, **kwargs):
        raise AssertionError("generator must not be called")

    with pytest.raises(RuntimeError, match="ALPHA_PRODUCER_UNSUPPORTED_STRATEGY:carry_flow_v1"):
        run_once(factory=cfg, now_ms=10_000, signal_generator=forbidden)
    assert not Path(cfg["active_signal_path"]).exists()

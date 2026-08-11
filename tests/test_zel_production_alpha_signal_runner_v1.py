import json
from pathlib import Path

import pytest

from backend.production.zel_production_alpha_signal_runner_v1 import run_once


def factory(tmp_path):
    return {
        "schema_version": "zel.production_alpha_factory.v1",
        "mode": "PAPER",
        "families": {
            "trend_momentum": {
                "strategy_id": "trend_momentum_v1",
                "status": "IMPLEMENTED_PRIMARY_SEED",
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "timeframe": "1h",
                "history_bars": 200,
                "long_enabled": True,
                "short_enabled": False,
                "ema_fast": 50,
                "ema_slow": 200,
                "parameter_lineage": {
                    "source": "strategies/evidence_alpha_v1.py:_htf_bias",
                    "source_sha256": "a060529401c9a218cfa04be0511d5f7ab0cdecff",
                    "inherited_rule": "price > EMA50 > EMA200",
                },
                "promotion_authority": False,
                "execution_authority": "PAPER_SIGNAL_ONLY",
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


def signal():
    return {
        "schema_version": "zel.production_alpha_signal.v1",
        "state": "PASS_ACTIVE_ALPHA_SIGNAL",
        "strategy_id": "trend_momentum_v1",
        "alpha_id": "alpha.seed.v1",
        "symbol": "BTCUSDT",
        "signal": "LONG",
        "signal_ts": 10_000,
        "source_hashes": ["a" * 64],
        "receipt_sha256": "b" * 64,
        "exchange_order_submitted": False,
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
    authority = executable_authority()
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


def test_executable_trend_authority_atomically_writes_pass_signal(tmp_path):
    cfg = factory(tmp_path)
    write(Path(cfg["active_authority_path"]), executable_authority())
    calls = []

    def fake_generator(authority, *, factory, now_ms):
        calls.append((authority["strategy_id"], now_ms))
        return signal()

    result = run_once(factory=cfg, now_ms=10_000, signal_generator=fake_generator)
    assert calls == [("trend_momentum_v1", 10_000)]
    assert result["state"] == "PASS_ACTIVE_ALPHA_SIGNAL_WRITTEN"
    assert result["network_called"] is True
    assert result["signal_written"] is True
    saved = json.loads(Path(cfg["active_signal_path"]).read_text())
    assert saved["signal"] == "LONG"
    assert saved["exchange_order_submitted"] is False
    assert (Path(cfg["active_signal_path"]).stat().st_mode & 0o777) == 0o600


def test_unsupported_executable_strategy_fails_closed_before_generator(tmp_path):
    cfg = factory(tmp_path)
    write(Path(cfg["active_authority_path"]), executable_authority("carry_flow_v1"))

    def forbidden(*args, **kwargs):
        raise AssertionError("generator must not be called")

    with pytest.raises(RuntimeError, match="ALPHA_PRODUCER_UNSUPPORTED_STRATEGY:carry_flow_v1"):
        run_once(factory=cfg, now_ms=10_000, signal_generator=forbidden)
    assert not Path(cfg["active_signal_path"]).exists()

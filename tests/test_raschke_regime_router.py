from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_regime_router.py"
    spec = importlib.util.spec_from_file_location("test_raschke_regime_router_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def metric(
    *,
    events: int = 80,
    avg: float = 0.12,
    pf: float = 1.4,
    mdd: float = 6.0,
    positive_symbols: int = 4,
):
    return {
        "events": events,
        "avg_net_R": avg,
        "profit_factor_R": pf,
        "max_drawdown_R": mdd,
        "positive_symbols": positive_symbols,
    }


def test_router_scores_are_predeclared_and_monotonic() -> None:
    features = {
        "slope_aligned": True,
        "adx_ok": True,
        "chop_ok": True,
        "macd_ok": False,
        "h4_aligned": True,
        "volatility_ok": False,
    }
    assert MODULE.router_pass("router_off", features) == (True, 0)
    assert MODULE.router_pass("r1_slope_alignment", features) == (True, 1)
    assert MODULE.router_pass("r2_quality_2of3", features) == (True, 2)
    assert MODULE.router_pass("r3_regime_3of5", features) == (True, 4)
    assert MODULE.router_pass("r4_regime_4of6", features) == (True, 4)


def test_router_rejects_low_quality_regime() -> None:
    features = {
        "slope_aligned": False,
        "adx_ok": False,
        "chop_ok": True,
        "macd_ok": False,
        "h4_aligned": False,
        "volatility_ok": True,
    }
    assert MODULE.router_pass("r1_slope_alignment", features)[0] is False
    assert MODULE.router_pass("r2_quality_2of3", features)[0] is False
    assert MODULE.router_pass("r3_regime_3of5", features)[0] is False
    assert MODULE.router_pass("r4_regime_4of6", features)[0] is False


def test_atr_percentile_uses_current_against_prior_distribution() -> None:
    values = [float(index) for index in range(1, 101)]
    assert MODULE.atr_percentile(values) == 100.0
    values[-1] = 0.5
    assert MODULE.atr_percentile(values) == 0.0
    assert MODULE.atr_percentile(values[:20]) is None


def test_regime_features_use_only_latest_completed_rows() -> None:
    signal_ts = 1_700_000_000_000
    frames = {
        "1h": pd.DataFrame(
            [
                {"ts": signal_ts - 60_000, "atr_percentile_240h": 50.0},
                {"ts": signal_ts + 60_000, "atr_percentile_240h": 99.0},
            ]
        ),
        "4h": pd.DataFrame(
            [
                {
                    "ts": signal_ts - 60_000,
                    "close": 110.0,
                    "ema50": 100.0,
                    "ema50_slope_2bar": 2.0,
                },
                {
                    "ts": signal_ts + 60_000,
                    "close": 90.0,
                    "ema50": 100.0,
                    "ema50_slope_2bar": -2.0,
                },
            ]
        ),
    }
    result = {
        "ema_slope_atr": 0.02,
        "adx": 20.0,
        "chop_score": 0.20,
        "macd_signal_spread_atr": 0.01,
    }
    features = MODULE.regime_features(
        result,
        side="long",
        signal_ts=signal_ts,
        frames=frames,
    )
    assert features["slope_aligned"] is True
    assert features["adx_ok"] is True
    assert features["chop_ok"] is True
    assert features["macd_ok"] is True
    assert features["h4_aligned"] is True
    assert features["volatility_ok"] is True
    assert features["atr_percentile_240h"] == 50.0


def test_gate_requires_second_window_recovery() -> None:
    blocks = {"nonnegative_block_ratio": 0.8}
    passed = MODULE.gate_assessment(
        combined=metric(),
        prior=metric(avg=0.20),
        second=metric(avg=-0.04),
        cost020=metric(avg=0.03),
        block_report=blocks,
        retention_pct=75.0,
    )
    assert passed["pass"] is True

    failed = MODULE.gate_assessment(
        combined=metric(),
        prior=metric(avg=0.20),
        second=metric(avg=-0.20),
        cost020=metric(avg=0.03),
        block_report=blocks,
        retention_pct=75.0,
    )
    assert failed["pass"] is False
    assert "second_window" in failed["failed_checks"]


def test_monthly_blocks_purge_cross_month_trade() -> None:
    start = int(pd.Timestamp("2026-01-31T23:00:00Z").timestamp() * 1000)
    same_month = {
        "entry_ts": start - 86_400_000,
        "exit_ts": start - 82_800_000,
        "entry": 100.0,
        "base_risk": 1.0,
        "gross_r": 0.5,
        "symbol": "BTCUSDT",
        "side": "long",
        "outcome": "TP",
    }
    cross_month = {
        "entry_ts": start,
        "exit_ts": start + 7_200_000,
        "entry": 100.0,
        "base_risk": 1.0,
        "gross_r": -0.5,
        "symbol": "BTCUSDT",
        "side": "long",
        "outcome": "SL",
    }
    report = MODULE.monthly_blocks([same_month, cross_month], 0.15)
    assert report["purged_cross_month_trades"] == 1
    assert report["block_count"] == 1

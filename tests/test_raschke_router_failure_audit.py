from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_router_failure_audit.py"
    spec = importlib.util.spec_from_file_location("test_raschke_router_failure_audit_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def trade(
    key: str,
    net_r: float,
    *,
    window: str = "second_holdout_90d",
    symbol: str = "BTCUSDT",
    side: str = "long",
    hour: int = 12,
    outcome: str = "SL",
):
    start = int(pd.Timestamp(f"2026-01-02T{hour:02d}:00:00Z").timestamp() * 1000)
    row = {
        "window": window,
        "router": "router_off",
        "symbol": symbol,
        "side": side,
        "signal_ts": start + int(key.strip("T") or 0) * 3_600_000,
        "entry_ts": start + int(key.strip("T") or 0) * 3_600_000,
        "exit_ts": start + int(key.strip("T") or 0) * 3_600_000 + 60 * 60_000,
        "entry": 100.0,
        "base_risk": 1.0,
        "gross_r": net_r + 0.15,
        "outcome": outcome,
        "trade_id": key,
        "net_R_0.15": net_r,
        "net_R_0.20": net_r - 0.05,
        "duration_min": 60,
        "month": "2026-01",
        "session": MODULE.utc_session(start),
        "mfe_R": 0.2,
        "mae_R": 0.6,
        "duration_bucket": "d00_060",
        "mfe_bucket": "mfe_lt_0.5R",
        "mae_bucket": "mae_0.5_0.75R",
    }
    return row


def test_utc_session_boundaries() -> None:
    for hour, expected in ((0, "utc_00_07"), (7, "utc_00_07"), (8, "utc_08_15"), (15, "utc_08_15"), (16, "utc_16_23"), (23, "utc_16_23")):
        stamp = int(pd.Timestamp(f"2026-01-01T{hour:02d}:00:00Z").timestamp() * 1000)
        assert MODULE.utc_session(stamp) == expected


def test_router_audit_detects_profit_destruction_and_loss_left() -> None:
    baseline = [trade("T1", 1.0, outcome="TP"), trade("T2", -0.6), trade("T3", -0.5)]
    routed = [baseline[1], baseline[2]]
    report = MODULE.router_window_audit(baseline, routed)
    assert report["false_blocked_wins"] == 1
    assert report["false_blocked_win_R"] == 1.0
    assert report["useful_blocked_losses"] == 0
    assert report["false_passed_losses"] == 2
    assert report["actual_router_delta_R"] == -1.0


def test_router_audit_detects_useful_loss_block() -> None:
    baseline = [trade("T1", 0.8, outcome="TP"), trade("T2", -0.6), trade("T3", -0.5)]
    routed = [baseline[0], baseline[2]]
    report = MODULE.router_window_audit(baseline, routed)
    assert report["useful_blocked_losses"] == 1
    assert round(report["useful_blocked_loss_R"], 6) == 0.6
    assert report["false_blocked_wins"] == 0
    assert round(report["actual_router_delta_R"], 6) == 0.6


def test_contribution_counterfactual_improves_second_window() -> None:
    prior = [trade("T1", 0.2, window="prior_holdout_90d", symbol="BTCUSDT") for _ in range(5)]
    for index, row in enumerate(prior):
        row["trade_id"] = f"P{index}"
    second = [trade("T1", -0.6, symbol="BTCUSDT") for _ in range(5)] + [trade("T2", 0.3, symbol="ETHUSDT") for _ in range(5)]
    for index, row in enumerate(second):
        row["trade_id"] = f"S{index}"
    records = MODULE.contribution_records(prior, second, "symbol")
    btc = next(row for row in records if row["group"] == "BTCUSDT")
    assert btc["second"]["net_sum_R"] < 0
    assert btc["counterfactual_remove_group"]["second_avg_R_improvement"] > 0


def test_split_candidate_requires_causal_axis_and_all_gates() -> None:
    good_evidence = {
        "axis": "side",
        "group": "short",
        "prior": {"avg_net_R": 0.0},
        "second": {"events": 10, "net_sum_R": -3.0},
        "combined": {},
        "second_loss_share_pct": 30.0,
        "counterfactual_remove_group": {
            "retention_combined_pct": 80.0,
            "second_avg_R_improvement": 0.10,
            "combined_cost_0.15": {"positive_symbols": 4},
            "combined_cost_0.20": {"avg_net_R": 0.03},
        },
    }
    contribution = {axis: [] for axis in MODULE.DIAGNOSTIC_AXES}
    contribution["side"] = [good_evidence]
    candidates = MODULE.split_candidates(contribution)
    assert len(candidates) == 1
    assert candidates[0]["axis"] == "side"
    assert candidates[0]["auto_apply"] is False


def test_excursion_marks_gap_invalid() -> None:
    start = int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp() * 1000)
    raw = pd.DataFrame(
        [
            {"ts": start, "high": 101.0, "low": 99.0},
            {"ts": start + 120_000, "high": 102.0, "low": 98.0},
        ]
    )
    row = trade("T0", -0.5)
    row["entry_ts"] = start
    row["exit_ts"] = start + 120_000
    enriched = MODULE.enrich_excursion(row, raw)
    assert enriched["path_valid"] is False
    assert enriched["mfe_R"] is None


def test_bucket_contracts() -> None:
    assert MODULE.duration_bucket(60) == "d00_060"
    assert MODULE.duration_bucket(61) == "d061_120"
    assert MODULE.mfe_bucket(1.2) == "mfe_1.0_2.0R"
    assert MODULE.mae_bucket(0.8) == "mae_ge_0.75R"

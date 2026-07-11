from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_loss_cluster_forensic.py"
    spec = importlib.util.spec_from_file_location("test_raschke_loss_forensic", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def trade(index: int, net_r: float, outcome: str = "SL", **extra):
    row = {
        "mode": "candle_direction",
        "window": "prior_holdout_90d",
        "symbol": "BTCUSDT",
        "side": "long",
        "entry_ts": 1_700_000_000_000 + index * 3_600_000,
        "exit_ts": 1_700_000_000_000 + index * 3_600_000 + 1_800_000,
        "entry": 100.0,
        "exit": 99.5,
        "stop": 99.5,
        "target": 102.0,
        "base_risk": 1.0,
        "gross_r": net_r,
        "net_R": net_r,
        "outcome": outcome,
        "trade_key": f"T{index}",
        "entry_utc": "x",
        "exit_utc": "y",
        "ema_distance_atr": 0.5,
        "ema_slope_atr": -0.02,
        "adx": 14.0,
        "candle_body_atr": 0.08,
        "close_location": 0.55,
        "volume_ratio": 0.7,
        "macd_signal_spread_atr": 0.003,
        "macd_signal_spread_prev_atr": 0.002,
        "chop_score": 0.35,
        "mfe_R": 0.2,
        "mae_R": 0.6,
        "post_exit_best_R_240": 0.1,
    }
    row.update(extra)
    return row


def test_detects_consecutive_and_rolling_loss_cluster() -> None:
    rows = [
        trade(0, 0.4, "TP"),
        trade(1, -0.55),
        trade(2, -0.52),
        trade(3, -0.54),
        trade(4, -0.30, "TIMEOUT"),
        trade(5, 0.2, "TIMEOUT"),
    ]
    clusters = MODULE.detect_clusters(rows, "candle_direction", "prior_holdout_90d")
    assert clusters
    assert any("consecutive_sl>=3" in cluster["triggers"] for cluster in clusters)
    assert any(cluster["net_sum_R"] <= -1.5 for cluster in clusters)
    assert any(row.get("cluster_ids") for row in rows[1:4])


def test_recurring_signature_requires_both_windows() -> None:
    first = [trade(index, -0.4) for index in range(6)]
    second = [
        trade(index + 10, -0.3, window="second_holdout_90d")
        for index in range(6)
    ]
    second[0]["window"] = "second_holdout_90d"
    mode_rows = {
        "prior_holdout_90d": first,
        "second_holdout_90d": second,
    }
    _, adverse = MODULE.recurring_signatures(mode_rows)
    keys = {(row["feature"], row["bucket"]) for row in adverse}
    assert ("ema_slope_alignment", "misaligned") in keys
    assert ("adx", "weak<=17") in keys
    assert ("ema_distance_atr", "near<=0.75") in keys


def test_fix_candidates_are_capped_and_not_auto_applied() -> None:
    evidence = []
    for score, key in enumerate(
        [
            ("ema_slope_alignment", "misaligned"),
            ("adx", "weak<=17"),
            ("ema_distance_atr", "near<=0.75"),
            ("chop_score", "choppy>0.30"),
            ("side", "short"),
        ],
        start=1,
    ):
        evidence.append(
            {
                "feature": key[0],
                "bucket": key[1],
                "evidence_score": float(score),
                "combined": {"avg_net_R": -0.2},
                "windows": {},
            }
        )
    rows = [trade(index, -0.5) for index in range(10)]
    candidates = MODULE.make_fix_candidates(evidence, rows)
    assert len(candidates) == 3
    assert all(candidate["auto_apply"] is False for candidate in candidates)
    assert all(candidate["change_scope"] == "single_structure_only" for candidate in candidates)


def test_trade_path_gap_blocks_excursion_metrics() -> None:
    start = 1_700_000_000_000
    raw = pd.DataFrame(
        [
            {"ts": start, "ts_dt": pd.to_datetime(start, unit="ms", utc=True), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"ts": start + 120_000, "ts_dt": pd.to_datetime(start + 120_000, unit="ms", utc=True), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
        ]
    )
    row = trade(0, -0.5)
    row["entry_ts"] = start
    row["exit_ts"] = start + 120_000
    enriched = MODULE.enrich_excursions(row, raw)
    assert enriched["path_gap"] is True
    assert enriched["mfe_R"] is None
    assert enriched["mae_R"] is None


def test_matched_pair_prefers_same_window_and_mode() -> None:
    loss = trade(1, -0.5)
    win_same = trade(2, 0.8, "TP", ema_distance_atr=0.55)
    win_other = trade(3, 1.0, "TP", window="second_holdout_90d", ema_distance_atr=0.51)
    win_other["window"] = "second_holdout_90d"
    pairs = MODULE.build_matched_pairs([loss, win_same, win_other], limit=1)
    assert len(pairs) == 1
    assert pairs[0]["matched_win_trade"]["trade_key"] == win_same["trade_key"]


def test_stop_recovery_summary() -> None:
    rows = [
        trade(1, -0.5, post_exit_best_R_240=0.2),
        trade(2, -0.5, post_exit_best_R_240=-0.1),
        trade(3, 0.5, "TP", post_exit_best_R_240=1.0),
    ]
    report = MODULE.stop_recovery_summary(rows)
    assert report["sl_events"] == 2
    assert report["recovered_to_entry_pct_240"] == 50.0

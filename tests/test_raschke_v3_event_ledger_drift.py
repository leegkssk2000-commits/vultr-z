from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_v3_event_ledger_drift.py"
    spec = importlib.util.spec_from_file_location("test_raschke_v3_event_ledger_drift_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def make_raw(prices):
    start = 1_700_000_000_000
    rows = []
    for index, (open_, high, low, close) in enumerate(prices):
        stamp = start + index * 60_000
        rows.append({
            "ts": stamp,
            "ts_dt": pd.to_datetime(stamp, unit="ms", utc=True),
            "open": open_, "high": high, "low": low, "close": close,
            "volume": 1.0, "raw_idx": index,
        })
    return pd.DataFrame(rows)


def test_label_signal_tp_first() -> None:
    raw = make_raw([
        (100.0, 100.2, 99.9, 100.1),
        (100.1, 102.1, 100.0, 102.0),
        (102.0, 102.2, 101.8, 102.1),
    ])
    result = MODULE.label_signal(raw, entry_idx=0, side="long", signal_entry=100.0, native_stop=99.0)
    assert result is not None
    assert result["label"] == "TP_FIRST"
    assert round(result["gross_R"], 6) == 2.0


def test_label_signal_same_bar_is_conservative_stop() -> None:
    raw = make_raw([
        (100.0, 102.1, 99.4, 100.0),
        (100.0, 100.1, 99.9, 100.0),
    ])
    result = MODULE.label_signal(raw, entry_idx=0, side="long", signal_entry=100.0, native_stop=99.0)
    assert result is not None
    assert result["label"] == "SL_FIRST_CONSERVATIVE"
    assert result["ambiguous"] is True


def test_label_signal_rejects_gap() -> None:
    raw = make_raw([
        (100.0, 100.2, 99.9, 100.1),
        (100.1, 100.3, 100.0, 100.2),
    ])
    raw.loc[1, "ts"] += 60_000
    result = MODULE.label_signal(raw, entry_idx=0, side="long", signal_entry=100.0, native_stop=99.0)
    assert result is None


def test_psi_detects_shift() -> None:
    prior = [float(value) for value in range(100)]
    second = [float(value + 100) for value in range(100)]
    assert MODULE.population_stability_index(prior, second) > 0.25
    assert MODULE.ks_statistic(prior, second) > 0.9
    assert abs(MODULE.standardized_mean_difference(prior, second)) > 1.0


def test_js_divergence_detects_category_shift() -> None:
    left = {"long": 0.9, "short": 0.1}
    right = {"long": 0.1, "short": 0.9}
    assert MODULE.js_divergence(left, right) > 0.1


def event(index: int, *, window: str, side: str, label: str, net_r: float):
    return {
        "event_id": f"E{index}",
        "window": window,
        "symbol": "BTCUSDT",
        "side": side,
        "signal_ts": 1_700_000_000_000 + index * 60_000,
        "signal_utc": "2023-11-14 00:00:00+00:00",
        "utc_hour": 0,
        "utc_session": "utc_00_07",
        "source_reason": "enter",
        "proximity_pass": True,
        "label": label,
        "net_R_0.15": net_r,
        "mfe_R": 1.0,
        "mae_R": 0.5,
        "checkpoint_close_R": {str(minute): 0.1 for minute in MODULE.CHECKPOINTS_MIN},
        "features": {feature: float(index) for feature in MODULE.NUMERIC_FEATURES},
    }


def test_readiness_requires_balanced_windows_sides_and_labels() -> None:
    events = []
    for index in range(240):
        events.append(event(
            index,
            window=MODULE.WINDOWS[index % 2],
            side="long" if index % 2 == 0 else "short",
            label="TP_FIRST" if index % 4 < 2 else "SL_FIRST",
            net_r=2.0 if index % 4 < 2 else -0.5,
        ))
    prior = [row for row in events if row["window"] == MODULE.WINDOWS[0]]
    second = [row for row in events if row["window"] == MODULE.WINDOWS[1]]
    drift = {"numeric": MODULE.numeric_drift(prior, second)}
    report = MODULE.readiness(events, drift)
    assert report["ready_for_meta_labeler_design"] is True
    assert report["next"] == "PURGED_WALK_FORWARD_META_LABELER"


def test_aligned_paths_groups_by_window_side_label() -> None:
    rows = [
        event(1, window=MODULE.WINDOWS[0], side="long", label="TP_FIRST", net_r=2.0),
        event(2, window=MODULE.WINDOWS[0], side="long", label="TP_FIRST", net_r=2.0),
    ]
    report = MODULE.aligned_paths(rows)
    key = f"{MODULE.WINDOWS[0]}|long|TP_FIRST"
    assert report[key]["events"] == 2
    assert report[key]["checkpoints"]["60"]["mean_close_R"] == 0.1

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "q4r3_route_a_raschke_v3_drift_attribution_inventory.py"
    spec = importlib.util.spec_from_file_location("test_raschke_v3_drift_attribution_inventory_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MODULE = load_module()


def event(
    index: int,
    *,
    window: str,
    side: str,
    label: str,
    feature_value: float,
    net_r: float,
    duration: int = 60,
    mfe: float = 0.2,
    mae: float = 0.6,
):
    return {
        "event_id": f"{window}|BTCUSDT|{side}|{index}",
        "window": window,
        "symbol": "BTCUSDT",
        "side": side,
        "signal_ts": 1_700_000_000_000 + index * 3_600_000,
        "utc_session": "utc_08_15",
        "proximity_pass": True,
        "direction_alignment_pass": True,
        "macd_strength_pass": True,
        "label": label,
        "net_R_0.15": net_r,
        "duration_min": duration,
        "mfe_R": mfe,
        "mae_R": mae,
        "checkpoint_close_R": {str(value): 0.1 for value in MODULE.CHECKPOINTS},
        "features": {"x": feature_value},
    }


def test_rank_auc_orders_positive_above_negative() -> None:
    assert MODULE.rank_auc([3.0, 4.0], [1.0, 2.0]) == 1.0
    assert MODULE.rank_auc([1.0, 2.0], [3.0, 4.0]) == 0.0


def test_feature_attribution_marks_cross_window_stable_direction() -> None:
    rows = []
    for offset, window in enumerate(MODULE.WINDOWS):
        rows.extend(
            event(offset * 20 + index, window=window, side="long", label="TP_FIRST", feature_value=10 + index, net_r=1.8)
            for index in range(4)
        )
        rows.extend(
            event(offset * 20 + 10 + index, window=window, side="long", label="SL_FIRST", feature_value=1 + index, net_r=-0.6)
            for index in range(4)
        )
    report = MODULE.feature_attribution(rows, {"x": {"drift_score": 0.1, "flags": []}})
    top = report["long"][0]
    assert top["stable_candidate"] is True
    assert top["sign_consistent"] is True
    assert top["interpretation"] == "higher_values_favor_tp"


def test_feature_attribution_rejects_direction_reversal() -> None:
    rows = []
    rows.extend(event(index, window=MODULE.WINDOWS[0], side="short", label="TP_FIRST", feature_value=10 + index, net_r=1.8) for index in range(4))
    rows.extend(event(10 + index, window=MODULE.WINDOWS[0], side="short", label="SL_FIRST", feature_value=1 + index, net_r=-0.6) for index in range(4))
    rows.extend(event(20 + index, window=MODULE.WINDOWS[1], side="short", label="TP_FIRST", feature_value=1 + index, net_r=1.8) for index in range(4))
    rows.extend(event(30 + index, window=MODULE.WINDOWS[1], side="short", label="SL_FIRST", feature_value=10 + index, net_r=-0.6) for index in range(4))
    report = MODULE.feature_attribution(rows, {"x": {"drift_score": 0.1, "flags": []}})
    top = report["short"][0]
    assert top["stable_candidate"] is False
    assert top["sign_consistent"] is False


def test_sample_gap_plan_reports_exact_deficits() -> None:
    rows = []
    for index in range(66):
        rows.append(event(index, window=MODULE.WINDOWS[0], side="long", label="TP_FIRST" if index < 10 else "TIMEOUT", feature_value=1.0, net_r=0.1))
    for index in range(89):
        rows.append(event(100 + index, window=MODULE.WINDOWS[1], side="short", label="SL_FIRST" if index < 20 else "TIMEOUT", feature_value=1.0, net_r=-0.1))
    plan = MODULE.sample_gap_plan(rows)
    assert plan["current"]["events"] == 155
    assert plan["deficits"]["events"] == 45
    assert plan["deficits"]["prior_window"] == 14
    assert plan["deficits"]["second_window"] == 0
    assert plan["deficits"]["tp"] == 20
    assert plan["deficits"]["sl"] == 10


def test_inventory_is_manifest_only_and_excludes_reserved(tmp_path: Path) -> None:
    safe = tmp_path / "archive_history"
    reserved = tmp_path / "third_holdout"
    consumed = tmp_path / "oos_a2" / "frozen_pre30d"
    safe.mkdir(parents=True)
    reserved.mkdir(parents=True)
    consumed.mkdir(parents=True)
    for symbol in MODULE.SYMBOLS:
        (safe / f"{symbol}_1m_history.json").write_text("{}")
        (reserved / f"{symbol}_1m_final.json").write_text("{}")
        (consumed / f"{symbol}_1m_90d_pre30d.json").write_text("{}")
    report = MODULE.inventory_history(tmp_path)
    assert report["manifest_only"] is True
    assert report["contract"]["file_contents_read"] is False
    assert len(report["full_symbol_candidate_groups"]) == 1
    assert report["full_symbol_candidate_groups"][0]["directory"] == "archive_history"
    assert report["excluded"]["already_consumed"] == 5
    assert report["excluded"]["reserved_token:third"] == 5


def test_path_mechanism_detects_entry_timing_failure() -> None:
    rows = [
        event(index, window=MODULE.WINDOWS[1], side="short", label="SL_FIRST", feature_value=1.0, net_r=-0.6, duration=60, mfe=0.1)
        for index in range(6)
    ]
    rows.extend(
        event(20 + index, window=MODULE.WINDOWS[1], side="short", label="TIMEOUT", feature_value=1.0, net_r=0.1, duration=480, mfe=0.4)
        for index in range(2)
    )
    report = MODULE.path_mechanism(rows)
    assert report[MODULE.WINDOWS[1]]["short"]["dominant_mechanism"] == "entry_timing_failure"
    assert report[MODULE.WINDOWS[1]]["short"]["early_sl_120m_pct"] == 100.0

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import numpy as np
import pandas as pd


def load_module():
    path = Path(os.environ["R7A4D2_CHART_FORENSICS"])
    spec = importlib.util.spec_from_file_location("chart_forensics", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_frame(length: int = 640) -> pd.DataFrame:
    x = np.arange(length, dtype=float)
    close = 100.0 + x * 0.02 + np.sin(x / 9.0) * 0.3
    open_ = close - np.sin(x / 7.0) * 0.05
    high = np.maximum(open_, close) + 0.2
    low = np.minimum(open_, close) - 0.2
    volume = 1000.0 + (x % 17) * 10.0
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "__timestamp": x,
        }
    )


def outcome(robust: bool, net: float) -> dict:
    return {
        "robust": robust,
        "negative": not robust,
        "net_per_axis_cell_pct": net,
        "expectancy_r": 1.0 if robust else -1.0,
    }


def test_chart_features_ignore_future_bars() -> None:
    module = load_module()
    frame = synthetic_frame()
    baseline = module.chart_features(frame, 400)
    changed = frame.copy()
    changed.loc[401:, ["open", "high", "low", "close", "volume"]] *= 50.0
    assert module.chart_features(changed, 400) == baseline


def test_simple_rule_finds_stable_pre_entry_separator() -> None:
    module = load_module()
    rows = []
    for index in range(12):
        robust = index < 8
        value = -2.0 - index * 0.1 if robust else 1.0 + index * 0.1
        rows.append(
            {
                "candidate_id": f"c{index}",
                "source_path": f"source{index % 4}",
                "features": {"ret_30_pct": value},
                "outcome": outcome(robust, 0.2 if robust else -0.2),
            }
        )
    rule = module.search_best_rule(rows, ["ret_30_pct"], min_support=6, min_sources=3)
    assert rule is not None
    assert len(rule["conditions"]) == 1
    assert rule["conditions"][0]["feature"] == "ret_30_pct"
    assert rule["conditions"][0]["op"] == "<="
    assert rule["metrics"]["robust_precision"] == 1.0
    assert rule["metrics"]["robust_recall"] == 1.0


def test_forward_outcome_fields_are_not_gate_features() -> None:
    module = load_module()
    forbidden = module.FORWARD_FORBIDDEN_TOKENS
    assert len(module.FEATURE_NAMES) >= 18
    assert all(not any(token in feature.lower() for token in forbidden) for feature in module.FEATURE_NAMES)


def test_vol_all_negative_can_be_permanently_blocked() -> None:
    rows = [outcome(False, -0.1), outcome(False, -0.2), outcome(False, -0.3), outcome(False, -0.4)]
    assert rows and all(row["negative"] for row in rows)

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def load_module():
    path = Path(os.environ["R7A4D2_MARKET_EXPANSION"])
    spec = importlib.util.spec_from_file_location("market_expansion", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def segment(segment_id: str, source: str, start: int, trend: float, total_return: float, shock: float = 0.0):
    return {
        "segment_id": segment_id,
        "source_path": source,
        "start_row": start,
        "end_row_exclusive": start + 320,
        "metrics": {
            "trend_score": trend,
            "return": total_return,
            "max_drawdown": -shock if shock else -0.01,
            "recovery": shock,
            "shock_score": shock * 2,
        },
    }


def test_regime_matching_is_structural_not_performance_based() -> None:
    module = load_module()
    down = segment("d", "a", 320, -2.0, -0.1)
    up = segment("u", "a", 640, 2.0, 0.1)
    shock = segment("s", "a", 960, 0.1, 0.01, 0.2)
    flat = segment("r", "a", 1280, 0.02, 0.001)
    assert module.regime_match(down, "trend_down", 0.05)
    assert module.regime_match(up, "trend_up", 0.05)
    assert module.regime_match(shock, "shock_recovery", 0.05)
    assert module.regime_match(flat, "range", 0.05)


def test_diverse_take_round_robins_sources() -> None:
    module = load_module()
    rows = [
        segment("a1", "a.json", 320, -3.0, -0.2),
        segment("a2", "a.json", 640, -2.0, -0.1),
        segment("b1", "b.json", 320, -1.5, -0.1),
        segment("b2", "b.json", 640, -1.0, -0.1),
    ]
    selected = module.diverse_take(rows, "trend_down", 3)
    assert [row["source_path"] for row in selected[:2]] == ["a.json", "b.json"]
    assert len(selected) == 3


def test_signal_selection_caps_each_segment_and_round_robins() -> None:
    module = load_module()
    rows = []
    for segment_id in ("s1", "s2", "s3"):
        for bar in range(8):
            rows.append({"segment_id": segment_id, "bar_index": bar, "candidate_id": f"{segment_id}:{bar}"})
    selected = module.select_signals(rows, 12)
    counts = {}
    for row in selected:
        counts[row["segment_id"]] = counts.get(row["segment_id"], 0) + 1
    assert len(selected) == 12
    assert counts == {"s1": 4, "s2": 4, "s3": 4}


def test_bucket_specifications_require_one_strategy_and_regime() -> None:
    module = load_module()
    plan = {
        "stress_candidates": [
            {"bucket": "baseline_trend_down", "strategy_id": "alpha_combo", "regime": "trend_down"},
            {"bucket": "grid_rebalance_range", "strategy_id": "grid_rebalance", "regime": "range"},
            {"bucket": "scalp_snap_trend_up", "strategy_id": "scalp_snap", "regime": "trend_up"},
            {"bucket": "vol_spike_fade_shock_recovery", "strategy_id": "vol_spike_fade", "regime": "shock_recovery"},
        ]
    }
    specs, blockers = module.bucket_specifications(plan)
    assert blockers == []
    assert specs["baseline_trend_down"]["strategy_id"] == "alpha_combo"
    assert specs["grid_rebalance_range"]["regime"] == "range"

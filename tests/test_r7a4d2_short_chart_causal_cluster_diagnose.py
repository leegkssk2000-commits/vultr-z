from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import numpy as np


def load_module():
    path = Path(os.environ["R7A4D2_CAUSAL_CLUSTER"])
    spec = importlib.util.spec_from_file_location("causal_cluster", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def outcome(robust: bool, net: float, expectancy: float) -> dict:
    return {
        "robust": robust,
        "salvage_positive": net > 0 and expectancy > 0,
        "negative": net <= 0 or expectancy <= 0,
        "net_per_axis_cell_pct": net,
        "expectancy_r": expectancy,
    }


def row(candidate_id: str, source: str, values: list[float], robust: bool, net: float) -> dict:
    module = load_module()
    return {
        "candidate_id": candidate_id,
        "source_path": source,
        "symbol": source.upper(),
        "features": dict(zip(module.BASELINE_CLUSTER_FEATURES, values)),
        "outcome": outcome(robust, net, 1.0 if robust else -1.0),
    }


def test_geometry_relation_classifies_fill_cross() -> None:
    module = load_module()
    assert module.geometry_relation(99.0, 101.0, 98.0) == "RAW_GEOMETRY_VALID"
    assert module.geometry_relation(97.5, 101.0, 98.0) == "FILL_AT_OR_BELOW_RAW_TP"
    assert module.geometry_relation(101.5, 101.0, 98.0) == "FILL_AT_OR_ABOVE_RAW_STOP"


def test_rebased_short_geometry_is_valid() -> None:
    module = load_module()
    result = module.rebased_geometry(fill=97.5, signal_entry=100.0, raw_stop=101.0)
    assert result["geometry_ok"] is True
    assert result["tp"] < 97.5 < result["stop"]


def test_json_safe_normalizes_numpy_scalars_recursively() -> None:
    module = load_module()
    raw = {
        "flag": np.bool_(True),
        "count": np.int64(3),
        "score": np.float64(1.25),
        "array": np.asarray([1, 2], dtype=np.int64),
    }
    normalized = module.json_safe(raw)
    assert normalized == {"flag": True, "count": 3, "score": 1.25, "array": [1, 2]}
    assert json.loads(json.dumps(normalized)) == normalized


def test_unsupervised_cluster_finds_separated_core() -> None:
    module = load_module()
    rows = [
        row("a1", "s1", [-0.10, 0.3, -0.8, 0.2, 0.1, -0.4], True, 0.2),
        row("a2", "s2", [-0.11, 0.4, -0.9, 0.2, 0.1, -0.3], True, 0.2),
        row("a3", "s3", [-0.12, 0.2, -0.7, 0.3, 0.2, -0.4], True, 0.2),
        row("b1", "s1", [0.20, 2.0, 0.3, 0.6, 0.8, 0.5], False, -0.2),
        row("b2", "s2", [0.25, 2.2, 0.4, 0.7, 0.9, 0.6], False, -0.2),
        row("b3", "s3", [0.30, 1.8, 0.2, 0.5, 0.7, 0.4], False, -0.2),
    ]
    result = module.baseline_cluster_diagnosis(rows)
    classes = {cluster["classification"] for cluster in result["clusters"]}
    assert "S_CORE_CLUSTER_CANDIDATE" in classes
    assert "FAILURE_CLUSTER" in classes
    assert result["selected_k"] in {2, 3}


def test_vol_component_plan_is_observer_only() -> None:
    module = load_module()
    source = " ".join([
        "vol_spike", "atr_spike", "trend_stretch_pct", "strong_up_peak",
        "short_veto", "short_fade_setup", "short_mean_target", "short_scale_in",
    ])
    plan = module.vol_component_plan(source, True)
    assert plan["source_token_parity"] is True
    assert plan["permanent_strategy_regime_block"] is True
    assert plan["failure_learning_connection_allowed"] is False
    assert plan["automatic_repair_or_promotion_allowed"] is False

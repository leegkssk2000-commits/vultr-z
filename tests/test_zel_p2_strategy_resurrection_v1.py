from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from backend.research.zel_strategy_resurrection_v1 import (
    StrategyResurrectionError,
    audit_exact25,
    classify,
    plan_child,
)
from backend.tools.zel_strategy_native_profile_audit_v1 import profile_entry


def policy() -> dict:
    return {
        "minimum_decision_calls": 100,
        "minimum_indicator_valid_pct": 99.0,
        "gate_overfilter_min_block_rate": 0.9,
        "minimum_performance_trades": 20,
        "minimum_profit_factor": 1.2,
        "minimum_positive_net_pct": 0.2,
        "negative_edge_max_net_pct": -1.0,
        "negative_edge_max_profit_factor": 0.9,
        "near_breakeven_min_net_pct": -0.3,
        "near_breakeven_max_net_pct": 0.3,
        "near_breakeven_min_profit_factor": 0.9,
        "loss_shape_worsening_min_r": 0.1,
        "minimum_positive_window_ratio": 0.5,
        "minimum_positive_symbol_ratio": 0.5,
        "maximum_single_symbol_contribution_pct": 70.0,
        "short_edge_min_delta_pct": 1.0,
        "material_net_delta_pct": 0.2,
        "minimum_shadow_survivors": 10,
        "maximum_shadow_survivors": 15,
        "source_ref": "fixture:policy",
        "source_sha256": "f" * 64,
    }


def evidence(strategy_id: str = "alpha_combo", source_sha: str = "a" * 64) -> dict:
    return {
        "strategy_id": strategy_id,
        "strategy_source_sha256": source_sha,
        "source_verified": True,
        "lineage_verified": True,
        "decision_call_count": 1000,
        "indicator_valid_pct": 100.0,
        "pre_gate_opportunity_count": 100,
        "gate_block_count": 20,
        "trade_count": 100,
        "net_return_pct": 5.0,
        "profit_factor": 1.5,
        "average_loss_r": -0.4,
        "control_average_loss_r": -0.4,
        "max_drawdown_pct": 4.0,
        "stress_net_return_pct": 2.0,
        "positive_window_count": 3,
        "window_count": 4,
        "positive_symbol_count": 3,
        "symbol_count": 4,
        "largest_symbol_contribution_pct": 40.0,
        "long_net_return_pct": 5.0,
        "short_observer_net_return_pct": 1.0,
        "duplicate_trade_count": 0,
        "lookahead_violation_count": 0,
        "cost_model_mismatch_count": 0,
        "sample_fingerprint": "b" * 64,
    }


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"source_verified": False}, "SOURCE_OR_LINEAGE_HOLD"),
        ({"decision_call_count": 20}, "DATA_INSUFFICIENT_HOLD"),
        ({"indicator_valid_pct": 0.0}, "INDICATOR_OR_BASIS_DEAD"),
        ({"pre_gate_opportunity_count": 0, "gate_block_count": 0}, "ZERO_MARKET_OPPORTUNITY"),
        ({"trade_count": 0, "gate_block_count": 95}, "GATE_OVERFILTER_ZERO_TRADES"),
        ({"trade_count": 10}, "LOW_SAMPLE_HOLD"),
        ({"net_return_pct": -0.5, "profit_factor": 1.0}, "BAD_ENTRY_ECONOMICS"),
        ({"average_loss_r": -0.7}, "NEAR_PASS_LOSS_SHAPE"),
        ({"net_return_pct": -0.1, "profit_factor": 0.95}, "NEAR_BREAKEVEN_ECONOMICS"),
        ({"net_return_pct": 1.0, "stress_net_return_pct": -1.0}, "COST_FRAGILE"),
        ({"positive_window_count": 1}, "REGIME_CONCENTRATION"),
        ({"positive_symbol_count": 1}, "SYMBOL_CONCENTRATION"),
        ({"long_net_return_pct": -1.0, "short_observer_net_return_pct": 1.0}, "SHORT_ONLY_EDGE"),
        ({"net_return_pct": -5.0, "profit_factor": 0.5}, "NO_GENERALIZABLE_EDGE"),
        ({}, "PASS_CANDIDATE"),
    ],
)
def test_failure_fingerprints_are_cause_specific(updates: dict, expected: str) -> None:
    row = evidence()
    row.update(updates)
    result = classify(row, policy())
    assert result["primary_fingerprint"] == expected
    assert result["parent_mutation_allowed"] is False
    assert result["same_data_auto_promotion_allowed"] is False


def test_zero_trade_cannot_mutate_exit() -> None:
    row = evidence()
    row.update(trade_count=0, gate_block_count=100)
    classified = classify(row, policy())
    assert "gate_structure" in classified["allowed_axes"]
    with pytest.raises(StrategyResurrectionError, match="AXIS_NOT_ALLOWED"):
        plan_child(classified, {
            "axis": "exit_capture",
            "parent_sha256": row["strategy_source_sha256"],
            "child_sha256": "c" * 64,
            "parameters": {"target_r": [1.5, 2.0]},
            "sample_fingerprint": row["sample_fingerprint"],
        })


def test_loss_shape_allows_one_exit_axis_only() -> None:
    row = evidence()
    row["average_loss_r"] = -0.7
    classified = classify(row, policy())
    plan = plan_child(classified, {
        "axis": "time_stop",
        "parent_sha256": row["strategy_source_sha256"],
        "child_sha256": "c" * 64,
        "parameters": {"max_hold_bars": [12, 24, 36]},
        "sample_fingerprint": row["sample_fingerprint"],
    })
    assert plan["change_count"] == 1
    assert plan["parent_immutable"] is True
    with pytest.raises(StrategyResurrectionError, match="EXACTLY_ONE_PARAMETER_REQUIRED"):
        plan_child(classified, {
            "axis": "time_stop",
            "parent_sha256": row["strategy_source_sha256"],
            "child_sha256": "d" * 64,
            "parameters": {"max_hold_bars": [12], "stop_r": [0.75]},
            "sample_fingerprint": row["sample_fingerprint"],
        })


def test_exact25_audit_requires_all_unique_sources() -> None:
    rows = []
    sources = {}
    for index in range(25):
        strategy_id = f"strategy_{index:02d}"
        source_sha = hashlib.sha256(strategy_id.encode()).hexdigest()
        rows.append(evidence(strategy_id, source_sha))
        sources[strategy_id] = source_sha
    result = audit_exact25(rows, policy(), sources)
    assert result["strategy_count"] == 25
    assert result["failure_fingerprint_coverage_pct"] == 100.0
    assert result["p2_complete"] is False
    assert result["parent_strategy_mutation_count"] == 0


def test_native_profile_scans_complete_class_helpers(tmp_path: Path) -> None:
    source = tmp_path / "strategy.py"
    source.write_text(
        """
class TestStrategy:
    def helper(self, frame):
        ema = frame['close'].ewm(span=20).mean()
        return {'action': 'enter', 'side': 'long', 'sl': 1, 'tp': 2} if ema.iloc[-1] > 0 else {'action': 'hold'}
    def decide(self, frame, state=None, risk_action='hold'):
        return self.helper(frame)
""".strip() + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    entry = {
        "strategy_id": "test",
        "family": "TREND",
        "canonical_source": {
            "implementation_path": "strategy.py",
            "callable": "TestStrategy.decide",
            "source_sha256": digest,
        },
    }
    profile = profile_entry(tmp_path, entry)
    assert profile["semantic_scope"] == "COMPLETE_STRATEGY_CLASS_AST"
    assert "ema" in profile["indicator_semantic_tokens"]
    assert profile["supports_explicit_entry"] is True
    assert profile["supports_explicit_hold"] is True

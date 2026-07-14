from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "q4r3_exact25_six_profile_projection_observer.py"
SPEC = importlib.util.spec_from_file_location("q4r3_exact25_six_profile_projection_observer", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_projection_has_exact_six_profiles_when_empty() -> None:
    result = MODULE.project([])
    assert result["profile_count"] == 6
    assert result["total_trigger_count"] == 0
    assert result["total_outcome_join_count"] == 0
    assert [row["method_id"] for row in result["rows"]] == list(MODULE.PROFILES)
    assert all(row["action"] == "hold" for row in result["rows"])


def test_projection_joins_forward_evidence_by_method() -> None:
    events = [
        {
            "event_type": "skill_triggered",
            "position_id": "p1",
            "strategy_id": "vwap_revert",
            "method_id": "scalp_first/revert",
            "skill_id": "SK_ENTRY_LONG_BEAM",
        },
        {
            "event_type": "close_outcome_joined",
            "position_id": "p1",
            "strategy_id": "vwap_revert",
            "method_id": "scalp_first/revert",
            "skill_id": "SK_ENTRY_LONG_BEAM",
            "realized_r": 1.5,
            "fee_bps": 4.0,
            "slippage_bps": 2.0,
            "mfe_r": 2.0,
            "mae_r": -0.25,
            "exposure_time_min": 12.0,
        },
    ]
    result = MODULE.project(events)
    row = next(item for item in result["rows"] if item["method_id"] == "scalp_first/revert")
    assert row["trigger_count"] == 1
    assert row["outcome_join_count"] == 1
    assert row["net_r"] == 1.5
    assert row["avg_r"] == 1.5
    assert row["positive_rate_pct"] == 100.0
    assert row["evidence_ready"] is True
    assert result["profiles_with_trigger"] == 1
    assert result["profiles_with_outcome"] == 1


def test_projection_ignores_unknown_method_and_tracks_blocked() -> None:
    events = [
        {"event_type": "skill_triggered", "method_id": "unknown/x", "position_id": "x"},
        {"event_type": "skill_blocked", "method_id": "intraday/rescue", "position_id": "p2"},
    ]
    result = MODULE.project(events)
    row = next(item for item in result["rows"] if item["method_id"] == "intraday/rescue")
    assert row["trigger_count"] == 0
    assert row["blocked_count"] == 1
    assert result["total_blocked_count"] == 1
    assert result["total_trigger_count"] == 0

from __future__ import annotations

import json
from pathlib import Path

from backend.tools.zel_manual_multiaxis_gemini_v1 import AXES, normalize
from backend.tools.zel_manual_hypothesis_replay_v1 import provider_decisions


def test_gemini_no_action_axis_coverage():
    response = {"status": "PASS", "reviews": [{"axis": axis, "verdict": "NO_ACTION"} for axis in AXES]}
    rows = normalize(response, 6)
    assert len(rows) == 5
    assert {row["axis"] for row in rows} == set(AXES)


def test_single_parameter_catalog_enforced():
    response = {"status": "PASS", "reviews": [
        {"axis": "STRATEGY_ENTRY", "verdict": "PROPOSE_HYPOTHESIS", "hypothesis_id": "s1", "target": "strategy", "parameter": "minimum_trend_score", "values": [0.3, 0.5], "video_source_indexes": [1, 2]},
        {"axis": "BOT_POLICY", "verdict": "PROPOSE_HYPOTHESIS", "hypothesis_id": "b1", "target": "LBot", "parameter": "threshold", "values": [0.6, 0.7], "video_source_indexes": [1, 3]},
        {"axis": "TEAM_POLICY", "verdict": "PROPOSE_HYPOTHESIS", "hypothesis_id": "t1", "target": "team", "parameter": "support_threshold", "values": [0.35, 0.45], "video_source_indexes": [2, 4]},
        {"axis": "SKILL_PROFILE", "verdict": "PROPOSE_HYPOTHESIS", "hypothesis_id": "k1", "target": "skill", "parameter": "skill_id", "values": ["SK_EXIT_MFE_RUNNER", "SK_EXIT_TRAILING_STOP"], "video_source_indexes": [4, 5]},
        {"axis": "ZBOT_PROFILE", "verdict": "PROPOSE_HYPOTHESIS", "hypothesis_id": "z1", "target": "ZBot", "parameter": "disagreement_threshold", "values": [0.2, 0.4], "video_source_indexes": [2, 6]},
    ]}
    rows = normalize(response, 6)
    assert all(row["verdict"] == "PROPOSE_HYPOTHESIS" for row in rows)


def test_joint_provider_approval_requires_both():
    review = {"status": "PASS_AI_REVIEW_ROUTER", "provider_results": {
        "groq": {"artifact": {"review": {"decision": "PASS_TO_REPLAY"}}},
        "workers_ai": {"artifact": {"review": {"decision": "PASS_TO_REPLAY"}}},
    }}
    assert provider_decisions(review) == ("PASS_TO_REPLAY", "PASS_TO_REPLAY", True)
    review["provider_results"]["groq"]["artifact"]["review"]["decision"] = "HOLD"
    assert provider_decisions(review)[2] is False


def test_request_and_registry_are_fail_closed():
    root = Path(__file__).parents[1]
    request = json.loads((root / "backend/research/zel_manual_v3_request_v1.json").read_text())
    registry = json.loads((root / "backend/research/zel_manual_video_registry_v1.json").read_text())
    assert request["same_evidence_reanalysis"] is True
    assert request["new_market_data_claim"] is False
    assert request["promotion_authority"] is False
    assert request["protected_mutations"] == 0
    assert request["execution_allowed"] is False
    assert request["execution_authority"] == "NONE"
    assert request["order_authority"] == "BLOCKED"
    assert request["runtime_bound"] is False
    assert request["shadow_start_allowed"] is False
    assert request["paper_allowed"] is False
    assert request["live_allowed"] is False
    assert len(registry["sources"]) >= 6
    assert len({row["channel"] for row in registry["sources"]}) >= 5
    assert registry["selection_policy"]["view_count_is_discovery_weight_not_truth"] is True

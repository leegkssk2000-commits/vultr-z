from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.q4r3_exact25_skill_active_lineage_audit import (
    EXPECTED_SKILL_COUNT,
    explicit_hook_score,
    method_declared,
    skill_tokens,
    validate_candidate_registry,
    validate_owner_manifest,
)


def make_registry() -> dict:
    ids = [f"SK_TEST_{index:02d}" for index in range(EXPECTED_SKILL_COUNT)]
    skills = []
    for index, skill_id in enumerate(ids):
        skills.append(
            {
                "skill_id": skill_id,
                "label_ko": f"기술{index}",
                "category": "risk_control",
                "state": "observer_only",
                "family_scope": ["L", "M", "O", "S"],
                "required_inputs": ["position_id"],
                "trigger_contract": ["position_id_present"],
                "outputs": ["hold"],
                "performance_metrics": ["net_delta_r"],
                "dependencies": [],
                "conflicts": [],
            }
        )
    return {
        "activation_allowed": False,
        "runtime_mutation_allowed": False,
        "order_authority": "blocked",
        "execution_authority": "none",
        "skills": skills,
    }


def make_manifest() -> dict:
    return {
        "dynamic_fallback_allowed": False,
        "strategies": [
            {
                "strategy_id": f"strategy_{index:02d}",
                "owner_path": f"backend/strategies/strategy_{index:02d}.py",
                "owner_module": f"backend.strategies.strategy_{index:02d}",
                "owner_sha256": "a" * 64,
            }
            for index in range(25)
        ],
    }


def test_registry_requires_exact18_observer_only() -> None:
    rows = validate_candidate_registry(make_registry())
    assert len(rows) == 18
    bad = make_registry()
    bad["skills"][0]["state"] = "candidate_shadow"
    with pytest.raises(ValueError, match="NOT_OBSERVER_ONLY"):
        validate_candidate_registry(bad)


def test_registry_rejects_unknown_dependency() -> None:
    bad = make_registry()
    bad["skills"][0]["dependencies"] = ["SK_UNKNOWN"]
    with pytest.raises(ValueError, match="UNKNOWN_DEPENDENCIES"):
        validate_candidate_registry(bad)


def test_manifest_requires_exact25_and_no_fallback() -> None:
    rows = validate_owner_manifest(make_manifest())
    assert len(rows) == 25
    bad = make_manifest()
    bad["dynamic_fallback_allowed"] = True
    with pytest.raises(ValueError, match="DYNAMIC_FALLBACK_UNSAFE"):
        validate_owner_manifest(bad)


def test_manifest_rejects_duplicate_strategy() -> None:
    bad = make_manifest()
    bad["strategies"][1]["strategy_id"] = bad["strategies"][0]["strategy_id"]
    with pytest.raises(ValueError, match="DUPLICATE_STRATEGY"):
        validate_owner_manifest(bad)


def test_skill_token_hook_scoring_is_deterministic() -> None:
    skill = {
        "skill_id": "SK_EXIT_TRAILING_STOP",
        "label_ko": "트레일링",
        "category": "exit_management",
        "required_inputs": ["position_id", "mfe_r"],
        "trigger_contract": ["trail_trigger_reached"],
        "outputs": ["counterfactual_stop"],
        "performance_metrics": ["giveback_delta_r"],
    }
    tokens = skill_tokens(skill)
    assert "sk_exit_trailing_stop" in tokens
    score, hits = explicit_hook_score(
        {"sk_exit_trailing_stop", "position_id", "mfe_r", "unrelated"}, skill
    )
    assert score >= 102
    assert "position_id" in hits


def test_method_declaration_requires_family_and_subtype() -> None:
    text = "profiles = {'intraday': {'breakout_probe': {}}}"
    assert method_declared("intraday/breakout_probe", text) is True
    assert method_declared("intraday/rescue", text) is False


def test_registry_safety_flags_fail_closed() -> None:
    for field, unsafe in (
        ("activation_allowed", True),
        ("runtime_mutation_allowed", True),
        ("order_authority", "allowed"),
        ("execution_authority", "writer"),
    ):
        bad = make_registry()
        bad[field] = unsafe
        with pytest.raises(ValueError):
            validate_candidate_registry(bad)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.engine.skill_resolver_v2_candidate import (
    SkillResolutionError,
    migrate_requested_ids,
    resolve_skills,
    validate_registry,
)
from tools.q4r3_exact25_skill_registry_v2_audit import EXPECTED_SKILLS


REGISTRY_PATH = Path("backend/contracts/ZOS_SKILL_REGISTRY_v2_candidate.json")


def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def context(**overrides: object) -> dict:
    base = {
        "strategy_id": "trend_rider",
        "method_id": "intraday/breakout_probe",
        "bot_family": "L",
        "regime": "trend_long",
        "deploy_stage": "shadow",
        "market": "BTCUSDT",
        "position_id": "p1",
    }
    base.update(overrides)
    return base


def test_registry_has_exact_required_18_skills() -> None:
    data = registry()
    validate_registry(data)
    ids = {row["skill_id"] for row in data["skills"]}
    assert ids == EXPECTED_SKILLS
    assert len(ids) == 18
    assert data["activation_allowed"] is False
    assert data["order_authority"] == "blocked"
    assert data["execution_authority"] == "none"


def test_legacy_scale_in_never_auto_maps() -> None:
    resolved, blocked = migrate_requested_ids(["SK_POS_SCALE_IN"], registry())
    assert resolved == []
    assert blocked == {
        "SK_POS_SCALE_IN": "ambiguous_legacy_skill_requires_explicit_migration"
    }


def test_deprecated_unambiguous_alias_maps() -> None:
    resolved, blocked = migrate_requested_ids(["SK_POS_TIME_STOP"], registry())
    assert resolved == ["SK_EXIT_TIME_STOP"]
    assert blocked == {}


def test_unknown_family_fails_closed() -> None:
    with pytest.raises(SkillResolutionError, match="UNKNOWN_BOT_FAMILY"):
        resolve_skills(["SK_EXIT_TIME_STOP"], context(bot_family="UNKNOWN"), registry=registry())


def test_unknown_skill_is_hold() -> None:
    result = resolve_skills(["SK_NOT_REAL"], context(), registry=registry())
    assert result["state"] == "HOLD"
    assert result["blocked_reason"] == {"SK_NOT_REAL": "missing_in_registry"}
    assert result["runtime_mutation_allowed"] is False


def test_observer_skill_never_becomes_runtime_skill() -> None:
    result = resolve_skills(["SK_EXIT_TIME_STOP"], context(), registry=registry())
    assert result["state"] == "PASS"
    assert result["observer_skill_ids"] == ["SK_EXIT_TIME_STOP"]
    assert result["candidate_shadow_skill_ids"] == []
    assert result["order_enabled"] is False


def test_conflicting_beams_are_blocked() -> None:
    result = resolve_skills(
        ["SK_ENTRY_LONG_BEAM", "SK_ENTRY_SHORT_BEAM"],
        context(bot_family="O"),
        registry=registry(),
    )
    assert result["state"] == "HOLD"
    assert set(result["blocked_skill_ids"]) == {
        "SK_ENTRY_LONG_BEAM",
        "SK_ENTRY_SHORT_BEAM",
    }


def test_loss_add_requires_risk_dependencies() -> None:
    result = resolve_skills(["SK_ADD_WATER_ADD"], context(), registry=registry())
    assert result["state"] == "HOLD"
    assert result["blocked_reason"]["SK_ADD_WATER_ADD"].startswith(
        "missing_dependencies:"
    )


def test_loss_add_with_all_dependencies_remains_observer_only() -> None:
    result = resolve_skills(
        [
            "SK_ADD_WATER_ADD",
            "SK_RISK_LOSS_CAP",
            "SK_RISK_EXPOSURE_LIMITER",
            "SK_RISK_LIQUIDATION_BUFFER_GUARD",
        ],
        context(),
        registry=registry(),
    )
    assert result["state"] == "PASS"
    assert set(result["observer_skill_ids"]) == {
        "SK_ADD_WATER_ADD",
        "SK_RISK_LOSS_CAP",
        "SK_RISK_EXPOSURE_LIMITER",
        "SK_RISK_LIQUIDATION_BUFFER_GUARD",
    }
    assert result["order_authority"] == "blocked"


def test_registry_relationships_reference_known_ids() -> None:
    data = registry()
    ids = {row["skill_id"] for row in data["skills"]}
    for row in data["skills"]:
        assert set(row.get("dependencies", [])) <= ids
        assert set(row.get("conflicts", [])) <= ids

from __future__ import annotations

from pathlib import Path

from tools.q4r3_exact25_skill_registry_static_audit import (
    REQUIRED_SKILL_IDS,
    SNAPSHOT_ROOT,
    audit,
    resolver_ast_findings,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_inputs_exist() -> None:
    assert (
        REPO_ROOT
        / SNAPSHOT_ROOT
        / "backend/contracts/ZOS_SKILL_REGISTRY_v1.json"
    ).is_file()
    assert (
        REPO_ROOT
        / SNAPSHOT_ROOT
        / "backend/engine/skill_resolver.py"
    ).is_file()


def test_current_registry_is_not_binding_ready() -> None:
    result = audit(REPO_ROOT)
    assert result["state"] == "VIOLATION"
    assert result["action"] == "hold"
    assert result["registry"]["skill_count"] > 0
    assert result["registry"]["missing_required_skill_ids"]
    assert set(result["registry"]["missing_required_skill_ids"]).issubset(
        REQUIRED_SKILL_IDS
    )
    assert (
        "SKILL_REGISTRY_AND_RESOLVER_NOT_BINDING_READY"
        == result["verdict"]
    )


def test_category_enum_mismatch_is_detected() -> None:
    result = audit(REPO_ROOT)
    assert (
        "REGISTRY_RESOLVER_CATEGORY_ENUM_MISMATCH"
        in result["critical_findings"]
    )
    assert result["resolver"]["prefixed_category_literals"]
    assert result["resolver"]["registry_resolver_category_match"] is False


def test_scale_in_conflation_and_fail_open_paths_are_detected() -> None:
    result = audit(REPO_ROOT)
    assert result["resolver"]["generic_scale_in_uses_allow_dca"] is True
    assert result["resolver"]["unknown_family_defaults_to_l"] is True
    assert result["resolver"]["silent_registry_read_fallback"] is True
    assert (
        "LOSS_DIRECTION_AND_PROFIT_DIRECTION_ADD_CONFLATED"
        in result["major_findings"]
    )


def test_resolver_parser_flags_dead_context_parameters() -> None:
    source = """
def resolve_effective_skills(strategy_doc, bot_dna, regime=None, deploy_stage=None, market=None):
    return {"meta": {"regime": regime, "deploy_stage": deploy_stage, "market": market}}
"""
    result = resolver_ast_findings(source)
    assert set(result["context_parameters"]) == {
        "regime",
        "deploy_stage",
        "market",
    }

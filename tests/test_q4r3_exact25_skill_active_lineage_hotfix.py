from __future__ import annotations

from tools import q4r3_exact25_skill_active_lineage_audit_hotfix as hotfix


def test_all_family_scope_uses_valid_audit_family() -> None:
    assert hotfix._audit_family({"family_scope": ["all"]}) == "L"
    assert hotfix._audit_family({"family_scope": ["M", "S"]}) == "M"


def test_tactical_swing_candidate_is_fail_closed() -> None:
    payload = hotfix._load_tactical_candidate()
    assert payload["method_id"] == "tactical_swing/continuation"
    assert payload["profile_state"] == "candidate_declaration_only"
    assert payload["observer_only"] is True
    assert payload["activation_allowed"] is False
    assert payload["runtime_mutation_allowed"] is False
    assert payload["order_authority"] == "blocked"
    assert payload["execution_authority"] == "none"
    assert payload["runtime_trigger_proven"] is False
    assert payload["runtime_outcome_join_proven"] is False


def test_tactical_swing_declaration_is_candidate_backed() -> None:
    assert hotfix.method_declared("tactical_swing/continuation", "") is True

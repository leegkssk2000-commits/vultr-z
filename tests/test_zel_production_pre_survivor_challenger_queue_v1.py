from __future__ import annotations

from backend.production.zel_production_pre_survivor_challenger_queue_v1 import queue_tick

POLICY = {
    "schema_version": "zel.production_pre_survivor_challenger_queue_policy.v1",
    "mode": "PAPER",
    "input_path": "/tmp/in.json",
    "output_path": "/tmp/out.json",
    "proposal_policy_path": "/tmp/proposal.json",
    "challenger_evidence_path": "/tmp/evidence.json",
    "reference_feedback_path": "/tmp/reference.json",
    "incumbent_path": "/tmp/incumbent.json",
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
    "source_code_mutation_allowed": False,
    "self_modification_allowed": False,
}

SAFETY = {
    "selection_authority": False,
    "promotion_authority": False,
    "execution_authority": "NONE",
    "order_authority": "BLOCKED",
    "live_trade_authority": "BLOCKED",
    "exchange_order_submitted": False,
}


def proposal(family: str, template: str, mechanism: str) -> dict:
    return {
        "family_id": family,
        "template_id": template,
        "economic_mechanism": mechanism,
        "required_sources": ["basis", "open_interest"],
        "source_ready": True,
        "template_ready": True,
        **SAFETY,
    }


def current(*rows: dict) -> dict:
    return {
        "state": "PASS_PRE_SURVIVOR_NEXT_HYPOTHESIS_SOURCE_READY",
        "proposals": list(rows),
        "receipt_sha256": "a" * 64,
        **SAFETY,
    }


def test_queue_preserves_prior_and_adds_distinct_candidate_until_budget() -> None:
    first = queue_tick(
        POLICY,
        current=current(proposal("basis_a", "basis_oi_deleveraging_v1", "A")),
        previous=None,
        evidence=None,
        reference={"family_id": "funding_volume_elasticity", **SAFETY},
        incumbent=None,
        candidate_budget=2,
        now_ms=1,
    )
    second = queue_tick(
        POLICY,
        current=current(proposal("basis_b", "basis_oi_deleveraging_v1", "B")),
        previous=first,
        evidence=None,
        reference={"family_id": "funding_volume_elasticity", **SAFETY},
        incumbent=None,
        candidate_budget=2,
        now_ms=2,
    )
    assert second["state"] == "PASS_PRE_SURVIVOR_NEXT_HYPOTHESIS_SOURCE_READY"
    assert second["queue_family_ids"] == ["basis_a", "basis_b"]
    assert second["proposal_count"] == 2
    assert second["selection_authority"] is False
    assert second["execution_authority"] == "NONE"
    assert second["order_authority"] == "BLOCKED"


def test_queue_drops_terminal_reject_and_fills_with_new_candidate() -> None:
    previous = queue_tick(
        POLICY,
        current=current(
            proposal("old_bad", "basis_oi_deleveraging_v1", "OLD"),
            proposal("keep_me", "funding_l2_inventory_exhaustion_v1", "KEEP"),
        ),
        previous=None,
        evidence=None,
        reference={"family_id": "reference", **SAFETY},
        incumbent=None,
        candidate_budget=2,
        now_ms=1,
    )
    evidence = {
        "challengers": [{"family_id": "old_bad", "admission_state": "REJECT_AI_ADMISSION_ECONOMIC_EDGE"}],
        **SAFETY,
    }
    row = queue_tick(
        POLICY,
        current=current(proposal("new_family", "basis_oi_deleveraging_v1", "NEW")),
        previous=previous,
        evidence=evidence,
        reference={"family_id": "reference", **SAFETY},
        incumbent=None,
        candidate_budget=2,
        now_ms=2,
    )
    assert row["queue_family_ids"] == ["keep_me", "new_family"]
    assert row["terminal_family_ids_dropped"] == ["old_bad"]


def test_queue_excludes_reference_and_research_incumbent() -> None:
    row = queue_tick(
        POLICY,
        current=current(
            proposal("reference", "basis_oi_deleveraging_v1", "R"),
            proposal("incumbent", "funding_l2_inventory_exhaustion_v1", "I"),
            proposal("fresh", "basis_oi_deleveraging_v1", "F"),
        ),
        previous=None,
        evidence=None,
        reference={"family_id": "reference", **SAFETY},
        incumbent={"family_id": "incumbent", **SAFETY},
        candidate_budget=2,
        now_ms=3,
    )
    assert row["queue_family_ids"] == ["fresh"]


def test_queue_deduplicates_exact_proposal_identity() -> None:
    p = proposal("same", "basis_oi_deleveraging_v1", "M")
    row = queue_tick(
        POLICY,
        current=current(p, dict(p)),
        previous=None,
        evidence=None,
        reference={"family_id": "reference", **SAFETY},
        incumbent=None,
        candidate_budget=2,
        now_ms=4,
    )
    assert row["proposal_count"] == 1

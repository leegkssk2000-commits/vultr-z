from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[0]))
try:
    import r7a1a6c6b_writer_count_contract_correction as m
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
    import r7a1a6c6b_writer_count_contract_correction as m


def valid_prior():
    return {
        "official_stage": "R7.A1A6C6",
        "state": "HOLD",
        "blocker_count": 2,
        "blockers": sorted(m.EXPECTED_BLOCKERS),
        "prior_c5_valid": True,
        "writer_binding_valid": True,
        "canonical_route_bound": True,
        "telegram_binding_valid": True,
        "final_http_local_exact_parity": True,
        "protected_change_count": 0,
        "caddyfile_change_count": 0,
        **{key: 0 for key in m.MUTATION_KEYS},
    }


def test_contract_valid():
    contract = {
        "official_stage": "R7.A1A6C6B",
        "read_only": True,
        "writer_count_projection_required": False,
        "writer_binding_required": True,
        "runtime_mutation_allowed": False,
    }
    assert m.contract_valid(contract)
    assert not m.contract_valid(dict(contract, writer_count_projection_required=True))


def test_prior_false_positive_valid_exact_only():
    assert m.prior_false_positive_valid(valid_prior())
    bad = valid_prior()
    bad["blockers"] = bad["blockers"] + ["OTHER"]
    bad["blocker_count"] = 3
    assert not m.prior_false_positive_valid(bad)


def test_prior_rejects_missing_binding_or_mutation():
    bad = valid_prior()
    bad["writer_binding_valid"] = False
    assert not m.prior_false_positive_valid(bad)
    bad = valid_prior()
    bad["route_mutation_count"] = 1
    assert not m.prior_false_positive_valid(bad)


def test_boundary_prefers_current_exact_proof():
    current = valid_prior()
    archived = valid_prior()
    selected, source = m.select_boundary_prior(current, archived)
    assert selected is current
    assert source == "current_c6_status"


def test_boundary_falls_back_to_immutable_archive_after_c6_rerun():
    current = {
        "official_stage": "R7.A1A6C6",
        "state": "HOLD",
        "blocker_count": 1,
        "blockers": ["TELEGRAM_ZERO_EPOCH_SEMANTICS_FAILED:REAL_ORDER_ENABLED_NOT_FALSE"],
    }
    archived = valid_prior()
    selected, source = m.select_boundary_prior(current, archived)
    assert selected is archived
    assert source == "immutable_c6_status_before_correction"


def test_boundary_rejects_when_neither_receipt_is_exact():
    selected, source = m.select_boundary_prior({}, {"state": "HOLD"})
    assert selected == {}
    assert source == "none"


def test_corrected_semantic_disables_projection_writer_count_requirement():
    seen = []

    def base(payload, require_writer_counts):
        seen.append(require_writer_counts)
        return True, []

    assert m.corrected_semantic(base, {"closed": 0}, True) == (True, [])
    assert seen == [False]

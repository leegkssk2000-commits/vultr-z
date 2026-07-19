from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import r7a1a6c6_exact_semantic_stability_verify as m


def test_contract_and_prior_validation():
    contract = {
        "official_stage": "R7.A1A6C6",
        "read_only": True,
        "route_mutation_allowed": False,
        "service_mutation_allowed": False,
        "writer_timer_mutation_allowed": False,
        "surface_target_mutation_allowed": False,
        "telegram_command_required": False,
    }
    assert m.contract_valid(contract)
    assert not m.contract_valid(dict(contract, route_mutation_allowed=True))
    prior = {
        "official_stage": "R7.A1A6C5",
        "state": "PASS",
        "blocker_count": 0,
        "writer_binding_valid": True,
        "canonical_route_bound": True,
        "final_http_local_exact_parity": True,
        "protected_change_count": 0,
        "rollback_performed": False,
    }
    assert m.prior_valid(prior)
    assert not m.prior_valid(dict(prior, canonical_route_bound=False))


def test_semantic_zero_epoch_is_top_level_and_strict():
    payload = {
        "closed": 0,
        "closed_count": 0,
        "pnl_r": 0.0,
        "rows": [],
        "recent_rows": 0,
        "order_authority": "blocked",
        "execution_authority": "none",
        "real_order_enabled": False,
        "configured_writer_count": 7,
        "active_writer_count": 0,
        "nested": {"closed": 99, "rows": [1]},
    }
    passed, blockers = m.semantic_zero_epoch(payload)
    assert passed and blockers == []
    bad = dict(payload, closed=1)
    passed, blockers = m.semantic_zero_epoch(bad)
    assert not passed and "CLOSED_NOT_ZERO:1.0" in blockers


def test_semantic_requires_authority_and_core_fields():
    passed, blockers = m.semantic_zero_epoch({})
    assert not passed
    assert "CLOSED_FIELD_MISSING" in blockers
    assert "PNL_FIELD_MISSING" in blockers
    assert "ROW_FIELD_MISSING" in blockers
    assert "ORDER_AUTHORITY_NONE" in blockers


def test_route_binding_accepts_only_canonical_marked_block():
    text = """alimi.z-os.vip {
    # Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_BEGIN
    handle /api/view_contract_latest.json {
        root * /var/www/z-os-alimi/api
        rewrite * /view_contract_latest.json
        file_server
    }
    # Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_END
}
"""
    ok, evidence, blockers = m.route_binding(
        text,
        "rewrite * /view_contract_latest.json",
        "rewrite * /q4r3_exact25_shadow_view_contract_latest.json",
    )
    assert ok and not blockers
    assert evidence["canonical_rewrite_count"] == 1


def test_route_binding_rejects_legacy_or_ambiguous():
    legacy = """# Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_BEGIN
handle /api/view_contract_latest.json {
rewrite * /q4r3_exact25_shadow_view_contract_latest.json
}
# Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_END
"""
    ok, _, blockers = m.route_binding(
        legacy,
        "rewrite * /view_contract_latest.json",
        "rewrite * /q4r3_exact25_shadow_view_contract_latest.json",
    )
    assert not ok and "LEGACY_REWRITE_STILL_BOUND" in blockers


def test_fingerprint_detects_atomic_refresh_without_banning_it(tmp_path: Path):
    target = tmp_path / "view.json"
    target.write_text(json.dumps({"v": 1}))
    before = m.fingerprint(target)
    temp = tmp_path / "temp"
    temp.write_text(json.dumps({"v": 2}))
    temp.replace(target)
    after = m.fingerprint(target)
    assert before != after

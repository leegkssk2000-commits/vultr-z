from __future__ import annotations
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import r7a1a6c5_minimal_single_owner_route_correction as m


def test_contract_and_prior_validation():
    contract = {
        "official_stage": "R7.A1A6C5",
        "route_mutation_allowed": True,
        "service_mutation_allowed": False,
        "writer_timer_mutation_allowed": False,
        "rollback_required": True,
    }
    assert m.contract_valid(contract)
    assert not m.contract_valid(dict(contract, service_mutation_allowed=True))
    prior = {
        "official_stage": "R7.A1A6C4",
        "state": "DIAGNOSED",
        "blocker_count": 0,
        "writer_narrowed": True,
        "writer_proof_count": 15,
        "http_origin_exact_match_count": 1,
        "protected_change_count": 0,
    }
    assert m.prior_valid(prior)
    assert not m.prior_valid(dict(prior, writer_proof_count=0))


def test_patch_only_marked_route():
    text = """alimi.z-os.vip {
    # Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_BEGIN
    handle /api/view_contract_latest.json {
        root * /var/www/z-os-alimi/api
        rewrite * /q4r3_exact25_shadow_view_contract_latest.json
        file_server
    }
    # Q4R3_EXACT25_VIEW_CONTRACT_ROUTE_END
}
"""
    patched, count = m.patch_caddy(text, "rewrite * /q4r3_exact25_shadow_view_contract_latest.json", "rewrite * /view_contract_latest.json")
    assert count == 1
    assert "rewrite * /view_contract_latest.json" in patched
    assert "q4r3_exact25_shadow_view_contract_latest.json" not in patched
    patched2, count2 = m.patch_caddy(patched, "rewrite * /q4r3_exact25_shadow_view_contract_latest.json", "rewrite * /view_contract_latest.json")
    assert count2 == 0 and patched2 == patched


def test_patch_rejects_unmarked_or_ambiguous_route():
    bad = "rewrite * /q4r3_exact25_shadow_view_contract_latest.json\n"
    try:
        m.patch_caddy(bad, "rewrite * /q4r3_exact25_shadow_view_contract_latest.json", "rewrite * /view_contract_latest.json")
    except RuntimeError as exc:
        assert "ROUTE_MARKER_COUNT_INVALID" in str(exc)
    else:
        raise AssertionError("expected failure")


def test_semantic_zero_epoch_top_level_only():
    ok = {"closed": 0, "closed_count": 0, "pnl_r": 0.0, "rows": [], "recent_rows": 0, "order_authority": "blocked", "execution_authority": "none", "real_order_enabled": False, "nested": {"closed": 99}}
    passed, blockers = m.semantic_zero_epoch(ok)
    assert passed and not blockers
    bad = dict(ok, closed=1)
    passed, blockers = m.semantic_zero_epoch(bad)
    assert not passed and blockers


def test_fingerprint_detects_legitimate_atomic_change(tmp_path: Path):
    path = tmp_path / "view.json"
    path.write_text(json.dumps({"v": 1}))
    before = m.fingerprint(path)
    temp = tmp_path / "temp"
    temp.write_text(json.dumps({"v": 2}))
    temp.replace(path)
    after = m.fingerprint(path)
    assert before != after

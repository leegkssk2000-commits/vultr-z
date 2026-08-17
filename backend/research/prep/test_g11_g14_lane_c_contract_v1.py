import json
from pathlib import Path

P = Path(__file__).with_name('g11_g14_lane_c_contract_v1.json')


def load_contract():
    return json.loads(P.read_text())


def test_authority_is_fail_closed():
    d = load_contract()
    a = d['authority']
    assert a['selection_authority'] is False
    assert a['promotion_authority'] is False
    assert a['execution_authority'] == 'NONE'
    assert a['order_authority'] == 'BLOCKED'
    assert a['live_trade_authority'] == 'BLOCKED'
    assert a['exchange_order_submitted'] is False
    assert a['protected_mutations'] == 0


def test_g11_no_allocation_decision():
    d = load_contract()
    assert d['g11']['marker'] == 'G11_PREP_READY'
    assert d['g11']['actual_weight_selection_allowed'] is False
    assert d['g11']['rollback']['deterministic_rehearsal'] is True


def test_g12_shadow_never_activates_and_writer_is_single():
    d = load_contract()
    assert d['g12']['marker'] == 'G12_PREP_READY'
    assert d['g12']['runtime_activation_allowed'] is False
    assert d['g12']['guards']['single_writer'] is True
    assert d['g12']['guards']['duplicate_open'] == 0
    assert d['g12']['guards']['duplicate_close'] == 0
    assert d['g12']['guards']['stale_missing_fail_closed'] is True


def test_g13_canary_is_manifest_only():
    d = load_contract()
    assert d['g13']['marker'] == 'G13_PREP_READY'
    assert d['g13']['canary_days'] == 30
    assert d['g13']['paper_activation_allowed'] is False
    assert d['g13']['mutation_policy'] == 'RESTART_CLOCK_OR_SEPARATE_SEALED_CANARY'


def test_g14_requires_explicit_user_approval():
    d = load_contract()
    assert d['g14']['marker'] == 'G14_PREP_READY'
    assert d['g14']['receipt_only'] is True
    assert d['g14']['explicit_user_approval_required'] is True
    assert d['g14']['live_trade_authority'] == 'BLOCKED'
    assert d['g14']['order_authority'] == 'BLOCKED'
    assert d['final_marker'] == 'FOLLOWUP_PREP_LANE_C_READY'

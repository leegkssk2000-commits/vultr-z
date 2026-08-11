from __future__ import annotations

import copy
import json
from pathlib import Path

from backend.production.zel_production_ai_admission_materializer_v1 import materialize_tick


def policy() -> dict:
    return json.loads(Path('config/zel_production_ai_admission_materializer_v1.json').read_text())


def source_registry() -> dict:
    return json.loads(Path('config/zel_production_source_capability_registry_v1.json').read_text())


def templates() -> dict:
    return json.loads(Path('config/zel_production_ai_admission_template_registry_v1.json').read_text())


def proposal(rows: list[dict]) -> dict:
    return {
        'schema_version':'zel.production_ai_proposal_layer.v1',
        'state':'PASS_AI_PROPOSAL_SOURCE_READY' if any(x.get('source_ready') for x in rows) else 'HOLD_AI_PROPOSAL_SOURCE_BINDING_REQUIRED',
        'proposals':rows,
        'proposal_count':len(rows),
        'source_ready_count':sum(bool(x.get('source_ready')) for x in rows),
        'selection_authority':False,
        'promotion_authority':False,
        'execution_authority':'NONE',
        'order_authority':'BLOCKED',
        'live_trade_authority':'BLOCKED',
        'exchange_order_submitted':False,
        'receipt_sha256':'proposal-fixture'
    }


def row(family: str, required: list[str], ready: bool) -> dict:
    return {
        'proposal_id':family+'-id',
        'family_id':family,
        'required_sources':required,
        'missing_sources':[] if ready else [x for x in required if x in {'liquidation','l2_order_book'}],
        'source_ready':ready,
        'selection_authority':False,
        'promotion_authority':False,
        'execution_authority':'NONE',
        'order_authority':'BLOCKED',
        'live_trade_authority':'BLOCKED'
    }


def bind(reg: dict, source_id: str) -> None:
    reg['sources'][source_id]={
        'proposal_available':True,
        'native_read_bound':True,
        'owner_path':f'backend/production/verified_{source_id}.py',
        'native_endpoint':f'/verified/{source_id}',
        'history_state':'PROSPECTIVE_HISTORY_ACCUMULATING'
    }


def test_current_real_proposals_hold_on_source_binding() -> None:
    p=proposal([
        row('liquidation_cascade_imbalance',['basis','liquidation','open_interest'],False),
        row('order_book_inventory_asymmetry',['basis','l2_order_book'],False),
    ])
    out=materialize_tick(policy(),proposal=p,source_registry=source_registry(),template_registry=templates(),now_ms=1)
    assert out['state']=='HOLD_AI_ADMISSION_SOURCE_BINDING_REQUIRED'
    assert out['contract_count']==0
    assert {x['family_id'] for x in out['blockers']}=={'liquidation_cascade_imbalance','order_book_inventory_asymmetry'}
    assert out['order_authority']=='BLOCKED'


def test_liquidation_source_ready_freezes_threshold_free_contract() -> None:
    reg=copy.deepcopy(source_registry()); bind(reg,'liquidation')
    p=proposal([row('liquidation_cascade_imbalance',['basis','liquidation','open_interest'],True)])
    out=materialize_tick(policy(),proposal=p,source_registry=reg,template_registry=templates(),now_ms=2)
    assert out['state']=='PASS_AI_ADMISSION_CONTRACTS_FROZEN'
    assert out['contract_count']==1
    c=out['contracts'][0]
    assert c['template_id']=='liquidation_cascade_reversion_v1'
    assert c['direction_rule']=='FADE_PRIMARY_EVENT_SIGN'
    assert c['outcome_source']=='ohlcv'
    assert c['numeric_signal_thresholds']==[]
    assert c['parameter_search'] is False
    assert c['selection_authority'] is False and c['promotion_authority'] is False
    assert c['execution_authority']=='NONE' and c['order_authority']=='BLOCKED'


def test_l2_source_ready_freezes_continuation_contract() -> None:
    reg=copy.deepcopy(source_registry()); bind(reg,'l2_order_book')
    p=proposal([row('order_book_inventory_asymmetry',['basis','l2_order_book'],True)])
    out=materialize_tick(policy(),proposal=p,source_registry=reg,template_registry=templates(),now_ms=3)
    c=out['contracts'][0]
    assert c['template_id']=='l2_inventory_pressure_v1'
    assert c['direction_rule']=='FOLLOW_PRIMARY_IMBALANCE_SIGN'
    assert c['event_anchor']=='NATIVE_ORDER_BOOK_UPDATE'
    assert c['negative_controls']==['DIRECTION_REVERSAL','PLUS_ONE_EVENT_DELAY','NO_SIGNAL_PLACEBO']


def test_source_ready_unknown_signature_holds_template_required() -> None:
    p=proposal([row('ohlcv_volume_novel',['ohlcv','volume'],True)])
    out=materialize_tick(policy(),proposal=p,source_registry=source_registry(),template_registry=templates(),now_ms=4)
    assert out['state']=='HOLD_AI_ADMISSION_TEMPLATE_REQUIRED'
    assert out['contract_count']==0
    assert out['blockers'][0]['classification']=='ADMISSION_TEMPLATE_REQUIRED'


def test_no_proposal_is_o1_hold() -> None:
    out=materialize_tick(policy(),proposal=None,source_registry=source_registry(),template_registry=templates(),now_ms=5)
    assert out['state']=='HOLD_AI_ADMISSION_NO_SOURCE_READY_PROPOSAL'
    assert out['contracts']==[]

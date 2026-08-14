from __future__ import annotations

import json
from pathlib import Path

from backend.production import zel_production_a1_jump_liquidity_calibration_v1 as m


def policy():
    return json.loads(Path('config/zel_production_a1_jump_liquidity_calibration_v1.json').read_text())


def fake_rows(symbol: str, start: int, count: int):
    rows=[]
    for i in range(count):
        mid=100.0+i*0.01
        rows.append({
            'schema_version':m.history_gate.ROW_SCHEMA,
            'symbol':symbol,
            'bucket_start_ms':start+i*5000,
            'bucket_end_ms':start+(i+1)*5000,
            'mid_last':mid,
            'trade_quote_notional':1000+i,
            'trade_imbalance':(-1 if i%2 else 1)*0.5,
            'imbalance_top20_mean':(-1 if i%3 else 1)*0.4,
            'bid_qty_top20_last':10+i*0.01,
            'ask_qty_top20_last':11+i*0.01,
            'spread_bps_mean':1+i*0.001,
        })
    return rows


def test_policy_is_source_only_and_no_pnl_selection():
    cfg=m.validate_policy(policy())
    assert cfg['threshold_selection_uses_future_returns'] is False
    assert cfg['threshold_selection_uses_pnl'] is False
    assert cfg['threshold_selection_uses_winrate'] is False
    assert cfg['economic_outcomes_inspected'] is False
    assert cfg['parameter_search'] is False
    assert cfg['economic_replay_allowed_by_calibration'] is False
    assert cfg['falsification_horizons_sec']==[5,15,30,60]
    assert cfg['negative_controls']==['DIRECTION_FLIP','PLUS_ONE_BUCKET_DELAY','TIMESTAMP_SHIFT_PLACEBO','MATCHED_NON_EVENT']


def test_quantile_and_thresholds_are_deterministic():
    cfg=policy()
    rows=fake_rows('BTC-USDT',100_000,100)
    a=m._symbol_thresholds(rows,cfg['threshold_quantiles'])
    b=m._symbol_thresholds(list(reversed(rows)),cfg['threshold_quantiles'])
    assert a==b
    assert a['jump_abs_return_bps_q975']>0
    assert a['trade_quote_notional_q80']>1000
    assert 0<=a['abs_trade_imbalance_q80']<=1
    assert 0<=a['abs_book_imbalance_q80']<=1
    assert a['total_depth_top20_q20']>0
    assert a['spread_bps_q80']>0


def test_source_not_ready_never_creates_threshold_seal(monkeypatch):
    monkeypatch.setattr(m,'_history_gate_receipt',lambda _: {'state':'HOLD_A1_JUMP_SOURCE_HISTORY_ACCUMULATING','calibration_ready':False})
    result=m.build_seal(policy())
    assert result['state']=='HOLD_A1_JUMP_CALIBRATION_SOURCE_NOT_READY'
    assert result['economic_outcomes_inspected'] is False
    assert result['economic_replay_allowed'] is False
    assert 'thresholds_by_symbol' not in result


def test_persisted_seal_is_immutable(tmp_path):
    seal=tmp_path/'seal.json'
    base={
        'schema_version':m.SEAL_SCHEMA,
        'state':'PASS_A1_JUMP_SOURCE_ONLY_CALIBRATION_SEALED',
        'calibration_policy_sha256':'A','history_prefix_sha256':'B','source_template_sha256':'C','autopsy_policy_sha256':'D',
        'economic_replay_allowed':False,
    }
    first=m.persist_or_verify(seal,base)
    second=m.persist_or_verify(seal,base)
    assert first['seal_reused_immutable'] is False
    assert second['seal_reused_immutable'] is True
    changed=dict(base); changed['history_prefix_sha256']='OTHER'
    bad=m.persist_or_verify(seal,changed)
    assert bad['state']=='HOLD_A1_JUMP_CALIBRATION_IMMUTABILITY_MISMATCH'


def test_calibration_prefix_is_exact_six_hours():
    cfg=policy(); start=100_000; count=cfg['calibration_elapsed_ms']//cfg['bucket_ms']
    rows=fake_rows('BTC-USDT',start,count)+fake_rows('ETH-USDT',start,count)
    s,e,selected=m._select_prefix(rows,cfg['symbols'],cfg['calibration_elapsed_ms'])
    assert s==start
    assert e-start==21_600_000
    assert len(selected['BTC-USDT'])==count
    assert len(selected['ETH-USDT'])==count

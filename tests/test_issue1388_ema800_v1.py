"""Artificial lifecycle/integrity tests; no actual source market replay."""
import copy
import json
from pathlib import Path
import pandas as pd
import pytest
from ops import issue1388_alpha_screen_v1 as common
from ops.issue1388_bband_rsi_v1 import bind_bband_decisions, DraftError
from ops.issue1388_ema800_execution_v1 import replay_ema800
from ops.issue1388_ema800_audit_v1 import audit_ema800_result
H=3600000

def bars(n=7):
    return [dict(open_ts_ms=i*H,close_ts_ms=(i+1)*H,available_ts_ms=(i+1)*H,
                 segment_id=0,open=100.,high=102.,low=99.,close=100.,volume=1.) for i in range(n)]

def replay(rows,entry=None,exits=None,funding=None):
    n=len(rows)
    decisions=bind_bband_decisions(rows,entry or [True]+[False]*(n-1),exits or [False]*n)
    return replay_ema800('BTC-USDT',rows,decisions,[] if funding is None else funding,
                         start_ms=0,end_ms=n*H,roundtrip_cost_bps=14.)

def test_current_high_cannot_raise_stop_before_current_low():
    r=bars();r[1].update(high=200.,low=90.,close=100.)
    v=replay(r)
    assert v['trades'][0]['exit_ts_ms']==2*H
    assert v['trades'][0]['exit_reason']=='OPEN_STOP'
    assert v['trades'][0]['exit_price']==100. # gap to known170 stop, never170 phantom fill
    assert v['frozen_roi_ratio']==11.0

def test_prior_received_high_stop_touch():
    r=bars();r[1].update(high=110.) # knownstop93.5 at bar2
    r[2].update(low=92.)
    v=replay(r);assert v['trades'][0]['exit_price']==93.5
    assert v['trades'][0]['exit_reason']=='INTRABAR_STOP_FIRST'

def test_late_high_receipt_not_used_early():
    r=bars();r[1].update(high=200.,available_ts_ms=4*H)
    v=replay(r);assert v['trades'][0]['exit_ts_ms']==4*H
    assert v['trades'][0]['exit_price']==100.

def test_late_exit_dependency_keeps_original_signal():
    r=bars();r[1]['available_ts_ms']=4*H
    v=replay(r,exits=[False,True,False,False,False,False,False]);t=v['trades'][0]
    assert t['exit_ts_ms']==4*H and t['exit_signal_open_ts_ms']==H

def test_stop_first_not_current_high_roi_fill():
    r=bars();r[1].update(high=1200.,low=80.)
    v=replay(r);assert v['trades'][0]['exit_price']==85.
    assert v['trades'][0]['exit_reason']=='INTRABAR_STOP_FIRST'

def test_terminal_touch_is_unresolved_no_end_order():
    r=bars(3);r[-1]['low']=80.
    v=replay(r);assert v['unresolved_end']==1 and not v['trades']
    assert len(v['orders'])==1 and v['terminal_protective_touch']

def test_gap_keeps_open_state_and_paid_cost():
    r=bars();r[2]['segment_id']=1
    v=replay(r);assert v['gap_quarantine'] and v['open_position']
    assert v['paid_trading_cost_bps']==7. and v['unresolved_end']==1

def test_late_protective_touch_not_backdated():
    r=bars();r[1].update(low=80.,available_ts_ms=3*H)
    v=replay(r);assert v['protective_touch_quarantine'] and not v['trades']

def test_signed_funding_boundary_and_fixed_cost():
    r=bars();fund=[dict(symbol='BTC-USDT',fundingTime=H,fundingRate=-.001,markPrice=100.),
                  dict(symbol='BTC-USDT',fundingTime=2*H,fundingRate=-.001,markPrice=100.),
                  dict(symbol='BTC-USDT',fundingTime=3*H,fundingRate=.001,markPrice=100.)]
    v=replay(r,exits=[False,False,True,False,False,False,False],funding=fund)
    assert v['trades'][0]['funding_bps']==0. # interior-10+adverseexit10; entrycreditexcluded
    assert v['trades'][0]['cost_bps']==14.

def market(kind='closed'):
    rows=bars(830)
    offset=common.START_MS-800*H
    for r in rows:
        for k in ('open_ts_ms','close_ts_ms','available_ts_ms'):r[k]+=offset
    rows[801].update(close=110.,high=110.)
    rows[802].update(close=98.,low=98.) # sourcecrossbelow.99 exit
    if kind=='trail':
        rows[802].update(close=105.,high=120.,low=99.)
        rows[803].update(open=100.,high=100.,low=99.,close=100.) # priorstop102 gap100
    end=dict(rows[-1],open_ts_ms=common.END_MS-H,close_ts_ms=common.END_MS,available_ts_ms=common.END_MS,segment_id='END')
    frame=pd.DataFrame(rows+[end]);costs=json.loads(common.COST_PATH.read_bytes())['costs_bps']
    return dict(frames={s:frame.copy() for s in common.SYMBOLS},costs=costs,
                six_funding={s:[dict(symbol=s,fundingTime=t,fundingRate='0.0001',markPrice='100') for t in range(common.START_MS,common.END_MS,8*H)] for s in common.SYMBOLS})

@pytest.mark.parametrize('kind',['closed','trail'])
def test_common_source_model_saved_independent_certificate(kind):
    m=market(kind);v=common.screen(m,common.PROFILES[common.EMA800_ID]);assert len(v['trades'])==6
    audit_ema800_result(v,m)
    assert v['cost_2x']['ExplicitTradingCost_bps']==2*v['cost_1x']['ExplicitTradingCost_bps']
    assert v['cost_2x']['Funding_bps']==v['cost_1x']['Funding_bps']
    entry,exit_=common.ema800_source_decisions(m['frames']['BTC-USDT']);assert entry.sum()==1
    assert entry.iloc[801] and not entry.iloc[800]

@pytest.mark.parametrize('field,value',[('exit_price',999.),('cost_bps',1.),('funding_bps',-999.),('entry_price',999.),('exit_ts_ms',common.END_MS)])
def test_rehashed_saved_trade_tamper_rejected(field,value):
    m=market();v=common.screen(m,common.PROFILES[common.EMA800_ID]);x=copy.deepcopy(v)
    x['trades'][0][field]=value;x['result_sha256']=common.digest({k:v for k,v in x.items() if k!='result_sha256'})
    with pytest.raises(common.ScreenError):audit_ema800_result(x,m)

def test_false_rehashed_density_cannot_start():
    with pytest.raises(common.ScreenError,match='PINNED_PREFLIGHT'):
        common.validate_ema800_preflight({'density_preflight':{'result_sha256':'bad'}},{})

def test_frozen_contract_and_source_constants():
    common.validate_ema800_contract()
    c=json.loads((common.INTAKE_PATH.parent/'EMA800_EXECUTION_CONTRACT.json').read_bytes())
    assert c['ema_period']==800 and c['roi_default_rate']==10. and c['roi_gross_ratio']==11.
    assert c['trailing_stop_ratio']==.85 and c['exit_threshold_ratio']==.99

@pytest.mark.parametrize('field,value',[('candidate_id','fake'),('source_replication',True),('order_authority','LIVE'),('full_consumed',1),('execution_contract_sha256','fake'),('frozen_thesis_sha256','fake'),('funding_hashes',{})])
def test_rehashed_semantics_rejected(field,value):
    m=market();v=common.screen(m,common.PROFILES[common.EMA800_ID]);v[field]=value
    v['result_sha256']=common.digest({k:v for k,v in v.items() if k!='result_sha256'})
    with pytest.raises(common.ScreenError):audit_ema800_result(v,m)

@pytest.mark.parametrize('field',['completed','signals_or_attempts','occupied_rejections','pending_rejections','missing_fill_evidence'])
def test_rehashed_census_rejected(field):
    m=market();v=common.screen(m,common.PROFILES[common.EMA800_ID]);v['census'][field]+=1
    v['result_sha256']=common.digest({k:v for k,v in v.items() if k!='result_sha256'})
    with pytest.raises(common.ScreenError):audit_ema800_result(v,m)

@pytest.mark.parametrize('field,value',[('frozen_roi_ratio',1.1),('frozen_stop_ratio',.75),('signals',999),('occupied_rejections',999),('pending_entry_rejections',999)])
def test_rehashed_both_symbol_and_top_census_rejected(field,value):
    m=market();v=common.screen(m,common.PROFILES[common.EMA800_ID]);v['symbol_accounting']['BTC-USDT'][field]=value
    if field=='signals':v['census']['signals_or_attempts']=sum(x['signals'] for x in v['symbol_accounting'].values())
    if field=='occupied_rejections':v['census']['occupied_rejections']=sum(x['occupied_rejections'] for x in v['symbol_accounting'].values())
    if field=='pending_entry_rejections':v['census']['pending_rejections']=sum(x['pending_entry_rejections'] for x in v['symbol_accounting'].values())
    v['result_sha256']=common.digest({k:v for k,v in v.items() if k!='result_sha256'})
    with pytest.raises(common.ScreenError):audit_ema800_result(v,m)

@pytest.mark.parametrize('field,value',[('gap_quarantine',{}),('protective_touch_quarantine',{}),('terminal_protective_touch',{}),('pending_exit',{}),('open_stop_price',999.)])
def test_fabricated_unresolved_state_rejected(field,value):
    m=market();v=common.screen(m,common.PROFILES[common.EMA800_ID]);v['symbol_accounting']['BTC-USDT'][field]=value
    with pytest.raises(common.ScreenError):audit_ema800_result(v,m)

def test_existing_real_preflight_reused_input_identity():
    proof=json.loads((common.INTAKE_PATH.parent/'EMA800_DENSITY_PROOF.json').read_bytes())
    receipt=copy.deepcopy(proof['receipts']['60']);receipt['order_adapter']=common.PROFILES[common.EMA800_ID]['order_adapter']
    common.validate_ema800_preflight({'density_preflight':proof,'funding_hashes':common.six_funding_hashes(),'execution_contract_sha256':common.EMA800_CONTRACT_SHA256},receipt)

def test_execute_input_start_model_save_audit_persist_artificial(tmp_path,monkeypatch):
    m=market();p=common.PROFILES[common.EMA800_ID];events=[]
    monkeypatch.setattr(common,'current_head',lambda:'a'*40)
    monkeypatch.setattr(common,'validate_activation',lambda *a:{'candidate_id':common.EMA800_ID})
    monkeypatch.setattr(common,'load_market',lambda *a:(events.append('input') or m))
    monkeypatch.setattr(common,'source_receipt',lambda *a:{'receipt_sha256':'synthetic'})
    monkeypatch.setattr(common,'validate_ema800_preflight',lambda *a:events.append('preflight'))
    def record(ref,path,value,head):
        if path=='STARTED.json':events.append('start');assert not (tmp_path/'out').exists()
        else:events.append('persist');assert (tmp_path/'out/RESULT.json').exists()
        return 'b'*40
    monkeypatch.setattr(common,'create_record',record)
    real_screen=common.screen
    def model(*a):events.append('model');assert events[-2]=='start';return real_screen(*a)
    monkeypatch.setattr(common,'screen',model)
    result=common.execute(Path('/synthetic'),tmp_path/'activation',tmp_path/'out')
    assert events==['input','preflight','start','model','persist']
    assert result['state']=='COMPLETE_PERSISTED_AND_AUDITED'
    assert (tmp_path/'out/PERSISTED.json').exists()

def test_before_start_funding_missing_does_not_claim(tmp_path,monkeypatch):
    m=market();m['six_funding'].pop('BTC-USDT')
    monkeypatch.setattr(common,'current_head',lambda:'a'*40)
    monkeypatch.setattr(common,'validate_activation',lambda *a:{'candidate_id':common.EMA800_ID})
    monkeypatch.setattr(common,'load_market',lambda *a:m)
    monkeypatch.setattr(common,'source_receipt',lambda *a:{'receipt_sha256':'synthetic'})
    monkeypatch.setattr(common,'create_record',lambda *a:pytest.fail('claim before real funding validation'))
    monkeypatch.setattr(common,'screen',lambda *a:pytest.fail('model before input validation'))
    with pytest.raises(common.ScreenError,match='FUNDING_REQUIRED_BEFORE_START'):
        common.execute(Path('/synthetic'),tmp_path/'activation',tmp_path/'out')
    assert not (tmp_path/'out').exists()

@pytest.mark.parametrize('kind',['open','gap','terminal','late'])
def test_true_unresolved_certificates_remain_blocked(kind):
    m=market();frame=m['frames']['BTC-USDT'].copy()
    # keep source entry, remove crossbelow, original15% protectives still apply
    existing=frame.iloc[:830].to_dict('records');seed=dict(existing[-1])
    for i in range(830,4520):
        r=dict(seed,open_ts_ms=common.START_MS+(i-800)*H,close_ts_ms=common.START_MS+(i-799)*H,available_ts_ms=common.START_MS+(i-799)*H)
        existing.append(r)
    frame=pd.DataFrame(existing)
    frame.loc[802:,'close']=110.;frame.loc[802:,'high']=110.;frame.loc[802:,'low']=99.
    frame.loc[802:,'open']=110.
    if kind=='gap':frame.loc[810:,'segment_id']=1
    if kind=='terminal':frame.loc[4519,['open','high','low','close']]=[110.,110.,80.,110.];frame.loc[4519,'segment_id']=0
    if kind=='late':frame.loc[805,'low']=80.;frame.loc[805,'available_ts_ms']+=H
    m['frames']={s:frame.copy() for s in common.SYMBOLS}
    v=common.screen(m,common.PROFILES[common.EMA800_ID]);assert v['census']['unresolved_end']==6
    audit_ema800_result(v,m)
    assert v['disposition'].startswith('BLOCKED')

def test_forged_true_late_gap_cannot_hide_earlier_eligible_fill():
    m=market();v=common.screen(m,common.PROFILES[common.EMA800_ID]);x=copy.deepcopy(v)
    for symbol,saved in x['symbol_accounting'].items():
        entry,exits=common.ema800_source_decisions(m['frames'][symbol]);decisions=bind_bband_decisions(m['frames'][symbol].to_dict('records'),entry.tolist(),exits.tolist())
        signal=next(d for d in decisions if d['entry'])
        saved.update(orders=[],trades=[],open_position=None,pending_exit=None,open_stop_price=None,pending_entry=signal,
                     gap_quarantine={'gap_ts_ms':common.END_MS-H,'position':None,'pending_entry':signal,'pending_exit':None},
                     paid_trading_cost_bps=0.,closed_trading_cost_bps=0.,open_entry_cost_bps=0.,unresolved_end=1,signals=1,occupied_rejections=0,pending_entry_rejections=0)
    x.update(trades=[],cost_1x=common.summarize([],1),cost_2x=common.summarize([],2),disposition='BLOCKED_INPUT_GAP_OR_PROTECTIVE_CLOCK')
    x['census'].update(completed=0,signals_or_attempts=6,occupied_rejections=0,pending_rejections=0,gap_quarantined=6,missing_fill_evidence=6,unresolved_end=6)
    x['result_sha256']=common.digest({k:v for k,v in x.items() if k!='result_sha256'})
    with pytest.raises(common.ScreenError,match='PENDING_ENTRY_FIRST_CAUSAL_OPEN'):audit_ema800_result(x,m)

def test_workflow_routes_008_without_density_or_global_lock_change():
    text=(common.ROOT/'.github/workflows/issue1388-internet-alpha-v1.yml').read_text()
    cheap=text.split('  cheap-screen-003:',1)[1];density=text.split('  density-preflight-003:',1)[-1].split('  cheap-screen-003:',1)[0]
    assert "number = '008' if '[issue1388-alpha-screen-8-ema800-1h-v1]'" in cheap
    assert "if number in ('007', '008'):" in cheap
    assert '[issue1388-alpha-screen-8-ema800-1h-v1]' not in density
    assert 'group: a1-global-heavy-economic-evaluator-v1' in cheap
    assert 'cancel-in-progress: false' in cheap

@pytest.mark.parametrize('field,value',[('available_ts_ms',0),('position',{}),('pending_entry',{}),('pending_exit',{})])
def test_rehashed_late_touch_snapshot_tamper_rejected(field,value):
    m=market();frame=m['frames']['BTC-USDT'].copy();frame.loc[802,'low']=80.;frame.loc[802,'available_ts_ms']+=H
    m['frames']={s:frame.copy() for s in common.SYMBOLS}
    v=common.screen(m,common.PROFILES[common.EMA800_ID]);audit_ema800_result(v,m)
    v['symbol_accounting']['BTC-USDT']['protective_touch_quarantine'][field]=value
    v['result_sha256']=common.digest({k:v for k,v in v.items() if k!='result_sha256'})
    with pytest.raises(common.ScreenError):audit_ema800_result(v,m)

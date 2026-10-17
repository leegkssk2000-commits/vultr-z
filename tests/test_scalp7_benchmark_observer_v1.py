"""Non-economic fixtures; original strategy functions are called, never re-tuned."""
from copy import deepcopy
from dataclasses import asdict
import math

import numpy as np
import pandas as pd
import pytest

from backend.research.rebuild import scalp7_positive_lanes_v2 as native
from ops import scalp7_benchmark_observer_v1 as obs

TF = obs.TF


def candles(n=44):
    closes = 100 + np.arange(n) * .03 + np.sin(np.arange(n) / 3)
    return pd.DataFrame([dict(open_ts_ms=i*TF, close_ts_ms=(i+1)*TF,
        available_ts_ms=(i+1)*TF, segment_id='a', open=float(c), high=float(c+1),
        low=float(c-1), close=float(c)) for i, c in enumerate(closes)])


def position():
    return dict(entry_ts_ms=40*TF, side=1, entry_price=101., initial_risk=5.,
        mfe_R=.2, hold_bars=4, stop_price=96., remaining=1.,
        signal=dict(symbol='BTC-USDT', identity=native.SQUEEZE_PARENT,
                    signal_ts_ms=40*TF, signal_open_ts_ms=39*TF,
                    meta=dict(be_arm_r=None, frozen_cost_bps=14.)))


def hrow(i, *, adx=31., strong=True, close=103., low=99.):
    r = dict(open_ts_ms=i*TF, close_ts_ms=(i+1)*TF,
             available_ts_ms=(i+1)*TF, segment_id='a',
             high=max(close, 104.), low=low, close=close, open=103.,
             adx14=adx, g20=102.+i if strong else 99., hi20=140., lo20=80.)
    for n, value in zip(native.LONG_GMMA, [110,108,106,104,102,100]):
        r[f'g{n}'] = value + i
    return r


@pytest.mark.parametrize('values,weak,cross', [([3,2,1],True,False),
    ([3,1,-1],False,True), ([1,-1,-2],False,False), ([-2,-1,1],False,False),
    ([2,0,-1],False,True), ([3,2,0],False,False)])
def test_momentum_predicate_is_observation(values,weak,cross):
    r=obs.momentum_flags(values)
    assert r['positive_weak_predicate'] is weak
    assert r['negative_cross'] is cross


@pytest.mark.parametrize('values', [[1,2], [1,2,float('nan')], [float('inf'),1,0]])
def test_malformed_momentum_is_not_no_trigger(values):
    with pytest.raises(ValueError): obs.momentum_flags(values)


def test_native_momentum_and_exit_are_unchanged():
    h=candles(); b=h.iloc[-1].to_dict(); p=position()
    old_h=h.copy(deep=True); old_p=deepcopy(p)
    before=native.exit_update(p,b,h)
    got=obs.squeeze_observation(p,b,h,before,signal_low=100.)
    assert got['features_asof']['momenta'] == native._last_momenta(h).tolist()
    assert got['native_decision_observed'] == before == native.exit_update(p,b,h)
    assert p==old_p
    pd.testing.assert_frame_equal(h,old_h)


@pytest.mark.parametrize('kind', ['warmup','gap','segment','late','mismatch','side'])
def test_squeeze_integrity_fails_closed(kind):
    h=candles(); p=position(); b=h.iloc[-1].to_dict()
    if kind=='warmup': h=h.iloc[-40:]
    if kind=='gap': h=h.drop(h.index[-5])
    if kind=='segment': h.loc[h.index[-5], 'segment_id']='b'
    if kind=='late': h.loc[h.index[-5], 'available_ts_ms']=100*TF
    if kind=='mismatch': b['close'] += .1
    if kind=='side': p['side']=-1
    with pytest.raises(ValueError): obs.squeeze_observation(p,b,h,{})


@pytest.mark.parametrize('weak_kind', ['ADX','SLOPE'])
def test_hg_native_event_and_state_parity_with_retained_touch(weak_kind):
    a,b=native.HolyGrailState(),native.HolyGrailState(); watcher=obs.HGObserver('BTC-USDT')
    r0=hrow(0); r1=hrow(1); r2=hrow(2,adx=27. if weak_kind=='ADX' else 31., strong=weak_kind!='SLOPE')
    r3=hrow(3,close=108.)
    observations=[]
    for prev,row in [(r0,r1),(r1,r2),(r2,r3)]:
        event=native._hg_event(a,row,prev)
        observed,record=obs.observed_hg_call(watcher,b,row,prev)
        assert event==observed and asdict(a)==asdict(b)
        observations.append(record)
    assert observations[1]['features_asof']['weak_state_retained']
    assert observations[2]['features_asof']['event_after_weak_retention']
    assert observations[2]['features_asof']['weak_bars_since_touch']==1


def test_hg_low_adx_resets_not_a_retained_touch():
    s=native.HolyGrailState(); w=obs.HGObserver('ETH-USDT')
    r0,r1,r2=hrow(0),hrow(1),hrow(2,adx=24.)
    obs.observed_hg_call(w,s,r1,r0)
    _,o=obs.observed_hg_call(w,s,r2,r1)
    assert not o['features_asof']['weak_state_retained'] and s.stage==0
    assert w.touch_ts_ms is None and w.weak_bars_since_touch==0


def test_hg_cold_attached_observer_has_unknown_prior_touch():
    s=native.HolyGrailState(side=1,stage=1,pull_low=99.,pull_high=104.)
    w=obs.HGObserver('BTC-USDT'); _,o=obs.observed_hg_call(w,s,hrow(1,adx=27.),hrow(0))
    assert o['coverage']=='TOUCH_NOT_OBSERVED'
    assert o['features_asof']['weak_bars_since_touch'] is None


def test_hg_duplicate_transition_rejected():
    s=native.HolyGrailState(); w=obs.HGObserver('BTC-USDT')
    r0,r1=hrow(0),hrow(1)
    obs.observed_hg_call(w,s,r1,r0)
    with pytest.raises(ValueError): w.observe(asdict(s),asdict(s),r1,r0,None)


def trade(i=1,net=10.):
    return dict(symbol='BTC-USDT',signal_ts_ms=i*TF,signal_open_ts_ms=(i-1)*TF,
        entry_ts_ms=i*TF,exit_ts_ms=(i+4)*TF,outcome_available_ts_ms=(i+4)*TF,
        gross_bps=net+14.,cost_bps=14.,net_bps=net,regime='TREND_DISPERSED',reason='TIME_STOP')


def observation(t,stamp):
    return dict(symbol=t['symbol'],signal_ts_ms=t['signal_ts_ms'],
        signal_open_ts_ms=t['signal_open_ts_ms'],asof_ts_ms=stamp,
        features_asof=dict(negative_cross=True,below_signal_low=True))


def test_missing_path_is_unknown_not_zero():
    t=trade(); r=obs.join_saved_squeeze([t],[],{})['rows'][0]
    assert r['negative_cross_status']=='UNKNOWN'
    assert r['profit_improvement']=='NOT_MEASURED'


def test_all_saved_winners_and_losers_are_retained_separately():
    a,b=trade(),trade(8,-5.)
    source=deepcopy([a,b])
    r=obs.join_saved_squeeze([a,b],[observation(a,2*TF)],{})
    assert [x['saved_result_label'] for x in r['rows']]==['WIN','LOSS']
    assert r['rows'][0]['negative_cross_status']=='OBSERVED'
    assert r['rows'][1]['negative_cross_status']=='UNKNOWN'
    assert r['saved_trade_count']==2 and [a,b]==source
    assert 'net_bps' not in r['rows'][0].get('features_asof',{})


def test_same_time_exit_not_counted_as_earlier():
    t=trade(); k=obs.observation_key(t)
    r=obs.join_saved_squeeze([t],[observation(t,t['exit_ts_ms'])],{k:True})['rows'][0]
    assert r['negative_cross_before_exit_ts_ms'] is None
    assert r['negative_cross_status']=='NOT_OBSERVED_COMPLETE'


@pytest.mark.parametrize('kind',['duplicate_trade','duplicate_observation','future','unknown_key','bad_exit'])
def test_join_rejects_unbound_observations(kind):
    t=trade(); ts=[t]; os=[observation(t,2*TF)]
    if kind=='duplicate_trade': ts.append(deepcopy(t))
    if kind=='duplicate_observation': os.append(deepcopy(os[0]))
    if kind=='future': os[0]['asof_ts_ms']=10*TF
    if kind=='unknown_key': os[0]['symbol']='ETH-USDT'
    if kind=='bad_exit': t['exit_ts_ms']=0
    with pytest.raises(ValueError): obs.join_saved_squeeze(ts,os,{})


def test_reset_extrema_are_strict_json_serializable():
    import json
    s=native.HolyGrailState();w=obs.HGObserver('BTC-USDT')
    _,r=obs.observed_hg_call(w,s,hrow(1,adx=24),hrow(0))
    json.dumps(r,allow_nan=False)
    assert r['native_state_after']['pull_low'] is None


def source_fixture():
    from ops import scalp7_squeeze_signal_low_successor_v1 as policy
    f=candles(47); p=position(); s=deepcopy(p['signal'])
    s.update(identity=policy.SAVED_OVERLAY, lane='squeeze_break', timeframe_min=30,
             side=1,segment_id='a',stop_price=90.,take_profit_r=None,max_hold_bars=11)
    s['meta'].update(regime='PANIC_DISPERSION', entry_cost_gate=dict(atr_price=2.,min_ratio=4.),
        fallback_stop_atr_mult=2., lifecycle_adapter_parent_identity=native.SQUEEZE_PARENT)
    t=dict(symbol='BTC-USDT',identity=policy.SAVED_OVERLAY,side=1, signal_ts_ms=40*TF,
        signal_open_ts_ms=39*TF,entry_ts_ms=40*TF,exit_ts_ms=44*TF,outcome_available_ts_ms=44*TF,
        gross_bps=24.,cost_bps=14.,net_bps=10.,regime='PANIC_DISPERSION',reason='TIME_STOP',
        signal=s,entry_prices={'BTC-USDT':float(f.iloc[40]['open'])})
    return f,t


def test_source_scan_fixture_uses_native_prefix_without_replay(monkeypatch):
    from ops import scalp7_squeeze_signal_low_successor_v1 as policy
    f,t=source_fixture(); old=deepcopy(t)
    # Fixture-only input admission: not a fabricated 57T receipt or market test.
    monkeypatch.setattr(policy,'scan_saved_trend_triggers',lambda *args:{'fixture_only':True})
    report=obs.scan_saved_squeeze_paths({'BTC-USDT':f},{'trade_rows':[t]})
    assert report['saved_trade_count']==1 and report['new_economic_runs']==0
    assert len(report['callback_observations'])==3
    assert report['rows'][0]['coverage']=='COMPLETE_CALLBACK_PATH'
    assert not report['rows'][0]['signal_low_policy_applies']
    assert old==t


def test_source_scan_gaps_do_not_become_zero(monkeypatch):
    from ops import scalp7_squeeze_signal_low_successor_v1 as policy
    f,t=source_fixture();f=f.drop(f.index[42]).reset_index(drop=True)
    monkeypatch.setattr(policy,'scan_saved_trend_triggers',lambda *args:{'fixture_only':True})
    with pytest.raises(ValueError): obs.scan_saved_squeeze_paths({'BTC-USDT':f},{'trade_rows':[t]})


def test_real_saved_57_requires_actual_price_paths():
    from pathlib import Path
    import json
    import hashlib
    from ops import scalp7_squeeze_signal_low_successor_v1 as policy
    p=Path(__file__).resolve().parents[2]/'evidence/saved_overlay/SQUEEZE_REGIME_OVERLAY_RESULT.json'
    if not p.exists():
        pytest.skip('Optional receipt-bound saved archive not supplied')
    report=json.loads(p.read_text()); unsigned=dict(report); unsigned.pop('receipt_sha256')
    digest=hashlib.sha256((json.dumps(unsigned,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()).hexdigest()
    assert digest==report['receipt_sha256']==policy.SAVED_RECEIPT
    rows=report['trade_rows']
    j=obs.join_saved_squeeze(rows,[],{})
    assert len(j['rows'])==57
    assert all(r['negative_cross_status']=='UNKNOWN' for r in j['rows'])
    with pytest.raises((KeyError,ValueError)):
        obs.scan_saved_squeeze_paths({},report)

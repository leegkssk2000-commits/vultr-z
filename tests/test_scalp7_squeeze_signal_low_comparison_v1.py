"""Synthetic integration tests and SAVED-ledger arithmetic; no new market replay."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import math

import pandas as pd
import pytest

from backend.research.rebuild import scalp7_execution_v2 as engine
from backend.research.rebuild import scalp7_positive_lanes_v2 as parent
from ops import scalp7_squeeze_signal_low_successor_v1 as policy
from ops import scalp7_squeeze_signal_low_comparison_v1 as sut
from research.campaigns.scalp7_20261013.dual_streak_v1.streak_successor_policies import RejectedHGEventReset

TF = 1_800_000


def frame(n=18, trigger=True):
    rows = [dict(open_ts_ms=i*TF, close_ts_ms=(i+1)*TF,
                 available_ts_ms=(i+1)*TF, segment_id='A',
                 open=103., high=104., low=101., close=103.) for i in range(n)]
    rows[0]['low'] = 100.
    if trigger:
        rows[1].update(low=98., close=99.)
        rows[2].update(open=97., high=99., low=96., close=98.)
    return pd.DataFrame(rows)


def signal(i=0, regime='TREND_DISPERSED', symbol='BTC-USDT'):
    return dict(identity=parent.SQUEEZE_PARENT, lane='squeeze_break', symbol=symbol,
                timeframe_min=30, side=1, signal_open_ts_ms=i*TF, signal_ts_ms=(i+1)*TF,
                segment_id='A', stop_price=90., max_hold_bars=11, take_profit_r=None,
                meta=dict(regime=regime, be_arm_r=None, frozen_cost_bps=14.,
                          fallback_stop_atr_mult=2., entry_cost_gate=dict(atr_price=2., min_ratio=4.)))


def windows(end=18*TF):
    return [dict(label='rolling_test', partition='rolling', start_ms=0, end_ms=end)]


def replay(bars=None, signals=None, ws=None):
    bars = frame() if bars is None else bars
    signals = [signal()] if signals is None else signals
    return sut.replay_successor(signals, {'BTC-USDT': bars}, {'BTC-USDT': 14.},
                                windows(len(bars)*TF) if ws is None else ws)


def original(bars, sig=None):
    return engine.replay([signal() if sig is None else sig], {'BTC-USDT': bars},
                         {'BTC-USDT': 14.}, exit_update=parent.exit_update,
                         entry_update=parent.entry_update, identity=parent.SQUEEZE_PARENT)


def strip_label(row):
    r = deepcopy(row)
    r.pop('window_label', None); r.pop('partition', None)
    r['identity'] = parent.SQUEEZE_PARENT
    r['signal']['identity'] = parent.SQUEEZE_PARENT
    r['signal']['meta'].pop('lifecycle_adapter_parent_identity', None)
    r['signal']['meta'].pop(policy.BINDING, None)
    return r


def reference_trade(gross, i, *, cost=14., symbol='BTC-USDT', outcome=None):
    return dict(symbol=symbol, identity='reference', signal_ts_ms=i*TF,
                signal_open_ts_ms=(i-1)*TF, entry_ts_ms=i*TF, exit_ts_ms=(i+1)*TF,
                outcome_available_ts_ms=(i+1)*TF if outcome is None else outcome,
                gross_bps=gross, cost_bps=cost, reason='REFERENCE', partition='rolling')


@pytest.mark.parametrize('path', [p for p in sut.PINS if 'overlay_child' not in p])
def test_exact_original_dependency_bytes(path):
    assert hashlib.sha256((Path(__file__).resolve().parents[1]/path).read_bytes()).hexdigest() == sut.PINS[path]


def test_actual_native_invalidation_next_open_no_fake_signal_low_fill():
    r = replay()
    t = r['trades'][0]
    assert t['reason'] == policy.EXIT_REASON
    assert t['exit_prices']['BTC-USDT'] == 97.
    assert t['exit_ts_ms'] == 2*TF
    assert t['signal']['meta'][policy.BINDING]['low'] == 100.
    assert r['causal_exit_traces'][0]['invalidation_available_ts_ms'] == 2*TF
    assert r['old_candidate_replayed'] is False


def test_future_price_changes_do_not_change_prior_low_binding():
    a, b = frame(), frame()
    b.loc[3:, ['open','high','low','close']] = [190.,191.,189.,190.]
    assert policy.bind_signal_low(signal(), a) == policy.bind_signal_low(signal(), b)
    assert replay(a)['trades'][0] == replay(b)['trades'][0]


def test_panics_original_native_lifecycle_exactly_unchanged():
    bars = frame()
    s = signal(regime='PANIC_DISPERSION')
    assert strip_label(replay(bars, [s])['trades'][0]) == original(bars, s)['trades'][0]


def test_current_bar_stop_precedes_added_exit():
    bars = frame(); bars.loc[1,'low'] = 89.
    r = replay(bars)
    assert r['trades'][0]['reason'] == 'STOP_FIRST'
    assert r['trades'][0]['exit_prices']['BTC-USDT'] == 90.
    assert r['causal_exit_traces'] == []


def test_actual_next_open_gap_stop_wins_and_retains_native_release_clock():
    bars = frame(); bars.loc[2,['open','high','low','close']] = [80.,85.,75.,82.]
    # Second opportunity at the gap open must not bypass native stop occupancy.
    r = replay(bars, [signal(), signal(i=1)])
    assert r['trades'][0]['reason'] == 'OPEN_GAP_STOP'
    assert r['trades'][0]['exit_prices']['BTC-USDT'] == 80.
    assert r['trades'][0]['exit_ts_ms'] == 2*TF
    assert r['next_open_stop_arbitrations'][0]['ownership_released_at_ms'] == 3*TF
    assert r['decisions'][1]['reason'] == 'POSITION_ALREADY_OWNED'
    assert r['next_open_stop_arbitrations'][0]['price_changed'] is False


def test_pending_market_exit_ignores_later_same_bar_low_after_actual_open():
    bars = frame(); bars.loc[2,['open','high','low','close']] = [97.,99.,75.,80.]
    r = replay(bars)
    assert r['trades'][0]['reason'] == policy.EXIT_REASON
    assert r['trades'][0]['exit_prices']['BTC-USDT'] == 97.
    assert r['next_open_stop_arbitrations'] == []


def test_equal_open_stop_retains_original_conservative_stop_timing():
    bars = frame(); bars.loc[2,['open','high','low','close']] = [90.,99.,89.,98.]
    r = replay(bars)
    t = r['trades'][0]
    assert t['reason'] == 'STOP_FIRST'
    assert t['exit_ts_ms'] == 3*TF
    assert t['outcome_available_ts_ms'] == 3*TF
    assert r['decisions'][0]['ownership_until_ms'] == 3*TF


def test_original_max_hold_wins_same_close():
    s = signal(); s['max_hold_bars'] = 1
    assert replay(signals=[s])['trades'][0]['reason'] == 'MAX_HOLD_NEXT_OPEN'


def test_parent_callback_exit_wins_same_close():
    bars, s = frame(), policy.bind_signal_low(signal(), frame())
    pos = dict(signal=s, entry_ts_ms=TF, entry_price=103., initial_risk=13.,
               stop_price=90., side=1, mfe_R=0., hold_bars=1, remaining=1.)
    expect = dict(exit_next_open=True, reason='ORIGINAL_CLOSE')
    assert policy.native_exit_update(pos, bars.to_dict('records')[1], bars.iloc[:2],
                                    parent_callback=lambda *a: expect) == expect


def test_earlier_close_releases_ownership_for_entire_future_opportunity_pool():
    bars = frame()
    r = replay(bars, [signal(), signal(i=2, regime='PANIC_DISPERSION')])
    assert sum(d['state']=='ACCEPTED' for d in r['decisions']) == 2
    control = engine.replay([signal(),signal(i=2,regime='PANIC_DISPERSION')],
        {'BTC-USDT':bars},{'BTC-USDT':14.},exit_update=parent.exit_update,entry_update=parent.entry_update)
    assert control['rejections']['POSITION_ALREADY_OWNED'] == 1
    assert r['trades'][1]['signal_ts_ms'] == 3*TF


def test_full_replay_not_saved_trade_only_counterfactual():
    bars = frame()
    r = replay(bars, [signal(), signal(i=2), signal(i=3)])
    assert len(r['decisions']) == 3
    assert r['window_census']['rolling_test']['signals'] == 3
    assert r['decisions'][2]['reason'] == 'POSITION_ALREADY_OWNED'


def test_no_next_open_remains_unresolved_not_a_free_avoided_loss():
    bars = frame().iloc[:2]
    r = replay(bars)
    assert r['trades'] == [] and len(r['unresolved']) == 1
    report = sut.comparison_report([], [], r, 0, 2*TF)
    assert report['state'] == 'INCOMPLETE_NO_ADOPTION'
    assert report['comparison_complete'] is False
    assert report['accepted_entries'] == 1


def test_gap_retains_ownership_for_later_signals():
    bars = frame().drop(index=2).reset_index(drop=True)
    r = replay(bars, [signal(), signal(i=3)], windows(18*TF))
    assert len(r['unresolved']) == 1
    assert r['decisions'][1]['reason'] == 'POSITION_ALREADY_OWNED'


def test_missing_segment_is_not_synthetic_path():
    bars = frame();bars.loc[2:,'segment_id']='B'
    r = replay(bars)
    assert r['trades'] == [] and len(r['unresolved']) == 1


def test_no_borrowing_next_window_bar():
    r = replay(frame(), [signal()], windows(2*TF))
    assert not r['trades'] and r['unresolved']
    assert not r['next_open_stop_arbitrations']


def test_closed_outcome_at_exclusive_end_is_visible_censored():
    bars = frame();bars.loc[1,'low']=89.
    r = replay(bars, ws=windows(2*TF))
    assert not r['trades'] and len(r['boundary_excluded'])==1
    assert sut.comparison_report([], [], r, 0, 2*TF)['comparison_complete'] is False


def test_late_signal_is_rejected_without_historical_fill():
    s=signal();s['signal_ts_ms']+=1
    r=replay(signals=[s])
    assert not r['trades']
    assert r['decisions'][0]['reason']=='LATE_OBSERVATION_NOT_HISTORICAL_OPEN_FILL'


def test_late_closed_bar_retains_unresolved():
    bars=frame();bars.loc[1,'available_ts_ms']+=1
    r=replay(bars)
    assert not r['trades'] and r['unresolved']


def test_duplicate_opportunities_fail_closed():
    with pytest.raises(ValueError, match='DUPLICATE_OPPORTUNITY'):
        replay(signals=[signal(),signal()])


@pytest.mark.parametrize('change', ['short','timeframe','regime','identity','cost'])
def test_unauthorized_input_change_rejected(change):
    s=signal()
    if change=='short':s['side']=-1
    elif change=='timeframe':s['timeframe_min']=15
    elif change=='regime':s['meta']['regime']='OTHER'
    elif change=='identity':s['identity']='other'
    elif change=='cost':s['meta']['frozen_cost_bps']=15.
    with pytest.raises(ValueError):replay(signals=[s])


def test_independent_windows_do_not_silently_carry_ownership():
    bars=frame(36)
    ws=[dict(label='a',partition='rolling',start_ms=0,end_ms=2*TF),
        dict(label='b',partition='rolling',start_ms=2*TF,end_ms=36*TF)]
    r=replay(bars,[signal(),signal(i=3,regime='PANIC_DISPERSION')],ws)
    assert len(r['unresolved'])==1 and len(r['trades'])==1
    assert r['trades'][0]['window_label']=='b'


def test_overlapping_windows_rejected():
    with pytest.raises(ValueError,match='OVERLAPPING_WINDOWS'):
        replay(ws=windows()+[dict(label='b',partition='rolling',start_ms=TF,end_ms=20*TF)])


def test_simultaneous_outcome_cohorts_do_not_create_artificial_dd():
    rows=[reference_trade(114,1,symbol='BTC-USDT',outcome=3*TF),
          reference_trade(-86,1,symbol='ETH-USDT',outcome=3*TF)]
    d=sut.economic_summary(rows,0,10*TF,1.)
    assert d['Net_bps']==0 and d['DD_bps']==0
    assert d['account_nav_or_mtm'] is False


def test_streak_zero_ends_both_and_loss_amount_not_only_count():
    rows=[reference_trade(v+14,i+1) for i,v in enumerate([10.,20.,0.,-100.,-5.,3.])]
    d=sut.economic_summary(rows,0,20*TF,1.)
    assert d['MaxWinStreak']==2 and d['MedianWinStreak']==1.5
    assert d['MaxLossStreak']==2 and d['WorstLossStreak_bps']==-105.


def test_cost_stress_does_not_change_gross_or_generate_new_trades():
    rows=[reference_trade(50,1),reference_trade(-10,2)]
    a,b=[sut.economic_summary(rows,0,10*TF,m) for m in [1.,2.]]
    assert a['Gross_bps']==b['Gross_bps'] and a['T']==b['T']==2
    assert b['Net_bps']==a['Net_bps']-28.


def test_attribution_reconciles_losses_winners_new_and_missing_trades():
    old=[reference_trade(-100,1),reference_trade(200,2),reference_trade(-50,3)]
    new=[reference_trade(-20,1),reference_trade(100,2),reference_trade(70,4)]
    d=sut.attribution(old,new,1.)
    assert d['common_T']==2 and d['added_T']==d['removed_T']==1
    assert d['loss_reduction_common_bps']==80.
    assert d['lost_winner_profit_bps']==100.
    assert d['total_delta_bps']==d['common_delta_bps']+d['added_net_bps']-d['removed_reference_net_bps']


def test_artificial_early_exit_can_reduce_loss_but_not_prove_market_edge():
    bars=frame();bars.loc[3:,['open','high','low','close']]=[91.,92.,90.5,91.]
    old=original(bars)['trades'];new=replay(bars)['trades']
    assert sut.net(new[0],1.) > sut.net(old[0],1.)
    assert sut.net(new[0],1.) < 0


def test_artificial_recovery_winner_can_be_harmed_and_is_reported():
    bars=frame();bars.loc[3:,['open','high','low','close']]=[122.,123.,121.,122.]
    old=original(bars)['trades'];new=replay(bars)['trades']
    d=sut.attribution(old,new,1.)
    assert sut.net(old[0],1.)>0>sut.net(new[0],1.)
    assert d['lost_winner_profit_bps']>0 and d['winner_profit_retention']==0


def test_nonfinite_and_nonpositive_cost_not_accepted():
    for c in [float('nan'),0,-1]:
        with pytest.raises(ValueError):sut.net(reference_trade(1,1,cost=c),1.)


def test_no_source_fails_before_execution(tmp_path):
    with pytest.raises(FileNotFoundError,match='SOURCE_ROOT_UNAVAILABLE'):
        sut.run(tmp_path/'missing',tmp_path/'not-there.json',tmp_path/'out',full=True)
    assert not (tmp_path/'out').exists()


def test_existing_output_prevents_duplicate_replay(tmp_path):
    (tmp_path/'source').mkdir();(tmp_path/'out').mkdir()
    with pytest.raises(FileExistsError,match='DO_NOT_REPLAY'):
        sut.run(tmp_path/'source',tmp_path/'missing.json',tmp_path/'out',full=True)


def test_write_new_is_append_only_and_receipt_bound(tmp_path):
    p=tmp_path/'a.json';sut._write_new(p,{'T':3})
    data=json.loads(p.read_text());receipt=data.pop('receipt_sha256')
    assert receipt==sut.digest(data)
    with pytest.raises(FileExistsError):sut._write_new(p,{'T':4})


def test_saved_receipt_tampering_is_rejected():
    with pytest.raises(ValueError,match='RECEIPT_MISMATCH'):
        sut.saved_overlay({'receipt_sha256':'0'*64})


SAVED=Path(__file__).resolve().parents[2]/'evidence/saved_overlay/SQUEEZE_REGIME_OVERLAY_RESULT.json'
@pytest.mark.skipif(not SAVED.exists(),reason='Optional archived evidence not in code-only patch')
def test_real_saved_57_trade_arithmetic_without_replaying_old_candidate():
    report=json.loads(SAVED.read_text());rows=sut.saved_overlay(report)
    for m,label in [(1.,'cost1x'),(2.,'cost2x')]:
        summary=sut.economic_summary(rows,sut.START,sut.END,m)
        for k in ['T','Gross_bps','Cost_bps','Net_bps','WR_pct','PF','payoff','MaxLossStreak']:
            assert summary[k]==pytest.approx(report['child'][label][k])
    assert len(rows)==57


def test_keltner_rejection_clears_only_old_setup_and_keeps_side():
    st=parent.HolyGrailState(side=1,episode_traded=True,stage=1,pull_low=90.,pull_high=105.)
    p=RejectedHGEventReset();p.generated(TF);p.decided(st,accepted=False,decision_ts_ms=TF)
    assert st.side==1 and st.stage==0 and not st.episode_traded
    assert math.isinf(st.pull_low) and math.isinf(st.pull_high)


def test_keltner_accepted_trade_setup_is_not_reset():
    st=parent.HolyGrailState(side=1,episode_traded=False,stage=1,pull_low=90.,pull_high=105.)
    p=RejectedHGEventReset();p.generated(TF);p.decided(st,accepted=True,decision_ts_ms=TF)
    assert st.episode_traded and st.stage==1 and st.pull_low==90. and st.pull_high==105.


def test_nontriggering_trend_trade_is_exact_original_after_metadata_normalization():
    bars=frame(trigger=False)
    assert strip_label(replay(bars)['trades'][0])==original(bars)['trades'][0]


@pytest.mark.parametrize('price',[80.,90.])
def test_next_open_stop_arbitration_matches_all_frozen_parent_trade_fields(price):
    bars=frame();bars.loc[2,['open','high','low','close']]=[price,99.,price-1.,98.]
    got=strip_label(replay(bars)['trades'][0])
    expected=original(bars)['trades'][0]
    assert got==expected


def test_saved_arithmetic_report_distinguishes_price_losses_from_cost_losses():
    rows=[reference_trade(5,1),reference_trade(-20,2),reference_trade(100,3)]
    got=sut.economic_summary(rows,0,10*TF,2.)
    assert got['net_bps_by_symbol']['BTC-USDT']==got['Net_bps']
    assert sum(got['net_bps_by_month'].values())==got['Net_bps']
    assert got['worst_trade_bps']==-48.
    assert got['negative_trade_bps_sorted']==[-48.,-23.]


def test_keltner_native_path_cannot_turn_again_without_a_later_new_touch():
    def row(offset, *, low, high, close):
        v={f'g{n}':110.-j+offset for j,n in enumerate(parent.LONG_GMMA)}
        v.update(g20=112.+offset,adx14=35.,low=low,high=high,close=close,hi20=200.,lo20=80.)
        return v
    previous=row(0,low=113.,high=114.,close=113.5)
    turn=row(1,low=114.,high=117.,close=116.)
    legacy=parent.HolyGrailState(side=1,episode_traded=False,stage=1,pull_low=90.,pull_high=115.)
    new=deepcopy(legacy)
    reset=RejectedHGEventReset();reset.generated(TF);reset.decided(new,accepted=False,decision_ts_ms=TF)
    assert parent._hg_event(legacy,turn,previous) is not None
    assert parent._hg_event(new,turn,previous) is None
    touch=row(2,low=112.,high=115.,close=113.)
    assert parent._hg_event(new,touch,turn) is None and new.stage==1
    later_turn=row(3,low=116.,high=119.,close=118.)
    assert parent._hg_event(new,later_turn,touch)==(1,112.)


def test_validation_partition_unresolved_cannot_be_ignored_for_full_completeness():
    r=replay(frame().iloc[:2])
    r['unresolved'][0]['partition']='validation'
    assert sut.comparison_report([],[],r,0,2*TF)['state']=='INCOMPLETE_NO_ADOPTION'

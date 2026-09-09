"""Artificial lifecycle/clock counterexamples; no market data or economic runs."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch
from backend.research.rebuild import chart_mechanism_execution_v1 as c
from backend.research.rebuild import chart_mechanism_features_v1 as f

def rows_of(bars):
    return [dict(bar_open_ts=b.open_ts,bar_close_ts=b.open_ts+c.BAR,open=b.open,high=b.high,low=b.low,close=b.close,volume=b.volume) for b in bars]

def momentum_fixture(n=75):
    bars=[f.Bar(i*c.BAR,100.,100.2,99.8,100.,10.) for i in range(n)]
    for i in range(30,n):
        close=110.+(i-30)*.2;bars[i]=f.Bar(i*c.BAR,close-.1,close+.2,close-.2,close,10.)
    return bars

def soup_fixture(n_days=25):
    days=[f.Bar(i*c.DAY,105.,110.,102.,106.,60.) for i in range(n_days)]
    days[10]=f.Bar(10*c.DAY,104.,108.,100.,102.,60.)
    days[20]=f.Bar(20*c.DAY,103.,106.,98.,99.,60.)
    bars=[]
    for d in days:
        for k in range(6):bars.append(f.Bar(d.open_ts+k*c.BAR,d.open,d.high,d.low,d.close,10.))
    for i in range(21*6,len(bars)):bars[i]=f.Bar(i*c.BAR,101.,102.,100.,101.5,10.)
    return bars

class StandaloneTests(unittest.TestCase):
    def run_bars(self,bars,variant='M1',start=0):
        return c.replay_independent(rows_of(bars),eval_start_ms=start,eval_end_ms=bars[-1].open_ts+c.BAR,variant=variant)
    def test_m1_has_real_complete_lifecycle(self):
        r=self.run_bars(momentum_fixture());self.assertGreater(len(r['trades']),0)
        t=r['trades'][0];self.assertEqual((t['signal_index'],t['entry_index'],t['exit_index']),(30,31,51))
        self.assertEqual(t['exit_reason'],'FIXED_TIME_CLOSE_NEXT_OPEN');self.assertEqual(t['hold_ms'],80*60*60*1000)
    def test_m1_entry_uses_open_not_signal_close(self):
        bars=momentum_fixture();bars[31]=replace(bars[31],open=106.,low=105.)
        t=self.run_bars(bars)['trades'][0];self.assertEqual(t['entry_price'],106.);self.assertNotEqual(t['entry_price'],bars[30].close)
    def test_floor_exit_is_next_open_and_gap_not_line(self):
        bars=momentum_fixture();bars[32]=f.Bar(32*c.BAR,109.,110.,90.,95.,10.);bars[33]=f.Bar(33*c.BAR,80.,999.,1.,105.,10.)
        t=self.run_bars(bars)['trades'][0];self.assertEqual((t['exit_index'],t['exit_price']),(33,80.))
        self.assertEqual(t['exit_reason'],'FIXED_FLOOR_CLOSE_NEXT_OPEN');self.assertGreater(t['mae_bps'],-5000.);self.assertLess(t['mfe_bps'],1000.)
    def test_final_exit_intent_stays_open(self):
        bars=momentum_fixture(33);bars[32]=f.Bar(32*c.BAR,109.,110.,90.,95.,10.)
        r=self.run_bars(bars);self.assertEqual(len(r['open_positions']),1);o=r['open_positions'][0]
        self.assertEqual(o['mark_ts'],33*c.BAR);self.assertEqual(o['pending_exit_signal_ts'],33*c.BAR)
        self.assertFalse(o['terminal_liquidation']);self.assertNotIn('exit_price',o)
    def test_signal_on_last_bar_no_fabricated_entry(self):
        r=self.run_bars(momentum_fixture(31));self.assertEqual(len(r['pending_entries']),1)
        self.assertEqual(r['trades'],[]);self.assertEqual(r['open_positions'],[])
    def test_floor_priority_before_momentum_and_time(self):
        self.assertEqual(c.exit_reason('M1',90.,95.,None,-5.,20),'FIXED_FLOOR_CLOSE')
    def test_momentum_priority_before_timeout(self):
        self.assertEqual(c.exit_reason('M1',100.,90.,None,0.,20),'MOMENTUM_NONPOSITIVE_CLOSE')
    def test_r1_stop_priority_and_target_priority(self):
        self.assertEqual(c.exit_reason('R1',98.,98.,105.,None,12),'FIXED_FLOOR_CLOSE')
        self.assertEqual(c.exit_reason('R1',105.,98.,105.,None,12),'PRIOR_RANGE_MIDPOINT_CLOSE')
    def test_low_intrabar_alone_does_not_stop(self):
        bars=momentum_fixture();bars[32]=replace(bars[32],low=1.)
        self.assertEqual(self.run_bars(bars)['trades'][0]['exit_index'],51)
    def test_gap_invalidates_entry_without_trade_or_retry(self):
        bars=momentum_fixture();bars[31]=f.Bar(31*c.BAR,90.,111.,89.,110.,10.)
        r=self.run_bars(bars);self.assertFalse(r['trades']);self.assertFalse(r['open_positions'])
        self.assertEqual(r['events'][0]['exclusion_reason'],'GAP_INVALIDATES_FIXED_SETUP')
    def test_warmup_never_creates_position(self):
        r=self.run_bars(momentum_fixture(),start=40*c.BAR);self.assertFalse(r['trades']);self.assertFalse(r['open_positions'])
    def test_event_and_geometry_no_price_after_exit(self):
        bars=momentum_fixture();t=self.run_bars(bars)['trades'][0];changed=deepcopy(bars)
        for i in range(t['exit_index']+1,len(changed)):changed[i]=f.Bar(i*c.BAR,100.,1000.,1.,999.,10.)
        self.assertEqual(t,self.run_bars(changed)['trades'][0])
    def test_repeated_json_restored_input_has_identical_output(self):
        bars=momentum_fixture();rows=rows_of(bars);kw=dict(eval_start_ms=0,eval_end_ms=len(bars)*c.BAR,variant='M1')
        self.assertEqual(c.replay_independent(rows,**kw),c.replay_independent(json.loads(json.dumps(rows)),**kw))
    def test_input_unchanged(self):
        rows=rows_of(momentum_fixture());old=deepcopy(rows)
        c.replay_independent(rows,eval_start_ms=0,eval_end_ms=len(rows)*c.BAR,variant='M1');self.assertEqual(old,rows)
    def test_gap_and_duplicate_fail_closed(self):
        rows=rows_of(momentum_fixture())
        for bad in (rows[:15]+rows[16:],rows[:15]+[rows[14]]+rows[16:]):
            with self.assertRaises(ValueError):c.replay_independent(bad,eval_start_ms=0,eval_end_ms=len(rows)*c.BAR,variant='M1')
    def test_bad_close_clock_rejected(self):
        rows=rows_of(momentum_fixture());rows[10]['bar_close_ts']+=1
        with self.assertRaisesRegex(ValueError,'BAR_CLOSE_CLOCK'):c.to_bars(rows,0,len(rows)*c.BAR)
    def test_future_rows_beyond_end_rejected(self):
        rows=rows_of(momentum_fixture())
        with self.assertRaisesRegex(ValueError,'EXACT_PREFIX'):c.to_bars(rows,0,(len(rows)-1)*c.BAR)
    def test_m1_one_signal_per_squeeze_episode(self):
        signals,obs,ft=c.m1_setups(momentum_fixture());self.assertEqual(len(signals),1);self.assertEqual(len({x['setup_id'] for x in signals}),1)
    def test_occupied_signal_cannot_open_second_position(self):
        bars=momentum_fixture();signals,obs,ft=c.m1_setups(bars)
        second=dict(deepcopy(signals[0]),signal_index=35,signal_ts=36*c.BAR,setup_id='synthetic2')
        with patch.object(c,'m1_setups',return_value=(signals+[second],obs,ft)):r=self.run_bars(bars)
        self.assertEqual(len(r['trades']),1);self.assertEqual(r['events'][1]['exclusion_reason'],'ACTUAL_POSITION_OCCUPIED_AT_DECISION')
    def test_same_timestamp_exit_not_available_at_decision(self):
        bars=momentum_fixture();signals,obs,ft=c.m1_setups(bars)
        second=dict(deepcopy(signals[0]),signal_index=50,signal_ts=51*c.BAR,setup_id='synthetic2')
        with patch.object(c,'m1_setups',return_value=(signals+[second],obs,ft)):r=self.run_bars(bars)
        self.assertEqual(r['events'][1]['exclusion_reason'],'ACTUAL_POSITION_OCCUPIED_AT_DECISION')
    def test_r1_uses_twenty_days_not_twenty_4h_bars(self):
        r=self.run_bars(soup_fixture(),'R1');self.assertGreater(len(r['events']),0)
        self.assertGreaterEqual(r['events'][0]['signal_index'],126);self.assertEqual(r['events'][0]['feature']['prior_low_index'],10)
    def test_r1_48h_timeout_and_real_price(self):
        t=self.run_bars(soup_fixture(),'R1')['trades'][0]
        self.assertEqual(t['hold_ms'],48*60*60*1000);self.assertEqual(t['exit_reason'],'FIXED_TIME_CLOSE_NEXT_OPEN')
    def test_r1_target_never_synthetic_fill(self):
        bars=soup_fixture();bars[128]=f.Bar(128*c.BAR,102.,108.,101.,107.,10.);bars[129]=f.Bar(129*c.BAR,106.,108.,105.,107.,10.)
        t=self.run_bars(bars,'R1')['trades'][0]
        self.assertEqual(t['fixed_target'],105.);self.assertEqual(t['exit_price'],106.);self.assertEqual(t['exit_reason'],'PRIOR_RANGE_MIDPOINT_CLOSE_NEXT_OPEN')
    def test_r1_gap_at_target_cancels_setup(self):
        bars=soup_fixture();bars[127]=replace(bars[127],open=106.,high=107.)
        r=self.run_bars(bars,'R1');self.assertEqual(r['events'][0]['exclusion_reason'],'GAP_INVALIDATES_FIXED_SETUP');self.assertFalse(r['trades'])
    def test_r1_last_reclaim_of_day_expires(self):
        bars=soup_fixture()
        for i in range(126,131):bars[i]=f.Bar(i*c.BAR,99.,100.,98.,99.,10.)
        r=self.run_bars(bars,'R1');self.assertEqual(r['events'][0]['signal_index'],131)
        self.assertEqual(r['events'][0]['exclusion_reason'],'SETUP_EXPIRED_BEFORE_ENTRY')
    def test_r1_target_does_not_use_setup_day_high(self):
        bars=soup_fixture();signals,_,_=c.r1_setups(bars);changed=list(bars)
        for i in range(120,126):changed[i]=replace(changed[i],high=1000.)
        other,_,_=c.r1_setups(changed);self.assertEqual(signals[0]['target'],other[0]['target'])
    def test_r1_later_day_low_never_changes_stop(self):
        bars=soup_fixture();signals,_,_=c.r1_setups(bars);changed=list(bars);changed[130]=replace(changed[130],low=.1)
        other,_,_=c.r1_setups(changed);self.assertEqual(signals[0]['floor'],other[0]['floor'])
    def test_r1_partial_leading_day_preserves_native_indices(self):
        original=soup_fixture();prefix=[f.Bar(i*c.BAR,105.,110.,102.,106.,10.) for i in range(6)]
        bars=prefix+[replace(b,open_ts=b.open_ts+c.DAY) for b in original];s1,_,_=c.r1_setups(bars)
        partial=bars[2:];s2,_,a=c.r1_setups(partial);self.assertEqual(a['leading_partial_bars'],4)
        self.assertEqual(s1[0]['signal_ts'],s2[0]['signal_ts']);self.assertEqual(s1[0]['signal_index']-2,s2[0]['signal_index'])
    def test_volume_binding_requires_base_or_fixed_contract(self):
        for binding in (None,{},dict(basis='QUOTE_TURNOVER',source_ref='doc',source_sha256='a'*64)):
            with self.assertRaises(c.UnverifiedVolume):c.validate_volume(binding)
        c.validate_volume(dict(basis='BASE_VOLUME',source_ref='synthetic',source_sha256='a'*64))
    def test_unknown_variant_rejected(self):
        with self.assertRaises(ValueError):self.run_bars(momentum_fixture(),'OTHER')
    def test_signal_features_prefix_invariant(self):
        bars=momentum_fixture();s1,_,_=c.m1_setups(bars);s2,_,_=c.m1_setups(bars[:31]);self.assertEqual(s1[0],s2[0])
    def test_zero_volume_does_not_silently_block_nonvolume_MR(self):
        self.assertTrue(self.run_bars([replace(b,volume=0.) for b in momentum_fixture()])['trades'])
if __name__=='__main__':unittest.main()

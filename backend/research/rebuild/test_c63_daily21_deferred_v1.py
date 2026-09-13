"""Synthetic causality/ownership/gap/cost-clock regressions; no market data."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch
from backend.research.rebuild import c63_daily21_deferred_v1 as c


class DeferredTests(unittest.TestCase):
    def bars(self,n=170):
        return [c.daily.f.Bar(j*c.BAR,100.,102.,98.,100.,0.) for j in range(n)]
    def signal(self,i=126):
        return dict(signal_index=i,signal_ts=(i+1)*c.BAR,setup_id='M1:'+str(i),episode_start=i-3,
                    floor=80.,target=None,expiry=None,max_hold_bars=20,feature={},setup_available_at=(i+1)*c.BAR)
    def call(self,b,signals=None,mom=None,eligible=True):
        signals=signals if signals is not None else [self.signal()]
        features=[dict(momentum=(mom or {}).get(j,1.)) for j in range(len(b))]
        rows=[dict(bar_open_ts=z.open_ts,bar_close_ts=z.open_ts+c.BAR,open=z.open,high=z.high,low=z.low,close=z.close,volume=z.volume) for z in b]
        with patch.object(c.engine,'m1_setups',return_value=(signals,[],features)),patch.object(c.parent,'context',return_value={'eligible':eligible,'reason':None if eligible else 'NATIVE_VETO'}):
            return c.replay(rows,eval_start_ms=0,eval_end_ms=b[-1].open_ts+c.BAR)
    def late(self):
        b=self.bars();b[126]=replace(b[126],close=99.);b[133]=replace(b[133],close=101.)
        return b
    def test_first_reclaim_next_open_and_origin(self):
        r=self.call(self.late());t=r['trades'][0]
        self.assertEqual((t['signal_index'],t['decision_index'],t['entry_index'],t['wait_bars']),(126,133,134,7))
        self.assertEqual(t['entry_price'],100.)
        self.assertEqual(t['signal_ts'],127*c.BAR);self.assertEqual(t['decision_ts'],134*c.BAR)
    def test_wait_and_hold_share_original_clock(self):
        t=self.call(self.late())['trades'][0]
        self.assertEqual(t['exit_trigger']['signal_index'],146);self.assertEqual(t['exit_index'],147)
        self.assertEqual(t['hold_ms'],13*c.BAR);self.assertFalse(t['entry_clock_reset'])
    def test_native_floor_before_reclaim(self):
        b=self.late();b[130]=replace(b[130],low=79.,close=80.)
        r=self.call(b);self.assertEqual(r['events'][0]['exclusion_reason'],'PENDING_CANCEL_FIXED_FLOOR_CLOSE');self.assertFalse(r['trades'])
    def test_momentum_cancel_before_reclaim(self):
        r=self.call(self.late(),mom={133:0.});self.assertEqual(r['events'][0]['exclusion_reason'],'PENDING_CANCEL_MOMENTUM_NONPOSITIVE_CLOSE')
    def test_time_cancel_wins_same_close_reclaim(self):
        b=self.bars();b[146]=replace(b[146],close=101.)
        r=self.call(b);self.assertEqual(r['events'][0]['exclusion_reason'],'PENDING_CANCEL_FIXED_TIME_CLOSE')
    def test_pending_replaced_by_new_raw_signal(self):
        b=self.late();b[129]=replace(b[129],close=101.)
        r=self.call(b,signals=[self.signal(),self.signal(129)])
        self.assertEqual(r['events'][0]['exclusion_reason'],'PENDING_CANCEL_REPLACED_BY_NEW_NATIVE_SIGNAL')
        self.assertEqual(len(r['trades']),1);self.assertEqual(r['trades'][0]['signal_index'],129)
    def test_original_native_veto_not_bypassed(self):
        r=self.call(self.late(),eligible=False);self.assertEqual(r['events'][0]['exclusion_reason'],'NATIVE_VETO');self.assertFalse(r['events'][0]['pending_observations'])
    def test_missing_daily_history_not_pending(self):
        r=self.call(self.bars(),signals=[self.signal(110)])
        self.assertEqual(r['events'][0]['exclusion_reason'],c.daily.MISSING);self.assertFalse(r['events'][0]['pending_observations'])
    def test_immediate_native_geometry_exact(self):
        b=self.bars();b[126]=replace(b[126],close=101.)
        s=self.signal();features=[dict(momentum=1.) for _ in b]
        expected,_,_=c.engine._position(b,s,'M1',features,len(b)*c.BAR)
        got=self.call(b)['trades'][0]
        for k,v in expected.items():self.assertEqual(got[k],v,k)
        self.assertEqual(got['wait_bars'],0)
    def test_original_gap_safety_not_bypassed(self):
        b=self.late();b[127]=replace(b[127],open=79.,low=78.)
        self.assertEqual(self.call(b)['events'][0]['exclusion_reason'],'GAP_INVALIDATES_FIXED_SETUP')
    def test_reclaim_gap_does_not_retry(self):
        b=self.late();b[134]=replace(b[134],open=79.,low=78.)
        r=self.call(b);self.assertEqual(r['events'][0]['exclusion_reason'],'GAP_INVALIDATES_FIXED_SETUP');self.assertFalse(r['trades'])
    def test_immediate_gap_not_bypassed(self):
        b=self.late();b[126]=replace(b[126],close=101.);b[127]=replace(b[127],open=79.,low=78.)
        self.assertEqual(self.call(b)['events'][0]['exclusion_reason'],'GAP_INVALIDATES_FIXED_SETUP')
    def test_terminal_pending_is_not_position(self):
        r=self.call(self.late()[:132]);self.assertFalse(r['trades']);self.assertFalse(r['open_positions']);self.assertEqual(len(r['pending_entries']),1)
    def test_terminal_reclaim_no_next_open(self):
        r=self.call(self.late()[:134]);self.assertEqual(r['events'][0]['exclusion_reason'],'NO_NEXT_OPEN_IN_APPROVED_WINDOW')
    def test_unfinished_position_is_not_closed(self):
        r=self.call(self.late()[:138]);self.assertFalse(r['trades']);self.assertEqual(len(r['open_positions']),1);self.assertFalse(r['open_positions'][0]['terminal_liquidation'])
    def test_actual_occupancy_after_delayed_fill(self):
        b=self.late();b[140]=replace(b[140],close=101.)
        r=self.call(b,signals=[self.signal(),self.signal(140)])
        self.assertEqual(len(r['trades']),1);self.assertEqual(r['events'][1]['exclusion_reason'],'ACTUAL_POSITION_OCCUPIED_AT_DECISION')
    def test_same_time_exit_does_not_reenter(self):
        b=self.late();b[146]=replace(b[146],close=101.)
        r=self.call(b,signals=[self.signal(),self.signal(146)])
        self.assertEqual(r['events'][1]['exclusion_reason'],'ACTUAL_POSITION_OCCUPIED_AT_DECISION')
    def test_future_mutation_does_not_change_entry_or_pending_observations(self):
        b=self.late();a=self.call(b);r=list(b)
        for j in range(135,len(r)):r[j]=replace(r[j],open=110.,high=115.,low=105.,close=112.)
        other=self.call(r)
        for k in ('signal_ts','decision_ts','entry_index','entry_ts','entry_price','wait_bars'):self.assertEqual(a['trades'][0][k],other['trades'][0][k])
        self.assertEqual(a['events'][0]['pending_observations'],other['events'][0]['pending_observations'])
    def test_prefix_first_admission_is_invariant(self):
        a=self.call(self.late());b=self.call(self.late()[:140])
        for k in ('decision_index','decision_ts','wait_bars','pending_observations'):self.assertEqual(a['events'][0][k],b['events'][0][k])
    def test_first_not_best_reclaim(self):
        b=self.late();b[135]=replace(b[135],close=102.)
        self.assertEqual(self.call(b)['trades'][0]['decision_index'],133)
    def test_native_floor_after_entry_preserved(self):
        b=self.late();b[137]=replace(b[137],low=79.,close=80.)
        t=self.call(b)['trades'][0];self.assertEqual(t['exit_index'],138);self.assertEqual(t['exit_reason'],'FIXED_FLOOR_CLOSE_NEXT_OPEN')
    def test_patch_restored_on_error(self):
        before=c.engine.exit_reason
        with patch.object(c.engine,'_position',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.call(self.late())
        self.assertIs(c.engine.exit_reason,before)
    def test_input_immutable(self):
        b=self.late();old=deepcopy(b);self.call(b);self.assertEqual(b,old)
    def test_gap_in_data_fails_closed(self):
        b=self.late();del b[20]
        with self.assertRaises(ValueError):self.call(b)
    def test_negative_delay_rejected(self):
        with self.assertRaises(ValueError):c.deferred_position(self.bars(),self.signal(),125,[],170*c.BAR)

if __name__=='__main__':unittest.main()

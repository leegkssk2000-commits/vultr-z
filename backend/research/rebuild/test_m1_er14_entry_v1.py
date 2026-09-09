from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import unittest
from backend.research.rebuild import m1_er14_entry_v1 as c
from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture,rows_of

class ERTests(unittest.TestCase):
    def test_fourteen_changes_not_fourteen_closes(self):
        self.assertIsNone(c.er_observation([100.]*14,13))
        self.assertEqual(c.er_observation(list(range(100,115)),14)['value'],1.)
    def test_monotonic_down_is_also_efficient(self):
        self.assertEqual(c.er_observation(list(range(115,100,-1)),14)['value'],1.)
    def test_zero_path_defined_zero(self):self.assertEqual(c.er_observation([100.]*15,14)['value'],0.)
    def test_known_oscillating_path(self):
        x=[100,101]*7+[102];o=c.er_observation(x,14)
        self.assertEqual(o['displacement'],2);self.assertEqual(o['path_length'],14);self.assertEqual(o['value'],1/7)
    def test_invalid_price_fails(self):
        for value in (0.,-1.,float('nan'),float('inf'),True):
            x=[100.]*15;x[5]=value
            with self.assertRaises(ValueError):c.er_observation(x,14)
    def test_index_failures(self):
        for i in (-1,15,True):
            with self.assertRaises(ValueError):c.er_observation([100.]*15,i)
    def test_tie_is_not_increase(self):
        bars=momentum_fixture();bars=[replace(b,close=100+i,high=200+i,low=1.) for i,b in enumerate(bars)]
        self.assertFalse(c.context(bars,20)['eligible'])
    def test_signal_changes_but_future_does_not(self):
        bars=momentum_fixture();x=c.context(bars,30);other=list(bars)
        for i in range(31,len(other)):other[i]=replace(other[i],close=1e6)
        self.assertEqual(x,c.context(other,30));self.assertEqual(x,c.context(bars[:31],30))
    def test_clock_and_history_exact(self):
        bars=momentum_fixture();x=c.context(bars,30)
        self.assertEqual(x['available_at'],31*c.BAR);self.assertEqual(x['previous_available_at'],30*c.BAR)
        self.assertEqual(x['current']['start_index'],16);self.assertEqual(x['previous']['start_index'],15)
    def test_positive_scaling_invariant(self):
        bars=momentum_fixture();x=c.context(bars,30)
        y=c.context([replace(b,close=b.close*4) for b in bars],30)
        self.assertEqual(x['eligible'],y['eligible']);self.assertEqual(x['current']['value'],y['current']['value'])
    def test_volume_irrelevant(self):
        bars=momentum_fixture();self.assertEqual(c.context(bars,30),c.context([replace(b,volume=0.) for b in bars],30))

class ReplayTests(unittest.TestCase):
    def call(self,bars,**kw):return c.replay(rows_of(bars),eval_start_ms=0,eval_end_ms=len(bars)*c.BAR,**kw)
    def parent(self,bars):return c.parent.replay_independent(rows_of(bars),eval_start_ms=0,eval_end_ms=len(bars)*c.BAR,variant='M1')
    def test_disabled_is_exact_original(self):
        bars=momentum_fixture();self.assertEqual(self.call(bars,enabled=False),self.parent(bars))
    def test_all_accepted_has_exact_geometry(self):
        bars=momentum_fixture();parent=self.parent(bars)
        with patch.object(c,'context',return_value={'eligible':True}):r=self.call(bars)
        for k in ('trades','open_positions','trace','setup_events','pending_entries'):self.assertEqual(r[k],parent[k])
        self.assertEqual([{k:v for k,v in e.items() if k!='er_context'} for e in r['events']],parent['events'])
    def test_veto_is_not_phantom_trade(self):
        with patch.object(c,'context',return_value={'eligible':False,'reason':c.VETO}):r=self.call(momentum_fixture())
        self.assertFalse(r['trades']);self.assertFalse(r['open_positions']);self.assertEqual(r['events'][0]['exclusion_reason'],c.VETO)
    def test_omitting_position_can_enable_later_original_signal(self):
        bars=momentum_fixture();signals,obs,ft=c.parent.m1_setups(bars)
        second=dict(deepcopy(signals[0]),signal_index=35,signal_ts=36*c.BAR,setup_id='SECOND_ORIGINAL_SIGNAL')
        with patch.object(c.parent,'m1_setups',return_value=(signals+[second],obs,ft)),patch.object(c,'context',side_effect=[{'eligible':False,'reason':c.VETO},{'eligible':True}]):r=self.call(bars)
        self.assertEqual([t['signal_index'] for t in r['trades']],[35])
    def test_original_same_close_occupancy_preserved(self):
        bars=momentum_fixture();signals,obs,ft=c.parent.m1_setups(bars)
        second=dict(deepcopy(signals[0]),signal_index=50,signal_ts=51*c.BAR,setup_id='SECOND')
        with patch.object(c.parent,'m1_setups',return_value=(signals+[second],obs,ft)),patch.object(c,'context',return_value={'eligible':True}):r=self.call(bars)
        self.assertEqual(r['events'][1]['exclusion_reason'],'ACTUAL_POSITION_OCCUPIED_AT_DECISION')
    def test_gap_cancels_at_actual_open(self):
        bars=momentum_fixture();bars[31]=replace(bars[31],open=1.,low=.5)
        with patch.object(c,'context',return_value={'eligible':True}):r=self.call(bars)
        self.assertEqual(r['events'][0]['exclusion_reason'],'GAP_INVALIDATES_FIXED_SETUP')
    def test_window_end_pending_not_fill(self):
        bars=momentum_fixture()[:31]
        with patch.object(c,'context',return_value={'eligible':True}):r=self.call(bars)
        self.assertEqual(r['events'][0]['exclusion_reason'],'NO_NEXT_OPEN_IN_APPROVED_WINDOW');self.assertFalse(r['trades'])
    def test_open_tail_preserved(self):
        bars=momentum_fixture()[:36]
        with patch.object(c,'context',return_value={'eligible':True}):r=self.call(bars)
        self.assertEqual(r['open_positions'],self.parent(bars)['open_positions'])
    def test_missing_bar_rejected(self):
        bars=momentum_fixture();del bars[15]
        with self.assertRaises(ValueError):self.call(bars)
    def test_inputs_immutable(self):
        bars=momentum_fixture();r=rows_of(bars);old=deepcopy(r);c.replay(r,eval_start_ms=0,eval_end_ms=len(bars)*c.BAR)
        self.assertEqual(r,old)
    def test_unknown_enabled_rejected(self):
        with self.assertRaises(ValueError):self.call(momentum_fixture(),enabled=1)
if __name__=='__main__':unittest.main()

"""Artificial prices only; no market-derived constants or hidden PnL scan."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import unittest
from backend.research.rebuild import m1_er_range_rescue_v1 as c
from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture,rows_of

class RangeTests(unittest.TestCase):
    def fixture(self):
        b=momentum_fixture();s=c.er.parent.m1_setups(b)[0][0]
        return b,s
    def er_context(self,eligible=False,missing=False):
        return lambda b,i:dict(current=None if missing else {'value':.2},previous=None if missing else {'value':.3},eligible=eligible,reason=None if eligible else 'ER14_HISTORY_UNAVAILABLE' if missing else c.er.VETO)
    def test_strict_prior_range_can_rescue(self):
        b,s=self.fixture();x=c.context(b,s,self.er_context());self.assertTrue(x['eligible']);self.assertTrue(x['range_context']['rescued'])
    def test_equal_high_never_rescues(self):
        b,s=self.fixture();i=s['signal_index'];hi=max(x.high for x in b[s['episode_start']:i]);b[i]=replace(b[i],close=hi)
        self.assertFalse(c.context(b,s,self.er_context())['eligible'])
    def test_signal_high_not_used_in_prior_range(self):
        b,s=self.fixture();x=c.context(b,s,self.er_context());b[s['signal_index']]=replace(b[s['signal_index']],high=1e9)
        self.assertEqual(x,c.context(b,s,self.er_context()))
    def test_no_future_or_pre_episode_extreme(self):
        b,s=self.fixture();x=c.context(b,s,self.er_context());r=list(b)
        for j in list(range(s['episode_start']))+list(range(s['signal_index']+1,len(b))):r[j]=replace(r[j],high=1e9)
        self.assertEqual(x,c.context(r,s,self.er_context()));self.assertEqual(x,c.context(b[:s['signal_index']+1],s,self.er_context()))
    def test_original_ER_pass_not_blocked(self):
        b,s=self.fixture();i=s['signal_index'];b[i]=replace(b[i],close=1.)
        x=c.context(b,s,self.er_context(True));self.assertTrue(x['eligible']);self.assertFalse(x['range_context']['rescued'])
    def test_missing_ER_not_bypassed(self):
        b,s=self.fixture();x=c.context(b,s,self.er_context(missing=True));self.assertFalse(x['eligible']);self.assertEqual(x['reason'],'ER14_HISTORY_UNAVAILABLE')
    def test_nonfinite_range_rejected(self):
        b,s=self.fixture();b[s['episode_start']]=replace(b[s['episode_start']],high=float('nan'))
        with self.assertRaises(ValueError):c.context(b,s,self.er_context())
    def test_exact_clock(self):
        b,s=self.fixture();x=c.context(b,s,self.er_context())['range_context'];self.assertLess(x['prior_available_at'],x['available_at'])
        for r in x['source_highs']:self.assertLess(r['ts'],x['available_at'])
        with self.assertRaises(ValueError):c.context(b,dict(s,signal_ts=s['signal_ts']+1),self.er_context())
    def test_zero_length_episode_rejected(self):
        b,s=self.fixture()
        with self.assertRaises(ValueError):c.context(b,dict(s,episode_start=s['signal_index']),self.er_context())
    def test_price_scaling_preserves_predicate(self):
        b,s=self.fixture();x=c.context(b,s,self.er_context());r=[replace(z,high=z.high*10,close=z.close*10) for z in b]
        self.assertEqual(x['eligible'],c.context(r,s,self.er_context())['eligible'])
    def test_volume_irrelevant(self):
        b,s=self.fixture();self.assertEqual(c.context(b,s,self.er_context()),c.context([replace(z,volume=0.) for z in b],s,self.er_context()))

class ReplayTests(unittest.TestCase):
    def call(self,b,**kw):return c.replay(rows_of(b),eval_start_ms=0,eval_end_ms=len(b)*c.BAR,**kw)
    def test_disabled_exact_M1(self):
        b=momentum_fixture();self.assertEqual(self.call(b,enabled=False),c.er.replay(rows_of(b),eval_start_ms=0,eval_end_ms=len(b)*c.BAR,enabled=False))
    def test_retained_geometry_original(self):
        b=momentum_fixture();x=self.call(b);p=self.call(b,enabled=False)
        for k in ('trades','open_positions','trace','setup_events','pending_entries'):self.assertEqual(x[k],p[k])
    def test_gap_safety_never_overridden(self):
        b=momentum_fixture();b[31]=replace(b[31],open=1.,low=.5)
        self.assertEqual(self.call(b)['events'][0]['exclusion_reason'],'GAP_INVALIDATES_FIXED_SETUP')
    def test_pending_end_unchanged(self):
        b=momentum_fixture()[:31];x=self.call(b)
        self.assertFalse(x['trades']);self.assertEqual(x['events'][0]['exclusion_reason'],'NO_NEXT_OPEN_IN_APPROVED_WINDOW')
    def test_open_tail_unchanged(self):
        b=momentum_fixture()[:36];self.assertEqual(self.call(b)['open_positions'],self.call(b,enabled=False)['open_positions'])
    def test_hooks_restored_after_exception(self):
        b=momentum_fixture();old=(c.er.context,c.er.parent.m1_setups)
        with patch.object(c,'context',side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError,'injected'):self.call(b)
        self.assertEqual(old,(c.er.context,c.er.parent.m1_setups))
    def test_input_immutable(self):
        b=momentum_fixture();r=rows_of(b);before=deepcopy(r);c.replay(r,eval_start_ms=0,eval_end_ms=len(b)*c.BAR);self.assertEqual(before,r)
    def test_missing_bar_rejected(self):
        b=momentum_fixture();del b[5]
        with self.assertRaises(ValueError):self.call(b)
    def test_bool_strict(self):
        with self.assertRaises(ValueError):self.call(momentum_fixture(),enabled=1)
if __name__=='__main__':unittest.main()

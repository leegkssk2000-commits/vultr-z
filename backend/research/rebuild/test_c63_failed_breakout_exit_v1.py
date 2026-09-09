"""Artificial fixtures only; no market-derived threshold or candidate return."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
import unittest
from backend.research.rebuild import c63_failed_breakout_exit_v1 as c
from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture,rows_of

class ExitTests(unittest.TestCase):
    def call(self,b,**kw):
        with patch.object(c,'observed_cost',return_value=20.):
            return c.replay(rows_of(b),eval_start_ms=0,eval_end_ms=len(b)*c.BAR,cost_model={},**kw)
    def fixture(self):
        b=momentum_fixture();s=c.engine.m1_setups(b)[0][0];i=s['signal_index'];upper=max(x.high for x in b[s['episode_start']:i]);return b,s,i,upper
    def fail_fixture(self):
        b,s,i,u=self.fixture();b[i+1]=replace(b[i+1],open=u+2,high=u+3,low=u-1,close=u-.1)
        return b,s,i,u
    def test_predicate_edges(self):
        for escape,close,net,expected in [(True,99,0,True),(True,100,-10,False),(True,99,.01,False),(False,99,-10,False),(True,101,-10,False)]:
            self.assertEqual(c.predicate(escaped=escape,close=close,upper=100,net_mark=net),expected)
    def test_invalid_price_fails(self):
        for x in (float('nan'),float('inf'),0):
            with self.assertRaises(ValueError):c.predicate(escaped=True,close=x,upper=100,net_mark=0)
    def test_disabled_exact_C63_not_original_M1(self):
        b,s,i,u=self.fixture();self.assertEqual(self.call(b,enabled=False),c.parent.replay(rows_of(b),eval_start_ms=0,eval_end_ms=len(b)*c.BAR))
    def test_no_failure_unchanged_economics(self):
        b,s,i,u=self.fixture();out=self.call(b);old=self.call(b,enabled=False)
        self.assertEqual(len(out['trades']),len(old['trades']))
        for k in ('entry_ts','entry_price','exit_ts','exit_price','exit_reason'):self.assertEqual(out['trades'][0][k],old['trades'][0][k])
    def test_first_failure_next_actual_open(self):
        b,s,i,u=self.fail_fixture();b[i+2]=replace(b[i+2],open=u-2,low=u-3)
        t=self.call(b)['trades'][0];self.assertEqual(t['exit_reason'],c.REASON+'_NEXT_OPEN');self.assertEqual(t['exit_index'],i+2);self.assertEqual(t['exit_price'],u-2)
    def test_signal_high_not_exit_anchor(self):
        b,s,i,u=self.fail_fixture();features=c.engine.m1_setups(b)[2];b[i]=replace(b[i],high=1e6)
        with patch.object(c,'observed_cost',return_value=20.):
            t,_,_=c.position(b,s,'M1',features,len(b)*c.BAR,{},c.engine._position,c.engine.exit_reason)
        self.assertEqual(t['failed_breakout_upper'],u);self.assertEqual(t['exit_index'],i+2)
    def test_floor_has_priority(self):
        b,s,i,u=self.fail_fixture();b[i+1]=replace(b[i+1],close=s['floor']-1,low=s['floor']-2)
        self.assertEqual(self.call(b)['trades'][0]['exit_reason'],'FIXED_FLOOR_CLOSE_NEXT_OPEN')
    def test_end_pending_not_fake_exit(self):
        b,s,i,u=self.fail_fixture();out=self.call(b[:i+2]);self.assertFalse(out['trades']);self.assertEqual(out['open_positions'][0]['pending_exit_trigger']['reason'],c.REASON)
    def test_next_open_safety_unchanged(self):
        b,s,i,u=self.fixture();b[i+1]=replace(b[i+1],open=1,low=.5)
        out=self.call(b);self.assertFalse(out['trades']);self.assertEqual(out['events'][0]['exclusion_reason'],'GAP_INVALIDATES_FIXED_SETUP')
    def test_only_known_range_and_no_future_leak(self):
        b,s,i,u=self.fail_fixture();out=self.call(b)['trades'][0]
        for j in range(i+3,len(b)):b[j]=replace(b[j],open=999,high=1000,low=998,close=999)
        self.assertEqual(out,self.call(b)['trades'][0])
    def test_fixed_entries_exact(self):
        b,s,i,u=self.fail_fixture();a=self.call(b,fixed_signal_indices=[i]);self.assertEqual(len(a['trades']),1);self.assertEqual(a['trades'][0]['signal_index'],i)
    def test_no_fixed_signals_no_positions(self):self.assertEqual(self.call(momentum_fixture(),fixed_signal_indices=[])['trades'],[])
    def test_unknown_fixed_rejected(self):
        with self.assertRaises(ValueError):self.call(momentum_fixture(),fixed_signal_indices=[0])
    def test_duplicate_fixed_rejected(self):
        b,s,i,u=self.fixture()
        with self.assertRaises(ValueError):self.call(b,fixed_signal_indices=[i,i])
    def test_hook_restored_on_cost_error(self):
        b,s,i,u=self.fixture();before=(c.engine._position,c.engine.exit_reason,c.engine.m1_setups,c.parent.er.context)
        with patch.object(c,'observed_cost',side_effect=RuntimeError('cost')):
            with self.assertRaises(RuntimeError):c.replay(rows_of(b),eval_start_ms=0,eval_end_ms=len(b)*c.BAR,cost_model={})
        self.assertEqual(before,(c.engine._position,c.engine.exit_reason,c.engine.m1_setups,c.parent.er.context))
    def test_input_immutable(self):
        b,s,i,u=self.fail_fixture();before=deepcopy(b);self.call(b);self.assertEqual(before,b)
    def test_gap_bar_rejected(self):
        b,s,i,u=self.fixture();del b[5]
        with self.assertRaises(ValueError):self.call(b)
    def test_cost_clock_is_held_close(self):
        b,s,i,u=self.fail_fixture();out=self.call(b);r=[r for r in out['trace'] if r['kind']=='FAILED_BREAKOUT_OBSERVATION'][0]
        self.assertEqual(r['ts'],b[i+1].open_ts+c.BAR);self.assertLess(r['fixed_upper'],b[i].close)
    def test_actual_cost_function_remote(self):
        # Real inherited cost function. Missing import in a partial export is not
        # silently replaced with a mock PASS; full checkout CI supplies it.
        from backend.research.rebuild.test_kr3_profit_zone_exit_v1 import COST
        self.assertGreater(c.observed_cost(0,c.BAR,COST),0)
if __name__=='__main__':unittest.main()

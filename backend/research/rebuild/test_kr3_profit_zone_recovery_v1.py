"""Artificial-only regression; parent historical trials are not rerun."""
from copy import deepcopy
import json,unittest
from unittest.mock import patch
from backend.research.rebuild import kr3_profit_zone_recovery_v1 as c
from backend.research.rebuild.test_kr3_profit_zone_exit_v1 import ProfitZoneTests,COST
p=c.parent
class RecoveryTests(unittest.TestCase):
    def state(self):return dict(armed_index=3,armed_ts=4*p.BAR,protected_line=102.,last_index=3,exit_requested=False)
    def step(self,st,index,close,e20=101.,e50=100.):
        return c.observation(st,row=dict(close=close,bar_close_ts=(index+1)*p.BAR),index=index,
            ema20=e20,ema50=e50,entry_price=100.,cost=p.decision_cost(3*p.BAR,(index+1)*p.BAR,COST))
    def fixture(self):return ProfitZoneTests().fixture()
    def run_child(self,r,b,s,e,**kw):return c.replay(r,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST,**kw)
    def test_positive_mark_exit_unchanged(self):
        st,hit=self.step(self.state(),4,101.5);self.assertTrue(hit);self.assertFalse(st['recovery_used'])
    def test_nonpositive_first_breach_deferred(self):
        old=self.state();st,hit=self.step(old,4,99.9)
        self.assertFalse(hit);self.assertFalse(st['exit_requested']);self.assertEqual(st['protected_line'],102.)
        self.assertEqual(st['recovery_pending_index'],4);self.assertEqual(old,self.state())
    def test_second_breach_confirms_even_if_mark_positive(self):
        st,_=self.step(self.state(),4,99.9);st,hit=self.step(st,5,101.)
        self.assertTrue(hit);self.assertIsNone(st['recovery_pending_index'])
    def test_recovery_cancels_once_and_next_breach_cannot_defer(self):
        st,_=self.step(self.state(),4,99.9);st,hit=self.step(st,5,102.)
        self.assertFalse(hit);self.assertTrue(st['recovery_used']);st,hit=self.step(st,6,99.8);self.assertTrue(hit)
    def test_state_roundtrip_does_not_reset_grace(self):
        st,_=self.step(self.state(),4,99.9)
        self.assertEqual(self.step(st,5,102.),self.step(json.loads(json.dumps(st)),5,102.))
    def test_skip_in_confirmation_rejected(self):
        st,_=self.step(self.state(),4,99.9)
        with self.assertRaisesRegex(ValueError,'NEXT_COMPLETED'):self.step(st,6,101.)
    def test_invalid_pending_rejected(self):
        st=self.state();st['recovery_pending_index']=3
        with self.assertRaisesRegex(ValueError,'INVALID_STATE'):self.step(st,4,101.)
    def test_line_remains_monotone_after_recovery(self):
        st,_=self.step(self.state(),4,99.9);st,hit=self.step(st,5,103.,e20=102.5)
        self.assertFalse(hit);self.assertEqual(st['protected_line'],102.5)
    def test_disabled_is_exact_C51_not_KR3(self):
        r,b,s,e,i=self.fixture();got=self.run_child(r,b,s,e,enabled=False)
        self.assertEqual(got,p.replay(r,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST))
        self.assertEqual(got['trades'][0]['exit_reason'],p.GUARD_EXIT)
    def loss_fixture(self):
        r,b,s,e,i=self.fixture();r[i+2].update(close=99.9,low=99.5)
        b['ema20'][i+2]=101.5;b['ema50'][i+2]=100.5
        return r,b,s,e,i
    def test_original_ema_exit_preempts_grace(self):
        r,b,s,e,i=self.loss_fixture();b['ema20'][i+2]=100.
        t=self.run_child(r,b,s,e)['trades'][0]
        self.assertEqual(t['exit_reason'],'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN');self.assertEqual(t['exit_index'],i+3)
    def test_recovery_keeps_priorities_and_then_real_gap(self):
        r,b,s,e,i=self.loss_fixture();r[i+3].update(open=99.9,close=101.,low=99.,high=102.)
        b['ema20'][i+3]=101.2;b['ema50'][i+3]=100.5
        r[i+4].update(open=96.,high=999.,low=.1,close=96.)
        t=self.run_child(r,b,s,e)['trades'][0]
        self.assertEqual(t['exit_index'],i+4);self.assertEqual(t['exit_price'],96.)
        self.assertEqual(len(t['profit_zone_state']['recovery_events']),2)
        self.assertLess(t['mfe_bps'],1000.);self.assertGreater(t['mae_bps'],-401.)
    def test_pending_recovery_at_end_remains_open(self):
        r,b,s,e,i=self.loss_fixture();r=r[:i+3];e=(i+3)*p.BAR
        for k in ('ema20','ema50'):b[k]=b[k][:i+3]
        out=self.run_child(r,b,s,e);t=out['open_positions'][0]
        self.assertFalse(out['trades']);self.assertIsNone(t['pending_exit_signal_ts'])
        self.assertEqual(t['profit_zone_state']['recovery_pending_index'],i+2);self.assertFalse(t['terminal_liquidation'])
    def test_future_suffix_and_exit_hlc_not_used(self):
        r,b,s,e,i=self.loss_fixture();r[i+3].update(open=99.9,close=101.,low=99.,high=102.)
        b['ema20'][i+3]=101.2;b['ema50'][i+3]=100.5;r[i+4].update(open=96.,low=95.)
        first=self.run_child(r,b,s,e)['trades'];r[i+4].update(high=1000000.,low=.001,close=10000.)
        for j in range(i+5,len(r)):r[j].update(open=20.,close=20.,high=21.,low=19.)
        self.assertEqual(first,self.run_child(r,b,s,e)['trades'])
    def test_inputs_and_hooks_unchanged(self):
        r,b,s,e,i=self.loss_fixture();before=deepcopy((r,b,COST));hook=p.guard_observation
        self.run_child(r,b,s,e);self.assertEqual((r,b,COST),before);self.assertIs(p.guard_observation,hook)
    def test_failure_restores_hook(self):
        r,b,s,e,i=self.fixture();hook=p.guard_observation
        with patch.object(c,'observation',side_effect=ValueError('injected')):
            with self.assertRaisesRegex(ValueError,'injected'):self.run_child(r,b,s,e)
        self.assertIs(p.guard_observation,hook)
    def test_reference_clock_kept(self):
        r,b,s,e,i=self.loss_fixture()
        for j in (i+4,i+6,i+18):b['signals'].append(dict(signal_index=j,signal_ts=r[j]['bar_close_ts']))
        got=self.run_child(r,b,s,e);old=p.replay(r,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST)
        for k in ('reference_checkpoint','reference_events','reference_opportunities'):self.assertEqual(got[k],old[k])
    def test_arming_bar_retained(self):
        r,b,s,e,i=self.fixture();t=self.run_child(r,b,s,e)['trades'][0]
        self.assertEqual(t['profit_zone_state']['armed_index'],i+1);self.assertGreater(t['exit_trigger']['signal_index'],i+1)
if __name__=='__main__':unittest.main()

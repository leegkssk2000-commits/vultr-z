"""Synthetic-only specification counterexamples, not economic outcomes."""
import unittest
from backend.research.rebuild import c63_profit_pivot_exit_v1 as x

class GuardTests(unittest.TestCase):
    def pivot(self,known,price=106):return dict(kind='LOW',index=known-2,known_index=known,price=price,available_at=(known+1)*14400000)
    def state(self):return x.Protection(10,100)
    def armed(self):
        s=self.state()
        for j in (10,11):s.step(j,110,20,None,None)
        s.step(12,110,20,self.pivot(12),None)
        return s
    def test_no_level_no_sell(self):self.assertIsNone(self.state().step(10,120,20,None,None)['selected_reason'])
    def test_activation_not_a_sale(self):self.assertIsNone(self.armed().step(13,120,20,None,None)['selected_reason'])
    def test_old_level_broken_next_close(self):self.assertEqual(self.armed().step(13,105,20,None,None)['selected_reason'],x.REASON)
    def test_equality_does_not_trigger(self):self.assertIsNone(self.armed().step(13,106,20,None,None)['selected_reason'])
    def test_native_priority(self):self.assertEqual(self.armed().step(13,105,20,None,'FIXED_TIME_CLOSE')['selected_reason'],'FIXED_TIME_CLOSE')
    def test_unprofitable_low_never_arms(self):
        s=self.state();s.step(10,110,20,None,None);s.step(11,110,20,None,None)
        self.assertIsNone(s.step(12,110,20,self.pivot(12,100.1),None)['active_after'])
    def test_break_even_equal_no_activation(self):
        s=self.state();s.step(10,110,100,None,None);s.step(11,110,100,None,None)
        self.assertIsNone(s.step(12,110,100,self.pivot(12,101),None)['active_after'])
    def test_preentry_low_no_activation(self):
        s=self.state();self.assertIsNone(s.step(10,110,20,self.pivot(10),None)['active_after'])
    def test_never_lower(self):
        s=self.armed();self.assertEqual(s.step(13,110,20,self.pivot(13,105),None)['active_after'],106)
    def test_raise_for_future_only(self):
        s=self.armed();o=s.step(13,107,20,self.pivot(13,108),None)
        self.assertIsNone(o['selected_reason']);self.assertEqual(o['active_after'],108)
        self.assertEqual(s.step(14,107,20,None,None)['selected_reason'],x.REASON)
    def test_cannot_rearm_on_exit(self):
        s=self.armed();self.assertIsNone(s.step(13,105,20,self.pivot(13,108),None)['activated'])
    def test_funding_may_outgrow_activated_level(self):
        s=self.armed();self.assertEqual(s.step(13,105,1000,None,None)['selected_reason'],x.REASON)
    def test_out_of_order(self):
        s=self.armed()
        with self.assertRaisesRegex(ValueError,'ORDER'):s.step(14,110,20,None,None)
    def test_future_pivot_rejected(self):
        with self.assertRaisesRegex(ValueError,'CLOCK'):self.state().step(10,110,20,self.pivot(12),None)
    def test_invalid_cost(self):
        for n in (float('nan'),float('inf'),-1,True):
            with self.subTest(n=n),self.assertRaises(ValueError):self.state().step(10,110,n,None,None)

class NativeTests(unittest.TestCase):
    def test_disabled_exact_c63(self):
        from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture,rows_of
        from backend.research.rebuild import m1_er_range_rescue_v1 as c63
        rows=rows_of(momentum_fixture());kw=dict(eval_start_ms=0,eval_end_ms=len(rows)*14400000)
        self.assertEqual(x.replay(rows,cost_model={},enabled=False,**kw),c63.replay(rows,**kw))
    def test_confirmed_clock_is_causal_and_strict(self):
        from backend.research.rebuild.chart_mechanism_features_v1 import Bar,confirmed_pivots
        b=[Bar(i*14400000,120,125,lo,120,1) for i,lo in enumerate([110,108,106,109,111])]
        self.assertFalse(confirmed_pivots(b,3));p=confirmed_pivots(b,4)[0]
        self.assertEqual((p['index'],p['known_index'],p['available_at']),(2,4,5*14400000))
        b[4]=Bar(4*14400000,120,125,106,120,1);self.assertFalse(confirmed_pivots(b,4))

    def fixture(self):
        from backend.research.rebuild.chart_mechanism_features_v1 import Bar
        from backend.research.rebuild import chart_mechanism_execution_v1 as e
        b=[Bar(i*e.BAR,100,105,95,100,1) for i in range(45)]
        vals={21:(100,113,99,110),22:(110,115,108,112),23:(110,114,106,110),24:(110,115,108,112),25:(110,115,109,112),26:(110,111,104,105),27:(104,106,103,104)}
        for i,v in vals.items():b[i]=Bar(i*e.BAR,*v,1)
        sig=dict(signal_index=20,signal_ts=21*e.BAR,floor=90,target=None,setup_id='SYNTHETIC')
        return b,sig,[dict(momentum=10) for _ in b],e
    def position(self,b,s,f,e,end=None):
        from unittest.mock import patch
        with patch('backend.research.rebuild.kr3_profit_zone_exit_v1.decision_cost',return_value={'cost_bps':20}):
            return x.position(b,s,'M1',f,end or len(b)*e.BAR,{},e._position,e.exit_reason)
    def test_native_next_open_not_level_price(self):
        b,s,f,e=self.fixture();t,op,tr=self.position(b,s,f,e)
        self.assertIsNone(op);self.assertEqual((t['exit_index'],t['exit_price'],t['exit_reason']),(27,104,x.REASON+'_NEXT_OPEN'))
    def test_window_end_pending_not_fake_fill(self):
        b,s,f,e=self.fixture();t,op,tr=self.position(b[:27],s,f[:27],e)
        self.assertIsNone(t);self.assertFalse(op['terminal_liquidation']);self.assertEqual(op['pending_exit_trigger']['reason'],x.REASON)
    def test_time_priority_and_hook_restored(self):
        b,s,f,e=self.fixture();fn=e.exit_reason;f[26]['momentum']=0
        t,_,_=self.position(b,s,f,e);self.assertEqual(t['exit_reason'],'MOMENTUM_NONPOSITIVE_CLOSE_NEXT_OPEN');self.assertIs(e.exit_reason,fn)
    def test_future_changes_no_earlier_fill_change(self):
        from dataclasses import replace
        b,s,f,e=self.fixture();first=self.position(b,s,f,e)[0]
        for i in range(28,len(b)):b[i]=replace(b[i],open=900,high=1000,low=800,close=900)
        self.assertEqual(self.position(b,s,f,e)[0],first)

if __name__=='__main__':unittest.main()

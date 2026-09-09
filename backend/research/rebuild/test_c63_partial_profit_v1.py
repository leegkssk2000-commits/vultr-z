"""Artificial inputs only. Real market execution is separately reserved."""
import unittest
from types import SimpleNamespace as B
from backend.research.rebuild import c63_partial_profit_v1 as c

class PartialTests(unittest.TestCase):
    def data(self):
        bars=[B(open_ts=i*10,open=100.,close=101.) for i in range(6)]
        signal={'signal_index':1}
        features=[{'momentum':m} for m in (0.,4.,3.,2.,1.,0.)]
        trace=[dict(kind='HELD_CLOSE_OBSERVATION',index=i,ts=(i+1)*10,close=101.,exit_reason=None) for i in range(2,6)]
        return bars,signal,features,trace
    def test_positive_deceleration(self):self.assertTrue(c.qualifies(1,2,3,None))
    def test_acceleration_no_partial(self):self.assertFalse(c.qualifies(3,2,3,None))
    def test_flat_momentum_no_partial(self):self.assertFalse(c.qualifies(2,2,3,None))
    def test_nonpositive_momentum_native_not_bypassed(self):self.assertFalse(c.qualifies(0,2,3,None))
    def test_net_zero_no_partial(self):self.assertFalse(c.qualifies(1,2,0,None))
    def test_losing_mark_no_partial(self):self.assertFalse(c.qualifies(1,2,-1,None))
    def test_native_exit_priority(self):self.assertFalse(c.qualifies(1,2,3,'FIXED_TIME_CLOSE'))
    def test_invalid(self):
        for value in (True,float('nan'),float('inf'),'1'):
            with self.assertRaises(ValueError):c.qualifies(value,2,3,None)
    def test_first_only_next_open(self):
        args=self.data();x=c.select_partial(*args,60,lambda a,b:20.)
        self.assertEqual((x['trigger']['index'],x['fill']['index'],len(x['decisions'])),(2,3,1))
    def test_first_open_gap_not_cancelled_by_future_loss(self):
        args=self.data();args[0][3].open=80.
        self.assertEqual(c.select_partial(*args,60,lambda a,b:20.)['fill']['price'],80.)
    def test_excluded_terminal_open(self):
        bars,s,f,t=self.data();x=c.select_partial(bars[:3],s,f[:3],t[:1],30,lambda a,b:20.)
        self.assertTrue(x['pending_at_end']);self.assertIsNone(x['fill'])
    def test_cost_available_at_decision(self):
        args=self.data();calls=[]
        def costs(a,b):calls.append((a,b));return 20.
        c.select_partial(*args,60,costs);self.assertEqual(calls,[(20,30)])
    def test_cost_blocks_gross_positive(self):
        args=self.data();x=c.select_partial(*args,60,lambda a,b:101.)
        self.assertIsNone(x['trigger'])
    def test_future_changes_not_used(self):
        args=self.data();before=c.select_partial(*args,60,lambda a,b:20.)
        args[2][4]['momentum']=999.;args[0][5].close=9999.
        self.assertEqual(before,c.select_partial(*args,60,lambda a,b:20.))
    def test_native_exit_prevents_same_close_partial(self):
        args=self.data();args[3][0]['exit_reason']='FIXED_FLOOR_CLOSE'
        x=c.select_partial(args[0],args[1],args[2],args[3][:1],60,lambda a,b:20.)
        self.assertIsNone(x['trigger'])
    def test_clock_rejected(self):
        args=self.data();args[3][0]['ts']=999
        with self.assertRaises(ValueError):c.select_partial(*args,60,lambda a,b:20.)
    def test_reference_fractions_conserve_values(self):
        z={'gross_bps':100.,'cost_bps':20.,'net_bps':80.,'cost2x_net_bps':60.}
        self.assertEqual(c.aggregate_values(z,z),z)
    def test_entry_fee_not_doubled(self):self.assertEqual(c.aggregate_values({'fee':10.},{'fee':10.})['fee'],10.)
    def test_partial_and_remaining_return(self):
        x=c.aggregate_values({'gross':300.},{'gross':30.});self.assertEqual(x['gross'],210.)
    def test_component_identity(self):
        x=c.aggregate_values(dict(g=100.,c=30.,n=70.,c2=40.),dict(g=30.,c=20.,n=10.,c2=-10.))
        self.assertAlmostEqual(x['g']-x['c'],x['n']);self.assertAlmostEqual(x['g']-2*x['c'],x['c2'])
    def test_fields_must_match(self):
        with self.assertRaises(ValueError):c.aggregate_values({'a':1},{'b':1})

if __name__=='__main__':unittest.main()

class NativeIntegrationTests(unittest.TestCase):
    """Full repository only. Artificial native prices, not market observations."""
    def test_native_entry_final_exit_and_hook_restoration(self):
        from backend.research.rebuild import m1_er_range_rescue_v1 as p
        from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture,rows_of
        from backend.research.rebuild.test_kr3_profit_zone_exit_v1 import COST
        bars=momentum_fixture();rows=rows_of(bars);kw=dict(eval_start_ms=0,eval_end_ms=len(bars)*p.BAR)
        old=p.replay(rows,**kw);fn=p.er.parent._position
        new=c.replay(rows,cost_model=COST,**kw)
        self.assertIs(fn,p.er.parent._position)
        for key in ('entry_ts','entry_price','exit_ts','exit_price','exit_reason','hold_ms'):
            self.assertEqual(old['trades'][0][key],new['trades'][0][key])
        self.assertEqual(old['events'],new['events'])
    def test_disabled_exact_native(self):
        from backend.research.rebuild import m1_er_range_rescue_v1 as p
        from backend.research.rebuild.test_chart_mechanism_execution_v1 import momentum_fixture,rows_of
        bars=momentum_fixture();rows=rows_of(bars);kw=dict(eval_start_ms=0,eval_end_ms=len(bars)*p.BAR)
        self.assertEqual(c.replay(rows,cost_model={},enabled=False,**kw),p.replay(rows,**kw))

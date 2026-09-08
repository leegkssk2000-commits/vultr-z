"""Artificial fixtures only; no market optimization hidden in tests."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from backend.research.rebuild import kr3_c51_entry_context_v1 as c
from backend.research.rebuild.test_kr3_profit_zone_exit_v1 import ProfitZoneTests,COST
class ContextTests(unittest.TestCase):
    def fixture(self):
        rows,b,start,end,i=ProfitZoneTests().fixture()
        # Put a pullback at i-1, after an above-EMA bar at i-2.
        rows[i-2].update(close=100.5);rows[i-1].update(close=99.5);rows[i].update(close=100.5)
        return rows,b,start,end,i
    def forced(self,rows,b,a=True,bb=True):
        return {s['signal_index']:{'A':a,'B':bb,'signal_index':s['signal_index'],'available_at':s['signal_ts']} for s in b['signals']}
    def call(self,rows,b,start,end,**kw):return c.replay(rows,b,eval_start_ms=start,eval_end_ms=end,cost_model=COST,**kw)
    def test_disabled_is_exact_parent(self):
        rows,b,s,e,_=self.fixture()
        self.assertEqual(self.call(rows,b,s,e,enabled=False),c.parent.replay(rows,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST))
    def test_all_accept_identical_geometry_and_reservations(self):
        rows,b,s,e,_=self.fixture();p=c.parent.replay(rows,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST)
        for mode in c.MODES:
            with patch.object(c,'observations',return_value=self.forced(rows,b)):
                out=self.call(rows,b,s,e,mode=mode)
            for key in ('trades','open_positions','trace','reference_events','reference_checkpoint'):self.assertEqual(out[key],p[key])
    def test_veto_has_no_trade_no_cost_and_keeps_reference(self):
        rows,b,s,e,i=self.fixture();p=c.parent.replay(rows,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST)
        with patch.object(c,'observations',return_value=self.forced(rows,b,False,False)):out=self.call(rows,b,s,e)
        self.assertFalse(out['trades']);self.assertFalse(out['open_positions'])
        self.assertEqual(out['reference_checkpoint'],p['reference_checkpoint'])
        self.assertEqual(out['events'][0]['exclusion_reason'],'ENTRY_CONTEXT_AB_VETO')
    def test_factorial_truth_table(self):
        for a in (False,True):
            for b in (False,True):
                o={'A':a,'B':b};self.assertEqual([c.allowed(o,m) for m in c.MODES],[a,b,a and b])
    def test_prefix_invariance_and_no_nextbar_feature(self):
        rows,b,s,e,i=self.fixture();before=c.observations(rows,b)[i]
        r=deepcopy(rows)
        for row in r[i+1:]:row.update(open=900.,high=999.,low=1.,close=950.)
        self.assertEqual(before,c.observations(r,b)[i])
        prefix={k:(v[:i+1] if k in ('ema20','ema50') else v) for k,v in b.items()}
        self.assertEqual(before,c.observations(rows[:i+1],prefix)[i])
    def test_pre_pullback_not_signal_adx(self):
        rows,b,s,e,i=self.fixture();n=len(rows)
        d={'adx':[30.]*n,'plus_di':[30.]*n,'minus_di':[10.]*n};d['adx'][i-3]=29.;d['adx'][i]=1.
        with patch.object(c.f,'directional_movement',return_value=d):o=c.observations(rows,b)[i]
        self.assertTrue(o['A']);self.assertEqual(o['trend_index'],i-2)
        self.assertLess(o['trend_available_at'],rows[i-1]['bar_close_ts'])
    def test_no_prior_trend_is_false(self):
        rows,b,s,e,i=self.fixture()
        for row in rows[:i]:row['close']=99.5
        self.assertFalse(c.observations(rows,b)[i]['A'])
    def test_atr_seed_and_lag_excludes_signal_range(self):
        rows,b,s,e,i=self.fixture();o=c.observations(rows,b)[i]
        r=deepcopy(rows);r[i].update(high=10000.,low=.01)
        self.assertEqual(o['atr_previous'],c.observations(r,b)[i]['atr_previous'])
        self.assertEqual(o['extension_atr'],c.observations(r,b)[i]['extension_atr'])
    def test_B_equality_and_above_cap(self):
        rows,b,s,e,i=self.fixture();atr=c.observations(rows,b)[i]['atr_previous']
        rows[i].update(close=100.+atr,high=103.)
        self.assertTrue(c.observations(rows,b)[i]['B'])
        rows[i]['close']+=.01
        self.assertFalse(c.observations(rows,b)[i]['B'])
    def test_immutable_and_hook_restored(self):
        rows,b,s,e,i=self.fixture();before=deepcopy((rows,b));d=c.parent.parent.kr.d;fn=d._path
        self.call(rows,b,s,e);self.assertEqual(before,(rows,b));self.assertIs(fn,d._path)
    def test_exception_restores_hook(self):
        rows,b,s,e,i=self.fixture();d=c.parent.parent.kr.d;fn=d._path
        with patch.object(c,'observations',return_value=self.forced(rows,b)),patch.object(c.parent,'path',side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError,'injected'):self.call(rows,b,s,e)
        self.assertIs(fn,d._path)
    def test_gap_rejected_before_features(self):
        rows,b,s,e,i=self.fixture();rows[12]['bar_open_ts']+=1
        with self.assertRaises(RuntimeError):self.call(rows,b,s,e)
    def test_end_pending_same_as_parent(self):
        rows,b,s,e,i=self.fixture();rows=rows[:i+3];b={k:(v[:i+3] if k in ('ema20','ema50') else v) for k,v in b.items()};e=len(rows)*c.BAR
        with patch.object(c,'observations',return_value=self.forced(rows,b)):out=self.call(rows,b,s,e)
        p=c.parent.replay(rows,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST)
        self.assertEqual(out['open_positions'],p['open_positions']);self.assertEqual(len(out['open_positions']),1)
    def test_checkpoint_reapplication(self):
        rows,b,s,e,i=self.fixture();out=self.call(rows,b,s,e)
        again=self.call(rows,b,s,e,reference_checkpoint=out['reference_checkpoint'])
        self.assertEqual(out,again)
    def test_no_signals(self):
        rows,b,s,e,i=self.fixture();b['signals']=[]
        out=self.call(rows,b,s,e);self.assertEqual(out['events'],[])
    def test_zero_ATR_never_divides(self):
        rows,b,s,e,i=self.fixture()
        for row in rows:row.update(open=100.,high=100.,low=100.,close=100.)
        self.assertIsNone(c.observations(rows,b)[i]['extension_atr']);self.assertFalse(c.observations(rows,b)[i]['B'])
if __name__=='__main__':unittest.main()

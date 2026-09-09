"""Artificial-only tests. Existing C54 rules and temporal boundaries remain fixed."""
from copy import deepcopy
from unittest.mock import patch
import unittest
from backend.research.rebuild import kr3_c54_pullback_failure_v1 as c
from backend.research.rebuild.test_kr3_profit_zone_exit_v1 import ProfitZoneTests,COST

class PullbackFailureTests(unittest.TestCase):
    def fixture(self):
        rows,b,s,e,i=ProfitZoneTests().fixture()
        for j in range(len(rows)):
            rows[j].update(open=100.,close=100.,high=101.,low=99.,volume=10.)
            b['ema20'][j]=100.;b['ema50'][j]=90.
        rows[i-3].update(close=101.,high=102.)
        rows[i-2].update(close=99.,low=98.)
        rows[i-1].update(close=99.5,low=98.8)
        rows[i].update(close=100.5,low=99.)
        rows[i+1].update(open=100.5,close=98.5,low=98.3)
        rows[i+2].update(open=98.5,close=97.,low=96.)
        rows[i+3].update(open=95.,close=97.,high=999.,low=1.)
        return rows,b,s,e,i
    def call(self,rows,b,s,e,**kw):
        return c.replay(rows,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST,**kw)
    def raw(self,rows,b,e,i,enabled=True):
        return c.path(rows,dict(signal_index=i,signal_ts=rows[i]['bar_close_ts']),b['ema20'],b['ema50'],e,enabled,cost_model=COST)
    def test_whole_pullback_floor_not_signal_low(self):
        r,b,s,e,i=self.fixture();o=c.original_pullback_floor(r,b['signals'][0],b['ema20'])
        self.assertEqual((o['trend_index'],o['start_index'],o['end_index']),(i-3,i-2,i))
        self.assertEqual(o['price'],98.);self.assertLess(o['price'],r[i]['low'])
        self.assertEqual(o['available_at'],b['signals'][0]['signal_ts'])
    def test_disabled_exact_parent(self):
        r,b,s,e,i=self.fixture()
        self.assertEqual(self.call(r,b,s,e,enabled=False),c.entry_parent.replay(r,b,eval_start_ms=s,eval_end_ms=e,cost_model=COST,mode='B'))
    def test_suppressed_signal_low_then_whole_floor_gap_exit(self):
        r,b,s,e,i=self.fixture();out=self.call(r,b,s,e);t=out['trades'][0]
        self.assertEqual((t['entry_index'],t['exit_index']),(i+1,i+3))
        self.assertEqual(t['exit_reason'],c.FLOOR_EXIT);self.assertEqual(t['exit_price'],95.)
        self.assertEqual(t['low_exit_state']['status'],c.SUPPRESSED)
        self.assertIsNone(t['profit_zone_state']['armed_index'])
        self.assertEqual(t['exit_trigger']['signal_index'],i+2)
        self.assertEqual(t['mfe_bps'],max(0.,(101./100.5-1)*10000))
    def test_floor_equality_not_breach(self):
        r,b,s,e,i=self.fixture();r[i+2]['close']=98.
        t,o,tr=self.raw(r[:i+3],b,(i+3)*c.BAR,i)
        self.assertFalse(any(x['kind']==c.FLOOR_TRIGGER for x in tr))
    def test_low_wick_is_not_completed_close(self):
        r,b,s,e,i=self.fixture();r[i+2].update(close=98.5,low=1.)
        t,o,tr=self.raw(r[:i+3],b,(i+3)*c.BAR,i)
        self.assertFalse(any(x['kind']==c.FLOOR_TRIGGER for x in tr))
    def test_parent_ema_exit_priority(self):
        r,b,s,e,i=self.fixture();b['ema20'][i+2]=89.
        t,_,tr=self.raw(r,b,e,i)
        self.assertEqual(t['exit_reason'],'EMA20_NOT_ABOVE_EMA50_NEXT_OPEN')
        self.assertFalse(any(x['kind']==c.FLOOR_TRIGGER for x in tr))
    def test_parent_allowed_signal_low_priority(self):
        r,b,s,e,i=self.fixture();b['ema50'][i+1]=99.
        t,_,tr=self.raw(r,b,e,i)
        self.assertEqual(t['exit_reason'],c.m2.EXIT)
        self.assertFalse(any(x['kind']==c.FLOOR_TRIGGER for x in tr))
    def test_already_armed_C51_protection_keeps_priority(self):
        r,b,s,e,i=self.fixture()
        r[i+1].update(close=104.,low=100.,high=105.);b['ema20'][i+1]=103.
        t,_,tr=self.raw(r,b,e,i)
        self.assertEqual(t['exit_reason'],c.GUARD_EXIT);self.assertEqual(t['profit_zone_state']['armed_index'],i+1)
        self.assertFalse(any(x['kind']==c.FLOOR_TRIGGER for x in tr))
    def test_pending_next_open_outside_window(self):
        r,b,s,e,i=self.fixture();end=(i+3)*c.BAR
        t,o,tr=self.raw(r[:i+3],b,end,i)
        self.assertIsNone(t);self.assertEqual(o['pending_exit_signal_ts'],end)
        self.assertTrue(o['pending_exit_trigger']['original_pullback_floor_condition'])
        self.assertFalse(o['terminal_liquidation'])
    def test_native_timeout_priority(self):
        r,b,s,e,i=self.fixture()
        for j in range(i+1,i+c.HOLD):r[j].update(open=100.,close=100.,low=99.,high=101.)
        r[i+c.HOLD].update(close=97.,low=96.)
        t,_,tr=self.raw(r,b,e,i)
        self.assertEqual(t['exit_index'],i+c.HOLD)
        self.assertFalse(any(x['kind']==c.FLOOR_TRIGGER for x in tr))
    def test_floor_is_fixed_and_future_suffix_unused(self):
        r,b,s,e,i=self.fixture();before=c.original_pullback_floor(r,b['signals'][0],b['ema20'])
        for row in r[i+1:]:row.update(low=.00001,high=10000.,close=500.)
        self.assertEqual(before,c.original_pullback_floor(r,b['signals'][0],b['ema20']))
        self.assertEqual(before,c.original_pullback_floor(r[:i+1],b['signals'][0],b['ema20'][:i+1]))
    def test_exit_open_only_future_HLC_excluded(self):
        r,b,s,e,i=self.fixture();t,_,_=self.raw(r,b,e,i);rr=deepcopy(r)
        for row in rr[i+3:]:row.update(high=1e6,low=.0001,close=1e5)
        u,_,_=self.raw(rr,b,e,i)
        for field in ('entry_price','exit_price','exit_ts','gross_bps','mfe_bps','mae_bps'):self.assertEqual(t[field],u[field])
    def test_reference_clock_survives_early_exit(self):
        r,b,s,e,i=self.fixture();p=self.call(r,b,s,e,enabled=False);child=self.call(r,b,s,e)
        for k in ('reference_checkpoint','reference_events','reference_opportunities'):self.assertEqual(child[k],p[k])
    def test_inputs_and_hook_restored(self):
        r,b,s,e,i=self.fixture();old=deepcopy((r,b));fn=c.c51.path
        self.call(r,b,s,e);self.assertEqual(old,(r,b));self.assertIs(fn,c.c51.path)
    def test_error_restores_hook(self):
        r,b,s,e,i=self.fixture();fn=c.c51.path
        with patch.object(c,'original_pullback_floor',side_effect=RuntimeError('injected')):
            with self.assertRaisesRegex(RuntimeError,'injected'):self.call(r,b,s,e)
        self.assertIs(c.c51.path,fn)
    def test_restart_reference_checkpoint(self):
        r,b,s,e,i=self.fixture();a=self.call(r,b,s,e)
        self.assertEqual(a,self.call(r,b,s,e,reference_checkpoint=a['reference_checkpoint']))
    def test_missing_pullback_preserves_parent_path(self):
        r,b,s,e,i=self.fixture();r[i-1]['close']=101.
        self.assertFalse(c.original_pullback_floor(r,b['signals'][0],b['ema20'])['available'])
        t,o,tr=self.raw(r,b,e,i);pt,po,ptr=self.raw(r,b,e,i,False)
        if t:
            t.pop('original_pullback_floor');self.assertEqual(t,pt)
        else:o.pop('original_pullback_floor');self.assertEqual(o,po)
    def test_gap_rejected_by_full_replay(self):
        r,b,s,e,i=self.fixture();r[12]['bar_open_ts']+=1
        with self.assertRaises(RuntimeError):self.call(r,b,s,e)
    def test_no_signals(self):
        r,b,s,e,i=self.fixture();b['signals']=[]
        self.assertEqual(self.call(r,b,s,e)['events'],[])
if __name__=='__main__':unittest.main()

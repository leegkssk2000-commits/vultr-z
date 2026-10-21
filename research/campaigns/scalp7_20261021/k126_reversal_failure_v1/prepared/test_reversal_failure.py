from copy import deepcopy
import unittest
import pandas as pd
from reversal_failure import ExitComparison,REASON,crossed,h
TF=h.TF;START=h.START

def fixture(side=1):
    values=[(100,102,99,101),(101,101.5,100,100.5),(100.5,101,98.5,98.8),(98.4,100,98,99),(99,99.5,96,97),(98,100,97.5,99),(99,100,98,99)]
    rows=[]
    for i,(o,high,low,c) in enumerate(values):
        if side==-1:o,high,low,c=200-o,200-low,200-high,200-c
        rows.append(dict(open_ts_ms=START+i*TF,close_ts_ms=START+(i+1)*TF,available_ts_ms=START+(i+1)*TF,segment_id=0,open=float(o),high=float(high),low=float(low),close=float(c)))
    f=pd.DataFrame(rows)
    signal=dict(identity=h.positive.KELTNER_PARENT,lane='keltner_holygrail',symbol='BTC-USDT',timeframe_min=30,
        signal_open_ts_ms=START,signal_ts_ms=START+TF,segment_id=0,side=side,stop_price=97. if side==1 else 103.,max_hold_bars=25,
        take_profit_r=None,partial_take_profit_r=2.,partial_fraction=.1,
        meta=dict(frozen_cost_bps=14.,atr_price=2.,be_arm_r=1.,fallback_stop_atr_mult=1.2,entry_cost_gate=dict(atr_price=2.,min_ratio=4.5)))
    return signal,f

def run(s,f,on=True):
    rows,index=h.execution._frame_records(f,30);x=ExitComparison(on)
    out=x.single(s,f,rows,index,14.,h.positive.exit_update,h.positive.entry_update)
    return out,x

class Tests(unittest.TestCase):
    def test_long_next_open_not_close_or_boundary(self):
        s,f=fixture();(t,u,until,r),x=run(s,f)
        self.assertEqual(t['reason'],REASON);self.assertEqual(t['exit_ts_ms'],START+3*TF)
        self.assertEqual(t['exit_prices']['BTC-USDT'],98.4);self.assertEqual(len(x.events),1)
    def test_short_symmetry(self):
        s,f=fixture(-1);(t,*_),x=run(s,f);self.assertEqual(t['reason'],REASON)
        self.assertAlmostEqual(t['exit_prices']['BTC-USDT'],101.6)
    def test_touch_is_not_close_break(self):
        self.assertFalse(crossed(1,99,99,102));self.assertFalse(crossed(-1,102,99,102))
    def test_wick_only_no_new_exit(self):
        s,f=fixture();f.loc[2,'close']=100
        (t,*_),x=run(s,f);self.assertNotEqual(t['reason'],REASON);self.assertEqual(len(x.events),0)
    def test_stop_wins_before_close_decision(self):
        s,f=fixture();f.loc[2,'low']=96
        (t,*_),x=run(s,f);self.assertEqual(t['reason'],'STOP_FIRST');self.assertEqual(x.events,[])
    def test_gap_stop_precedes_observer(self):
        s,f=fixture();f.loc[2,['open','high','low','close']]=[96,101,95,98.8]
        (t,*_),x=run(s,f);self.assertEqual(t['reason'],'OPEN_GAP_STOP');self.assertEqual(t['exit_prices']['BTC-USDT'],96.)
    def test_unfavourable_next_open_is_paid(self):
        s,f=fixture();f.loc[3,['open','high','low','close']]=[90,100,89,99]
        (t,*_),x=run(s,f);self.assertEqual(t['exit_prices']['BTC-USDT'],90.)
    def test_disabled_exact_original_extension(self):
        s,f=fixture();(actual,*_),x=run(s,f,False)
        rows,idx=h.execution._frame_records(f,30);c=deepcopy(s);c['max_hold_bars']=50
        expected=h.execution._single(c,f,rows,idx,14.,h.timeout._continuation_callback([]),h.positive.entry_update)[0]
        self.assertEqual(actual,expected);self.assertEqual(actual['reason'],'STOP_FIRST')
    def test_later_future_values_do_not_select_exit(self):
        s,f=fixture();a=run(s,f)[0][0];f.loc[4:,['open','high','low','close']]=[1000,1100,900,1000]
        self.assertEqual(a,run(s,f)[0][0])
    def test_nextbar_extremes_not_used_for_fill(self):
        s,f=fixture();a=run(s,f)[0][0];f.loc[3,['high','low','close']]=[1000,1,500]
        self.assertEqual(a,run(s,f)[0][0])
    def test_no_nextbar_no_fabricated_exit(self):
        s,f=fixture();out,x=run(s,f.iloc[:3].copy());self.assertIsNone(out[0]);self.assertIsNotNone(out[1])
    def test_late_available_bar_unresolved(self):
        s,f=fixture();f.loc[2,'available_ts_ms']+=1
        out,x=run(s,f);self.assertIsNone(out[0]);self.assertIsNotNone(out[1]);self.assertEqual(x.events,[])
    def test_existing_scratch_same_time_keeps_reason(self):
        s,f=fixture();f.loc[2:4,['open','high','low','close']]=[100,101.5,99.5,100]
        f.loc[5,['open','high','low','close']]=[100,101,98.5,98.8]
        (t,*_),x=run(s,f);self.assertEqual(t['reason'],'HG_FROZEN_5BAR_MFE_SCRATCH');self.assertFalse(x.events[0]['actionable'])
    def test_inputs_not_mutated(self):
        s,f=fixture();ss=deepcopy(s);ff=f.copy();run(s,f);self.assertEqual(s,ss);pd.testing.assert_frame_equal(f,ff)
    def test_builder_is_isolated(self):
        before=h.k.execution;fun=ExitComparison(True).build();self.assertTrue(callable(fun));self.assertIs(h.k.execution,before)
    def test_invalid_numeric_input_rejected(self):
        with self.assertRaises(ValueError):crossed(1,float('nan'),99,102)

if __name__=='__main__':unittest.main(verbosity=2)

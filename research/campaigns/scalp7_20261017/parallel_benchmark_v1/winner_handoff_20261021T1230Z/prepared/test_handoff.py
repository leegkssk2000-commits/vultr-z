from copy import deepcopy
import unittest
import pandas as pd
from handoff_comparison import Handoff,execution,positive,TF,START

def fixture(side=1, high=103., n=55):
    bars=[]
    for i in range(n):
        o,h,l,c=(100.,100.5,99.5,100.) if i==0 else ((101.,high,100.5,101.5) if i==1 else (102.,high,101.5,102.))
        if side==-1:o,h,l,c=200-o,200-l,200-h,200-c
        bars.append(dict(open_ts_ms=START+i*TF,close_ts_ms=START+(i+1)*TF,available_ts_ms=START+(i+1)*TF,segment_id=0,open=o,high=h,low=l,close=c))
    f=pd.DataFrame(bars)
    s=dict(identity=positive.KELTNER_PARENT,lane='keltner_holygrail',symbol='BTC-USDT',timeframe_min=30,
      signal_open_ts_ms=START,signal_ts_ms=START+TF,segment_id=0,side=side,stop_price=100.,max_hold_bars=25,
      take_profit_r=None,partial_take_profit_r=2.,partial_fraction=.1,
      meta=dict(frozen_cost_bps=14.,atr_price=1.,be_arm_r=1.,fallback_stop_atr_mult=1.2,entry_cost_gate=dict(atr_price=1.,min_ratio=4.5)))
    new=deepcopy(s);new.update(signal_open_ts_ms=START+25*TF,signal_ts_ms=START+26*TF)
    return s,new,f

def shortened(s,new,f,enabled=True):
    rec,idx=execution._frame_records(f,30)
    return Handoff(enabled).shortened({'signal':s,'entry_ts_ms':START+TF},new,f,rec,idx,14.)

class Tests(unittest.TestCase):
    def test_long_handoff_at_next_open(self):
        s,n,f=fixture();t,until,state=shortened(s,n,f)
        self.assertEqual(t['exit_ts_ms'],START+26*TF);self.assertEqual(until,t['exit_ts_ms'])
        self.assertEqual(t['exit_prices']['BTC-USDT'],102.);self.assertEqual(t['cost_bps'],14.)
        self.assertEqual(state['hold_bars'],25);self.assertAlmostEqual(state['remaining'],.9)
    def test_short_symmetry(self):
        s,n,f=fixture(-1);t,_,_=shortened(s,n,f);self.assertEqual(t['exit_prices']['BTC-USDT'],98.)
    def test_opposite_side_not_switched(self):
        s,n,f=fixture();n['side']=-1;self.assertIsNone(shortened(s,n,f))
    def test_before_deadline_not_switched(self):
        s,n,f=fixture();n.update(signal_open_ts_ms=START+24*TF,signal_ts_ms=START+25*TF)
        self.assertIsNone(shortened(s,n,f))
    def test_fill_cost_rejection_keeps_old_position(self):
        s,n,f=fixture();n['meta']['entry_cost_gate']['atr_price']=.00001
        self.assertIsNone(shortened(s,n,f))
    def test_sub2R_and_future2R_do_not_qualify(self):
        s,n,f=fixture(high=102.5);f.loc[27:,'high']=110.;self.assertIsNone(shortened(s,n,f))
    def test_signal_bar_protective_stop_first(self):
        s,n,f=fixture();f.loc[25,'low']=99.;self.assertIsNone(shortened(s,n,f))
    def test_no_retroactive_signal_open_fill(self):
        s,n,f=fixture();n['signal_ts_ms']+=1;self.assertIsNone(shortened(s,n,f))
    def test_no_following_bar(self):
        s,n,f=fixture(n=26);self.assertIsNone(shortened(s,n,f))
    def test_disabled_unchanged(self):
        s,n,f=fixture();self.assertIsNone(shortened(s,n,f,False))
    def test_adverse_next_open_not_old_close_price(self):
        s,n,f=fixture();f.loc[26,['open','high','low','close']]=[99.,103.,98.,100.]
        t,_,_=shortened(s,n,f);self.assertEqual(t['exit_prices']['BTC-USDT'],99.)
    def test_post_decision_prices_do_not_choose_old_close(self):
        s,n,f=fixture();before=shortened(s,n,f)[0];g=f.copy();g.loc[27:,['open','high','low','close']]=[50.,51.,49.,50.]
        self.assertEqual(before,shortened(s,n,g)[0])
    def test_new_bar_high_low_do_not_choose_handoff(self):
        s,n,f=fixture();a=shortened(s,n,f)[0];f.loc[26,['high','low','close']]=[1000.,1.,500.]
        self.assertEqual(a,shortened(s,n,f)[0])
    def test_inputs_preserved(self):
        s,n,f=fixture();a,b,c=deepcopy(s),deepcopy(n),f.copy();shortened(s,n,f)
        self.assertEqual(s,a);self.assertEqual(n,b);pd.testing.assert_frame_equal(f,c)
    def test_native_adapter_compiles(self):
        fun,src=Handoff(False).build();self.assertTrue(callable(fun));self.assertIn('_handoff.switch',src)

if __name__=='__main__':unittest.main(verbosity=2)

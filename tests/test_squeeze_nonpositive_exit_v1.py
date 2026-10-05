"""Generated-data rule, causal clock, full-opportunity and accounting tests."""
import copy
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from ops import squeeze_nonpositive_exit_v1 as m
from backend.research.rebuild import scalp7_positive_lanes_v2 as native


def fixture():
    minute=m.clock.MINUTE;tf=m.clock.TF
    rows=[[t,100.,100.1,99.9,100.,1,t+minute+1,0,'test'] for t in range(0,1500*minute,minute)]
    f=pd.DataFrame([{'open_ts_ms':t,'close_ts_ms':t+tf,'available_ts_ms':t+tf+61000,
                    'open':100.,'high':100.1,'low':99.9,'close':100.,'volume':1.,'segment_id':0}
                   for t in range(0,1500*minute,tf)])
    ready={int(r.open_ts_ms):int(r.available_ts_ms) for r in f.itertuples()}
    s={'identity':m.PARENT,'lane':'squeeze_break','symbol':'BTC-USDT','side':1,'timeframe_min':30,
       'signal_open_ts_ms':1200*minute,'signal_ts_ms':1230*minute,'stop_price':98.,'max_hold_bars':4,
       'take_profit_r':None,'meta':{'regime':'PANIC_DISPERSION','frozen_cost_bps':14.,
       'entry_cost_gate':{'atr_price':2.,'min_ratio':4.},'fallback_stop_atr_mult':2.,'be_arm_r':None}}
    return m.as_child(s),f,rows,ready


def position():
    s,f,_,_=fixture();h=f.iloc[:44];b=h.iloc[-1].to_dict()
    p={'signal':s,'side':1,'entry_price':100.,'initial_risk':2.,'mfe_R':0.,'mae_R':0.,
       'stop_price':98.,'entry_ts_ms':1232*m.clock.MINUTE,'hold_bars':2,'remaining':1.}
    return p,b,h


class FailureExitTests(unittest.TestCase):
    def test_negative_and_zero_trigger(self):
        for last in (-.1,0.):
            p,b,h=position()
            with self.subTest(last=last),patch.object(native,'_last_momenta',return_value=np.array([3,2,last])):
                u=m.management(p,b,h);self.assertTrue(u['exit_next_open']);self.assertEqual(u['reason'],m.RULE)
    def test_positive_native_hold_unchanged(self):
        p,b,h=position()
        with patch.object(native,'_last_momenta',return_value=np.array([1,2,3])):
            self.assertFalse(m.management(p,b,h)['exit_next_open'])
    def test_native_positive_weak_exit_preserved(self):
        p,b,h=position()
        with patch.object(native,'_last_momenta',return_value=np.array([3,2,1])):
            self.assertEqual(m.management(p,b,h)['reason'],'SQUEEZE_TWO_WEAK_MOMENTUM_NEXT_OPEN')
    def test_no_mutation_or_be_inheritance(self):
        p,b,h=position();before=copy.deepcopy(p)
        m.management(p,b,h);self.assertEqual(before,p)
        parent=m.native_signal(p['signal']);parent['meta']['be_arm_r']=1.
        with self.assertRaisesRegex(Exception,'NO_BE'):m.as_child(parent)
    def test_other_identity_rejected(self):
        p,b,h=position();p['signal']['identity']=m.PARENT
        with self.assertRaisesRegex(Exception,'CHILD_IDENTITY'):m.management(p,b,h)
    def test_native_cost_guard_preserved(self):
        s,_,_,_=fixture();s['meta']['entry_cost_gate']['atr_price']=.001
        self.assertTrue(m.admission(s,100)['reject'])
    def test_future_history_rejected(self):
        p,b,h=position();h=h.copy();h.loc[h.index[0],'available_ts_ms']=b['available_ts_ms']+1
        with self.assertRaisesRegex(Exception,'FUTURE'):m.management(p,b,h)
    def test_nonfinite_momentum_rejected(self):
        p,b,h=position()
        with patch.object(native,'_last_momenta',return_value=np.array([1,2,np.nan])):
            with self.assertRaisesRegex(Exception,'NONFINITE'):m.management(p,b,h)
    def test_actual_native_zero_exit_after_receipt_not_bar_close(self):
        s,f,rows,ready=fixture()
        t,_,_,why,events=m.clock.simulate(s,f,rows,ready,14,m.admission,m.management)
        self.assertIsNone(why);self.assertEqual(t['reason'],m.RULE)
        self.assertEqual(t['entry_ts_ms'],1232*m.clock.MINUTE)
        self.assertEqual(t['exit_ts_ms'],1292*m.clock.MINUTE)
        self.assertEqual(events[0]['bar_open_ms'],1260*m.clock.MINUTE)
        self.assertGreater(t['exit_ts_ms'],events[0]['input_ready_ms'])
    def test_resting_stop_before_observation(self):
        s,f,rows,ready=fixture();rows[1240][3]=97.
        t,_,_,_,events=m.clock.simulate(s,f,rows,ready,14,m.admission,m.management)
        self.assertEqual(t['reason'],'CLOCKED_MINUTE_STOP_FIRST');self.assertEqual(events,[])
    def test_full_stream_frees_later_signal_only_after_exit_ack(self):
        s,f,rows,ready=fixture();s2=copy.deepcopy(s)
        s2.update(signal_open_ts_ms=1290*m.clock.MINUTE,signal_ts_ms=1320*m.clock.MINUTE)
        result=m.replay_child([s,s2],{'BTC-USDT':f},{'BTC-USDT':rows},ready,{'BTC-USDT':14.})
        self.assertEqual(len(result['trades']),2)
        self.assertLess(result['trades'][0]['outcome_available_ts_ms'],result['trades'][1]['entry_ts_ms'])
    def test_no_partial_or_target(self):
        s,_,_,_=fixture();s=m.native_signal(s);s['take_profit_r']=2.
        with self.assertRaisesRegex(Exception,'NO_BE_PARTIAL'):m.as_child(s)
    def test_pair_delta_includes_unique_opportunities(self):
        def row(k,g):return {'symbol':'BTC-USDT','side':1,'signal_ts_ms':m.START+k,
            'outcome_available_ts_ms':m.START+k+1,'gross_bps':g,'cost_bps':14.,'reason':'generated'}
        p={'trades':[row(1,-100),row(2,200)]};c={'trades':[row(1,-20),row(3,30)]}
        r=m.paired(p,c)['1x'];self.assertEqual(r['common_T'],1)
        self.assertEqual(r['child_only_T'],1);self.assertEqual(r['parent_only_T'],1)
        self.assertAlmostEqual(r['total_net_delta_bps'],80+16-186)
    def test_saved_signal_clone_only_changes_identity_and_provenance(self):
        s,_,_,_=fixture();parent=m.native_signal(s);child=m.as_child(parent)
        self.assertEqual(parent,m.native_signal(child));self.assertEqual(parent['identity'],m.PARENT)

if __name__=='__main__':unittest.main()

from copy import deepcopy
import unittest
import pandas as pd
from backend.research.rebuild import scalp7_execution_v2 as e
from backend.research.rebuild import scalp7_positive_lanes_v2 as p
import importlib.util
from pathlib import Path
_spec = importlib.util.spec_from_file_location("winner_timeout_comparison", Path(__file__).with_name("winner_timeout_comparison.py"))
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

TF = 1800000


def fixture(high=102.5, side=1, n=34):
    bars=[]
    for i in range(n):
        o,h,l,c = (100.,100.5,99.5,100.) if i == 0 else ((101.,high,100.5,101.5) if i == 1 else (102.,high,101.5,102.))
        if side == -1:
            o,h,l,c = 200-o,200-l,200-h,200-c
        bars.append(dict(open_ts_ms=i*TF,close_ts_ms=(i+1)*TF,
                         available_ts_ms=(i+1)*TF,segment_id=0,open=o,high=h,low=l,close=c))
    f=pd.DataFrame(bars)
    s=dict(identity=p.KELTNER_PARENT,lane='keltner_holygrail',symbol='BTC-USDT',
           timeframe_min=30,signal_open_ts_ms=0,signal_ts_ms=TF,segment_id=0,
           side=side,stop_price=100.,max_hold_bars=25,take_profit_r=None,
           partial_take_profit_r=2.,partial_fraction=.1,
           meta=dict(frozen_cost_bps=14.,atr_price=1.,be_arm_r=1.,fallback_stop_atr_mult=1.2,
                     entry_cost_gate=dict(atr_price=1.,min_ratio=4.5)))
    # Entry is101 long or99 short, initial risk1.
    return s,f


def control(s,f):
    rows,idx=e._frame_records(f,30)
    t,u,_,reason=e._single(deepcopy(s),f,rows,idx,14.,p.exit_update,p.entry_update)
    assert t is not None and u is None and reason is None
    return t


class Tests(unittest.TestCase):
    def run_pair(self,s,f,**kw):
        return m.compare_one(control(s,f),f,window_end_ms=len(f)*TF,
               hard_max_hold_bars=30,horizon_authority='SYNTHETIC_FIXTURE_ONLY_NOT_A_REAL_RULE',**kw)

    def test_sub_2r_preserves_original_time_exit(self):
        s,f=fixture(); r=self.run_pair(s,f)
        self.assertEqual(r['child']['exit_ts_ms'],26*TF)
        self.assertFalse(r['timeout_decisions'][0]['extend'])
        self.assertAlmostEqual(r['net_delta_trade_bps'],0)

    def test_observed_2r_extends_to_explicit_cap(self):
        s,f=fixture(high=103.); r=self.run_pair(s,f,additional_carry_bps=1.)
        self.assertEqual(r['child']['exit_ts_ms'],31*TF)
        self.assertTrue(r['timeout_decisions'][0]['extend'])
        self.assertEqual(r['child']['hold_bars'],30)
        self.assertFalse(r['economic_pass'])

    def test_original_stop_dominates_two_r_on_same_bar(self):
        s,f=fixture(high=104.); f.loc[1,'low']=99.
        r=self.run_pair(s,f)
        self.assertEqual(r['child']['reason'],'STOP_FIRST')
        self.assertEqual(r['timeout_decisions'],[])
        self.assertAlmostEqual(r['net_delta_trade_bps'],0)

    def test_gap_after_extension_uses_open(self):
        s,f=fixture(high=103.); f.loc[27,['open','high','low','close']]=[99.,101.,98.,100.]
        r=self.run_pair(s,f,additional_carry_bps=0.)
        self.assertEqual(r['child']['reason'],'OPEN_GAP_STOP')
        self.assertEqual(r['child']['exit_prices']['BTC-USDT'],99.)
        self.assertLess(r['net_delta_trade_bps'],0)

    def test_extended_winner_can_make_more_but_is_not_economic_proof(self):
        s,f=fixture(high=103.)
        f.loc[27:,['open','high','low','close']]=[104.,106.,103.5,105.]
        r=self.run_pair(s,f,additional_carry_bps=0.)
        self.assertGreater(r['net_delta_trade_bps'],0)
        self.assertFalse(r['economic_pass'])

    def test_unresolved_is_not_zero_loss_or_profitable_close(self):
        s,f=fixture(high=103.,n=29); r=self.run_pair(s,f)
        self.assertIsNone(r['child']); self.assertIsNotNone(r['unresolved'])
        self.assertIsNone(r['net_delta_trade_bps'])
        self.assertFalse(r['valuation_complete'])

    def test_missing_carry_for_changed_exit_blocks_net_claim(self):
        s,f=fixture(high=103.); r=self.run_pair(s,f)
        self.assertIsNone(r['net_delta_trade_bps'])
        self.assertFalse(r['valuation_complete'])

    def test_short_symmetry(self):
        s,f=fixture(high=103.,side=-1); r=self.run_pair(s,f,additional_carry_bps=0.)
        self.assertTrue(r['timeout_decisions'][0]['extend'])
        self.assertEqual(r['child']['hold_bars'],30)

    def test_inputs_unchanged(self):
        s,f=fixture(high=103.); saved=control(s,f); before=deepcopy(saved); frame=f.copy(deep=True)
        m.compare_one(saved,f,window_end_ms=len(f)*TF,hard_max_hold_bars=30,
                      horizon_authority='SYNTHETIC_ONLY')
        self.assertEqual(saved,before); pd.testing.assert_frame_equal(f,frame)

    def test_no_future_two_r_at_timeout(self):
        s,f=fixture()
        f.loc[27:,'high']=105.
        r=self.run_pair(s,f)
        self.assertEqual(r['child']['exit_ts_ms'],26*TF)
        self.assertFalse(r['timeout_decisions'][0]['extend'])

    def test_unbound_horizon_rejected(self):
        s,f=fixture(); saved=control(s,f)
        with self.assertRaisesRegex(ValueError,'HORIZON_REQUIRED'):
            m.compare_one(saved,f,window_end_ms=len(f)*TF,hard_max_hold_bars=30,horizon_authority='')

    def test_control_mismatch_not_hidden(self):
        s,f=fixture(); saved=control(s,f); saved['gross_bps'] += 1
        with self.assertRaisesRegex(ValueError,'CONTROL_ECONOMICS_MISMATCH'):
            m.compare_one(saved,f,window_end_ms=len(f)*TF,hard_max_hold_bars=30,horizon_authority='SYNTHETIC')

    def test_fresh_touch_signal_parent_translation(self):
        s,f=fixture(high=103.); saved=control(s,f)
        saved['identity']=m.CONTROL; saved['signal']['identity']=m.CONTROL
        saved['signal']['meta']['lifecycle_adapter_parent_identity']=p.KELTNER_PARENT
        r=m.compare_one(saved,f,window_end_ms=len(f)*TF,hard_max_hold_bars=30,
                        horizon_authority='SYNTHETIC')
        self.assertEqual(r['control']['identity'],m.CONTROL)
        self.assertEqual(r['child']['identity'],m.COMPARISON)

    def test_late_data_cannot_authorize_extension(self):
        s,f=fixture(high=103.); saved=control(s,f); f.loc[25,'available_ts_ms'] += 1
        with self.assertRaisesRegex(ValueError,'CONTROL_REPLAY'):
            m.compare_one(saved,f,window_end_ms=len(f)*TF,hard_max_hold_bars=30,horizon_authority='SYNTHETIC')

if __name__ == '__main__':
    unittest.main()

from __future__ import annotations
import unittest
from backend.research.architecture_factory.a1_regime_conditioned_flow_momentum_evaluator_v1 import feature_for_index,micro_confirmation

def bars(n=120):
    out=[];p=100.0
    for i in range(n):
        p*=1.0004
        out.append({'ts_ms':i*300000,'open':p-0.02,'high':p+0.10,'low':p-0.10,'close':p,'volume':100+i})
    return out

def row(end,flow,book):
    return {'symbol':'BTC-USDT','bucket_start_ms':end-5000,'bucket_end_ms':end,'trade_imbalance':flow,'imbalance_top20_mean':book,'mid_last':100,'trade_quote_notional':1000,'spread_bps_mean':1,'bid_qty_top20_last':10,'ask_qty_top20_last':9,'depth_messages':1}

class T(unittest.TestCase):
    def setUp(self):self.cfg={'momentum_lookback_bars':48,'participation_recent_bars':12,'participation_prior_bars':36,'range_lookback_bars':48,'expected_move_cost_multiple_floor':2.0,'micro_confirm_window_ms':60000,'minimum_complete_micro_buckets':6,'maximum_micro_staleness_ms':15000}
    def test_feature_uses_only_closed_history(self):
        b=bars();f=feature_for_index(b,100,self.cfg,14.0);self.assertTrue(f['pass']);self.assertEqual(f['side'],'long')
    def test_micro_future_never_used(self):
        entry=100000;rs=[row(entry-5000*(i+1),0.4,0.2) for i in range(8)]+[row(entry+5000,-1,-1)];g=micro_confirmation(rs,'BTC-USDT',entry,'long',self.cfg);self.assertTrue(g['pass']);self.assertLessEqual(g['latest_bucket_end_ms'],entry)
    def test_micro_wrong_sign_rejected(self):
        entry=100000;rs=[row(entry-5000*(i+1),-0.4,-0.2) for i in range(8)];self.assertFalse(micro_confirmation(rs,'BTC-USDT',entry,'long',self.cfg)['pass'])
if __name__=='__main__':unittest.main()

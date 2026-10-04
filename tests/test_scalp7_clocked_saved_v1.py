"""Generated saved-ledger arithmetic only, no strategy or market callbacks."""
import unittest
from ops import verify_scalp7_clocked_saved_v1 as a
class SavedTests(unittest.TestCase):
 def row(self,gross=30,cost=14,signal=None,outcome=None):
  return {'identity':'test','symbol':'BTC-USDT','signal_ts_ms':signal or a.START+1,
          'exit_ts_ms':a.START+120000,'outcome_available_ts_ms':outcome or a.START+180000,
          'gross_bps':gross,'cost_bps':cost}
 def test_costs_not_leverage(self):
  rows=[self.row()]
  self.assertEqual(a.metrics(rows,1)['Net_bps'],16)
  self.assertEqual(a.metrics(rows,2)['Net_bps'],2)
 def test_exact_end_and_carryin_excluded(self):
  rows=[self.row(),self.row(outcome=a.END),self.row(signal=a.START-1)]
  self.assertEqual(a.metrics(rows,1)['T'],1)
 def test_simultaneous_outcomes_netted_dd(self):
  rows=[self.row(114),self.row(-86)]
  self.assertEqual(a.metrics(rows,1)['DD_bps'],0)
 def test_empty_not_profitable(self):
  v=a.metrics([],1)
  self.assertEqual(v['T'],0);self.assertIsNone(v['PF']);self.assertIsNone(v['WR_pct'])
 def test_unequal_amount_rejected(self):
  with self.assertRaises(AssertionError):a.near(1,2)
if __name__=='__main__':unittest.main()

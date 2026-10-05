"""Synthetic tests for independent accounting, never a market replay."""
import unittest
import tempfile
from pathlib import Path
from ops import verify_squeeze_nonpositive_saved_v1 as a

class SavedArithmeticTests(unittest.TestCase):
    def rows(self):
        def r(t,g,s='BTC-USDT'):
            return {'symbol':s,'side':1,'identity':a.CHILD,'signal_ts_ms':a.START+t-1,
                    'exit_ts_ms':a.START+t,'outcome_available_ts_ms':a.START+t,'gross_bps':g,'cost_bps':14.}
        return [r(10,114),r(20,-36),r(20,34,'ETH-USDT'),r(30,-6)]
    def test_costs_expectancy_and_grouped_drawdown(self):
        m=a.metrics(self.rows(),1)
        self.assertEqual(m['T'],4);self.assertEqual(m['WR_pct'],50.)
        self.assertEqual(m['Net_bps'],50.);self.assertEqual(m['DD_bps'],50.)
        self.assertAlmostEqual(m['PF'],120/70)
    def test_stress_is_same_trades_and_cost_not_leverage(self):
        x=a.metrics(self.rows(),1);y=a.metrics(self.rows(),2)
        self.assertEqual(x['T'],y['T']);self.assertEqual(x['Gross_bps'],y['Gross_bps'])
        self.assertEqual(y['Net_bps'],x['Net_bps']-x['Cost_bps'])
    def test_exact_end_outcome_excluded(self):
        rs=self.rows();rs[0]['outcome_available_ts_ms']=a.END
        self.assertEqual(a.metrics(rs,1)['T'],3)
    def test_nonfinite_and_mismatch_rejected(self):
        for v in (float('nan'),float('inf'),1.):
            with self.assertRaises(AssertionError):a.close(v,0.)
    def test_bundle_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.xz';p.write_bytes(b'bad')
            with self.assertRaisesRegex(AssertionError,'BUNDLE_HASH'):a.unpack(p,'0'*64)

if __name__=='__main__':unittest.main()

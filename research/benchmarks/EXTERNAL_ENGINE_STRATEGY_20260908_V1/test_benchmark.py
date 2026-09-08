"""Synthetic benchmark semantics tests; no observed market outcomes."""
import json
from pathlib import Path
import tempfile
import unittest
import pandas as pd
import benchmark_run as b

class BenchmarkTests(unittest.TestCase):
    def test_canonical_hash_matches_legacy_no_newline_convention(self):
        import hashlib
        self.assertEqual(b.sha({'x':1}),hashlib.sha256(b'{"x":1}').hexdigest())
    def test_cost_floor_and_settlement_boundary(self):
        c={'fee_bps':10,'spread_bps':1,'impact_bps':2,'funding_p95_per_settlement_bps':3}
        self.assertEqual(b.cost(0,0,c),20)
        self.assertEqual(b.cost(0,3*28800000,c),22)
        self.assertEqual(b.cost(28800000,3*28800000,c),20)
    def test_force_exit_is_open_mark_not_completed_win(self):
        end=10*b.ft.BAR
        packet={'rows_by':{'BTC-USDT':[{'close':90}]},'costs':{'BTC-USDT':{'fee_bps':10,'spread_bps':1,'impact_bps':2,'funding_p95_per_settlement_bps':1}}}
        r={'pair':'BTC/USDT','open_date':'1970-01-01T04:00:00Z','close_date':'1970-01-02T12:00:00Z','open_rate':100,'close_rate':110,'exit_reason':'force_exit'}
        t=b.normalize_engine([r],packet,end)[0]
        self.assertFalse(t['closed']);self.assertEqual(t['exit_price'],90)
        self.assertAlmostEqual(t['gross_bps'],-1000)
        self.assertEqual(t['cost2_bps'],t['gross_bps']-2*t['cost_bps'])
    def test_intrabar_time_is_bounded_not_precise_funding_time(self):
        packet={'rows_by':{'BTC-USDT':[{'close':90}]},'costs':{'BTC-USDT':{'fee_bps':10,'spread_bps':1,'impact_bps':2,'funding_p95_per_settlement_bps':1}}}
        r={'pair':'BTC/USDT','open_date':'1970-01-01T00:00:00Z','close_date':'1970-01-01T04:00:00Z','open_rate':100,'close_rate':90,'exit_reason':'stop_loss'}
        t=b.normalize_engine([r],packet,10*b.ft.BAR)[0]
        self.assertTrue(t['intrabar_time_unobserved']);self.assertEqual(t['exit_ts']-t['exit_ts_lower'],b.ft.BAR)
    def test_mapping_preserves_1000_contract_price_unit(self):
        self.assertEqual('1000PEPE-USDT'.replace('-','/'),'1000PEPE/USDT')
    def test_exclusive_outputs_do_not_overwrite_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a.json';b.write(p,{'x':1})
            with self.assertRaises(RuntimeError):b.write(p,{'x':2})
            self.assertEqual(json.loads(p.read_bytes()),{'x':1})
    def test_network_guard_rejects(self):
        with self.assertRaisesRegex(RuntimeError,'NETWORK_FORBIDDEN'):b.ft.blocked()
    def test_ema_uses_only_prefix(self):
        x=list(range(1,400));a=b.ft.bounded_ema(x,20);c=b.ft.bounded_ema(x[:250],20)
        self.assertEqual(list(a[:250]),list(c))

if __name__=='__main__':unittest.main()

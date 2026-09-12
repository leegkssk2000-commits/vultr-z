import unittest
from backend.research.rebuild import squeeze_kr3_unified_repair_study_v1 as r

class RepairBoundaryTests(unittest.TestCase):
    def test_selects_exact_symbol_cost(self):
        a={'fee_bps':10.,'spread_bps':1.,'impact_bps':2.,'funding_p95_per_settlement_bps':1.}
        b={'fee_bps':11.,'spread_bps':2.,'impact_bps':3.,'funding_p95_per_settlement_bps':2.}
        packet={'costs':{'BTC-USDT':a,'ETH-USDT':b}}
        self.assertIs(r.symbol_cost(packet,'BTC-USDT'),a)
        self.assertIs(r.symbol_cost(packet,'ETH-USDT'),b)
        self.assertNotEqual(r.symbol_cost(packet,'BTC-USDT'),packet['costs'])

    def test_whole_map_and_missing_field_fail_closed(self):
        with self.assertRaises(RuntimeError):
            r.symbol_cost({'costs':{'BTC-USDT':{'fee_bps':10.}}},'BTC-USDT')
        with self.assertRaises(RuntimeError):
            r.symbol_cost({'costs':{}},'BTC-USDT')

    def test_new_ordinals_never_reuse_failed_153(self):
        self.assertEqual(r.CANDIDATES,{'U1':86,'U2':87,'U3':88})
        self.assertEqual(sorted(r.EVALS.values()),[154,155,156,157,158,159])
        self.assertNotIn(153,r.EVALS.values())

if __name__=='__main__': unittest.main()

from __future__ import annotations

import unittest

from backend.research.architecture_factory.a1_gen2_generic_dev_econ_v1 import Expr, _feature_formula


class ExpandedDslTest(unittest.TestCase):
    def setUp(self):
        self.rows=[]
        base=1_700_000_000_000
        for i in range(120):
            o=100.0+i*0.1; c=o+(0.5 if i%2==0 else -0.2)
            self.rows.append({"ts":base+i*300_000,"open":o,"high":max(o,c)+0.3,"low":min(o,c)-0.2,"close":c,"volume":1000.0+i*10})
        self.e=Expr(self.rows,{})

    def test_core_extensions(self):
        i=100
        self.assertIsInstance(self.e.eval(_feature_formula("ema(close,20)"),i),float)
        self.assertGreaterEqual(self.e.eval(_feature_formula("pct_rank(volume,50)"),i),0.0)
        self.assertLessEqual(self.e.eval(_feature_formula("pct_rank(volume,50)"),i),1.0)
        self.assertIsInstance(self.e.eval(_feature_formula("percentile(close,50,90)"),i),float)
        self.assertGreaterEqual(self.e.eval("range_pct()",i),0.0)
        self.assertGreaterEqual(self.e.eval("body_pct()",i),0.0)
        self.assertTrue(0 <= self.e.eval("hour()",i) <= 23)
        self.assertTrue(0 <= self.e.eval("dow()",i) <= 6)

    def test_normalizer(self):
        self.assertEqual(_feature_formula("ema20 = EMA(close,20)"), "ema('close',20)")

    def test_unknown_name_fails_closed(self):
        with self.assertRaises(ValueError):
            self.e.validate("mystery_feature > 1")


if __name__ == "__main__":
    unittest.main()

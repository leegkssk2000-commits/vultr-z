import unittest
from backend.research.prep.g5_validation_harness_v1 import *

ROWS=[
 {"trade_id":"t1","entry_ts":1,"exit_ts":2,"symbol":"BTCUSDT","side":"LONG","net_pnl_r":1.0,"fee_r":0.1,"funding_r":0.0,"slippage_r":0.05,"window_id":"W1","regime":"TREND"},
 {"trade_id":"t2","entry_ts":3,"exit_ts":4,"symbol":"ETHUSDT","side":"SHORT","net_pnl_r":-0.5,"fee_r":0.1,"funding_r":0.01,"slippage_r":0.05,"window_id":"W2","regime":"RANGE"},
]

class TestG5(unittest.TestCase):
 def test_purged_walk_forward(self):
  x=purged_walk_forward(100,train=40,test=20,purge=5,embargo=5)
  self.assertTrue(x); self.assertGreaterEqual(x[0]["test"][0],x[0]["train"][1]+5)
 def test_frozen_manifest(self):
  m=frozen_manifest({"W1":[0,10],"W2":[10,20],"W3":[20,30]})
  self.assertTrue(m["w2_w3_frozen"]); self.assertEqual(m["selection_window"],"W1")
 def test_stress_matrix(self):
  names={x["name"] for x in stress_matrix(base_cost=1,p95_funding=2)}
  self.assertEqual(names,{"BASE","COST_2X","P95_FUNDING","PLUS_ONE_BAR"})
 def test_metric_recompute_and_parity(self):
  m=recompute_metrics(ROWS); self.assertEqual(m["trades"],2); self.assertAlmostEqual(m["net_r"],0.5)
  self.assertTrue(parity(ROWS,list(reversed(ROWS))))
 def test_duplicate_fail_closed(self):
  with self.assertRaises(ValidationError): validate_trade_rows(ROWS+[dict(ROWS[0])])
 def test_concentration(self):
  c=concentration(ROWS,"symbol"); self.assertEqual(c["top_share"],0.5)
 def test_adjacent_and_false_discovery(self):
  self.assertEqual(adjacent_parameter_grid(1.0,.1),[.9,1.0,1.1])
  self.assertTrue(false_discovery_contract(3)["dsr_required"])

if __name__=="__main__": unittest.main()

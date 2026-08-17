import unittest
from backend.research.prep.g10_execution_quality_ledger_v1 import *

R1={"record_id":"r1","ts_utc":"2026-08-17T00:00:00Z","symbol":"BTCUSDT","source_sha":"a","source_type":"PUBLIC_DEPTH","spread_bps":3.0,"depth_vwap_impact_bps":2.0,"notional_usdt":10000,"funding_bps":1.0}
R2={"record_id":"r2","ts_utc":"2026-08-17T00:01:00Z","symbol":"BTCUSDT","source_sha":"b","source_type":"PRIVATE_HISTORY","latency_ms":120,"rejected":False,"partial_fill_ratio":0.8,"stop_slippage_bps":4.0}

class TestG10(unittest.TestCase):
 def test_append_chain(self):
  x=append_record([],R1)
  x=append_record(x,R2,parent_digest=canonical_digest(x))
  self.assertEqual(len(x),2)
 def test_duplicate_rejected(self):
  x=append_record([],R1)
  with self.assertRaises(ExecutionQualityError): append_record(x,R1,parent_digest=canonical_digest(x))
 def test_parent_mismatch_rejected(self):
  x=append_record([],R1)
  with self.assertRaises(ExecutionQualityError): append_record(x,R2,parent_digest="bad")
 def test_calibration_is_read_only(self):
  c=calibrate([R1,R2])
  self.assertEqual(c["records"],2); self.assertFalse(c["order_submission_performed"])
  self.assertEqual(c["size_bucket_slippage_bps"]["LE_10000"]["median"],2.0)
 def test_size_bucket(self):
  self.assertEqual(size_bucket(50000),"LE_50000"); self.assertEqual(size_bucket(50001),"GT_50000")

if __name__=="__main__": unittest.main()

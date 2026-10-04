"""Small saved-only regression tests; no strategy replay."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

P=Path(__file__).resolve().parents[1]/'ops'/'verify_kp1355_saved_result.py'
if not P.exists():P=Path(__file__).with_name('verify_kp1355_saved_result.py')
spec=importlib.util.spec_from_file_location('saved_audit',P)
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class Tests(unittest.TestCase):
    def test_duplicate_and_nonfinite_json_rejected(self):
        for raw in (b'{"a":1,"a":2}',b'{"a":NaN}',b'{"a":Infinity}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):a.strict(raw)
    def test_corrupt_archive_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.zip';p.write_bytes(b'not saved evidence')
            with self.assertRaisesRegex(ValueError,'WRONG_COMPLETED_ARCHIVE'):a.verify(p)
    def test_nonfinite_comparison_rejected(self):
        with self.assertRaises(ValueError):a.near(float('nan'),0)
    def test_simultaneous_outcomes_are_netted_for_dd(self):
        rows=[]
        for i,(ts,gross) in enumerate(((1,-3),(1,5),(2,-2),(3,3))):
            rows.append({'outcome_available_ts_ms':ts,'exit_ts_ms':ts,'symbol':str(i),
                         'identity':'fixture','signal_ts_ms':0,'gross_bps':gross,'cost_bps':0})
        r=a.summarize(rows,1)
        self.assertEqual(r['DD_bps'],2);self.assertEqual(r['MaxLossStreak'],1)
        self.assertEqual(r['Net_bps'],3);self.assertEqual(r['T'],4)

if __name__=='__main__':unittest.main()

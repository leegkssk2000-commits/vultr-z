"""Closure regression only; no engine dependencies or empirical replay."""
from copy import deepcopy
import json
import subprocess
import unittest
import verify_saved as v
class ClosureTests(unittest.TestCase):
    def record(self):return json.loads((v.HERE/'results/BREAK_DEV2025.json').read_bytes())
    def test_actual_saved_result_verification(self):
        self.assertEqual(v.verify()['economic_replays'],0)
    def test_wrong_winner_count_rejected(self):
        r=self.record();r['metrics']['wins']+=1
        with self.assertRaisesRegex(ValueError,'WINS'):v.validate_record(r)
    def test_double_cost_rejected(self):
        r=self.record();r['normalized_trades'][0]['cost_bps']+=1
        with self.assertRaisesRegex(ValueError,'COST_DOUBLECOUNT'):v.validate_record(r)
    def test_closed_workflow_has_no_writer_or_execution(self):
        s=(v.ROOT/'.github/workflows/zel-external-benchmark-v1.yml').read_text()
        for key in ('contents: write','git push','benchmark_run.py --input','workflow_dispatch:', 'schedule:', 'download-artifact','pip install'):
            self.assertNotIn(key,s)
        self.assertIn('persist-credentials: false',s)
        self.assertIn('verify_saved.py',s)
        self.assertIn(v.BUDGET,s)
    def test_pipefail_propagates_python_error(self):
        r=subprocess.run(['bash','-o','pipefail','-c',"python -c 'raise SystemExit(9)' | cat"],capture_output=True,timeout=5)
        self.assertEqual(r.returncode,9)
if __name__=='__main__':unittest.main()

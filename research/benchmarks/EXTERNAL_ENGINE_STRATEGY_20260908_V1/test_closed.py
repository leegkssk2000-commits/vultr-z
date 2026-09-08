"""Closure regression only; no engine dependencies or empirical replay."""
from copy import deepcopy
import json
import subprocess
import unittest
import hashlib
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch
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
class ResultAnchorTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='benchmark-anchor-fixture-')
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        shutil.copytree(v.HERE,self.root,dirs_exist_ok=True)

    def replace_result_and_receipt(self):
        # A coherent, already-observed alternative payload passes arithmetic.
        # Relabeling it as BREAK must still fail the original-outcome anchor.
        result=json.loads((self.root/'results/HERACLES_DEV2025.json').read_bytes())
        result['kind']='BREAK'
        v.validate_record(result)
        raw=json.dumps(result,sort_keys=True,separators=(',',':')).encode()
        (self.root/'results/BREAK_DEV2025.json').write_bytes(raw)
        receipt_path=self.root/'receipts/BREAK_DEV2025.json'
        receipt=json.loads(receipt_path.read_bytes())
        receipt['result_sha256']=hashlib.sha256(raw).hexdigest()
        receipt_path.write_text(json.dumps(receipt,sort_keys=True,separators=(',',':')))

    def test_coherent_result_and_adjacent_receipt_cannot_replace_original(self):
        self.replace_result_and_receipt()
        with self.assertRaisesRegex(ValueError,'ORIGINAL_EXECUTED_BYTES_CHANGED'):
            v.verify_anchor(self.root)

    def test_rewriting_adjacent_anchor_also_cannot_reseal_outcomes(self):
        self.replace_result_and_receipt()
        path=self.root/'RESULT_ANCHOR.json'
        anchor=json.loads(path.read_bytes())
        for name in ('results/BREAK_DEV2025.json','receipts/BREAK_DEV2025.json'):
            anchor['files_sha256'][name]=hashlib.sha256((self.root/name).read_bytes()).hexdigest()
        path.write_text(json.dumps(anchor,sort_keys=True,indent=2)+'\n')
        with self.assertRaisesRegex(ValueError,'RESULT_ANCHOR_MANIFEST_CHANGED'):
            v.verify_anchor(self.root)

    def test_main_verification_requires_anchor_before_arithmetic(self):
        with patch.object(v,'verify_anchor',side_effect=ValueError('ANCHOR_SENTINEL')):
            with self.assertRaisesRegex(ValueError,'ANCHOR_SENTINEL'):
                v.verify()

if __name__=='__main__':unittest.main()

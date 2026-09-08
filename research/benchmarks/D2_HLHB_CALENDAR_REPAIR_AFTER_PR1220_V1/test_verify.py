import gzip,json,shutil,tempfile,unittest
from copy import deepcopy
from pathlib import Path
import verify_saved as v
class SavedChecks(unittest.TestCase):
    def result(self,kind='D2'):
        return json.loads(gzip.decompress((v.HERE/'results'/kind/'RESULT.json.gz').read_bytes()))
    def test_actual_two_results(self):
        value=v.verify(expected_manifest_sha=v.sha((v.HERE/'FINAL_HASHES.json').read_bytes()))
        self.assertEqual((value['candidates'],value['evaluations'],value['new_valid']),(49,78,2))
    def test_before_period_rejected(self):
        r=self.result();r['normalized_trades'][0]['entry_ts']=v.START-1
        with self.assertRaisesRegex(ValueError,'INVALID_CALENDAR'):v.validate_rows(r)
    def test_cost_edit_rejected(self):
        r=self.result();r['normalized_trades'][0]['net_bps']+=10
        with self.assertRaisesRegex(ValueError,'NET_MISMATCH'):v.validate_rows(r)
    def test_duplicate_origin_rejected(self):
        r=self.result();r['normalized_trades'].append(deepcopy(r['normalized_trades'][0]))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_ORIGIN'):v.validate_rows(r)
    def test_callback_errors_cannot_pass(self):
        r=self.result();r['parity']['callback_errors']=[{'error':'injected'}]
        with self.assertRaisesRegex(ValueError,'D2_UNRESOLVED'):v.validate_rows(r)
    def test_wrong_summary_cannot_pass(self):
        r=self.result('HLHB');r['metrics']['terminal_net']+=100
        with self.assertRaisesRegex(ValueError,'METRIC_MISMATCH'):v.validate_rows(r)
    def test_force_exit_cannot_be_dropped(self):
        r=self.result();r['normalized_trades']=[t for t in r['normalized_trades'] if t['closed']]
        with self.assertRaisesRegex(ValueError,'COUNTS_MISMATCH'):v.validate_rows(r)
    def test_result_and_manifest_joint_change_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'repo/research/benchmarks'/v.HERE.name
            root.parent.mkdir(parents=True);shutil.copytree(v.HERE,root)
            pin=v.sha((root/'FINAL_HASHES.json').read_bytes())
            target=root/'results/D2/RESULT.json.gz';target.write_bytes(b'changed')
            m=json.loads((root/'FINAL_HASHES.json').read_bytes());m['results/D2/RESULT.json.gz']=v.sha(target.read_bytes())
            (root/'FINAL_HASHES.json').write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'MANIFEST_DRIFT'):v.verify(root,pin)
    def test_new_location_with_complete_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/'repo/research/benchmarks'/v.HERE.name
            root.parent.mkdir(parents=True);shutil.copytree(v.HERE,root)
            shutil.copytree(v.FROZEN,root.parent/v.FROZEN.name)
            self.assertEqual(v.verify(root)['new_valid'],2)
    def test_completed_workflow_is_verification_only(self):
        p=v.HERE.parents[2]/'.github/workflows/d2-hlhb-calendar-repair-v1.yml'
        text=p.read_text()
        for forbidden in ['contents: write','git push','execute.py','pip install','workflow_dispatch:','schedule:','persist-credentials: true']:
            self.assertNotIn(forbidden,text)
        self.assertIn('contents: read',text)
        self.assertIn('verify_saved.py',text)
if __name__=='__main__':unittest.main()

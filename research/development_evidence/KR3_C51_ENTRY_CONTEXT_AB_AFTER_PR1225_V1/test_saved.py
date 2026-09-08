import gzip,json,tempfile,unittest
from copy import deepcopy
from pathlib import Path
import verify_saved as v
class SavedTests(unittest.TestCase):
    def result(self):return v.gz(v.HERE/'B/DEV2025/RESULT.json.gz')
    def test_all_records(self):self.assertEqual(v.verify()['evaluation_total'],90)
    def test_future_feature_rejected(self):
        r=self.result();r['events'][0]['entry_context']['available_at']+=1
        with self.assertRaisesRegex(ValueError,'FEATURE_CLOCK'):v.check_context(r,'B')
    def test_atr_signal_bar_timestamp_rejected(self):
        r=self.result();r['events'][0]['entry_context']['atr_available_at']=r['events'][0]['signal_ts']
        with self.assertRaisesRegex(ValueError,'ATR_NOT_LAGGED'):v.check_context(r,'B')
    def test_disallowed_admission_rejected(self):
        r=self.result();e=next(e for e in r['events'] if e['status']!='EXCLUDED')
        e['entry_context'].update(B=False,extension_atr=2.)
        with self.assertRaisesRegex(ValueError,'DISALLOWED_ENTRY'):v.check_context(r,'B')
    def test_cost_edit_rejected(self):
        r=self.result();r['trades'][0]['net_bps']+=10
        check=v.load_checker(v.HERE.parents[2])
        with self.assertRaises(ValueError):check.check_raw(v.gz(v.HERE/'B/DEV2025/RAW.json.gz'),r,v.read(v.HERE.parents[2]/v.PARENT/'COSTS.json'),v.read(v.HERE/'SPEC.json')['periods']['DEV2025'])
    def test_entry_only_cannot_relabel_original_winners(self):
        r=self.result();check=v.load_checker(v.HERE.parents[2]);r['trades'][0]['net_bps']+=10
        with self.assertRaises(ValueError):check.check_metrics(r)
    def test_manifest_rewrite_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'a/b/c';p.mkdir(parents=True)
            (p/'FINAL_HASHES.json').write_text('{}')
            # load_checker runs before pin: use actual root for a wrong immutable pin.
            with self.assertRaisesRegex(ValueError,'MANIFEST_DRIFT'):v.verify(pin='0'*64)
    def test_roundoff_not_strict_goal_success(self):
        s=v.read(v.HERE/'SUMMARY.json');p=s['periods']['SEEN2026']
        self.assertLess(abs(p['B']['snapshot']['marked_DD_trade_sum_bps']-p['C51']['marked_DD_trade_sum_bps']),1e-7)
        self.assertIn('NOT_ESTABLISHED',v.read(v.HERE/'INTERPRETATION.json')['adjudication'])
    def test_finished_workflow_has_no_economic_path(self):
        txt=(v.HERE.parents[2]/'.github/workflows/kr3-c51-entry-context-v1.yml').read_text()
        for item in ('contents: write','git push','download-artifact','_study_v1','workflow_dispatch:','schedule:'):
            self.assertNotIn(item,txt)
if __name__=='__main__':unittest.main()

"""Post-outcome regressions over saved rows only, never engine execution."""
from copy import deepcopy
import unittest
from pathlib import Path
import verify_saved as s
class SavedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=s.HERE;cls.v=s.checker(cls.root.parents[2]);cls.parent=s.gz(cls.root.parents[2]/s.PARENT/'B/DEV2025/RESULT.json.gz');cls.result=s.gz(cls.root/'DEV2025/RESULT.json.gz')
    def test_full(self):self.assertEqual(s.verify()['raw_positions'],237)
    def test_raw_volume_mismatch_fails_bound_projection(self):
        r=deepcopy(self.result);r['events'][0]['entry_context']['participation']['source_bars'][0]['volume']+=1
        self.assertNotEqual(s.digest(s.source_projection(r)),s.read(self.root/'SOURCE_BINDING.json')['DEV2025']['projection_sha256'])
    def test_future_observation_fails(self):
        r=deepcopy(self.result);r['events'][0]['entry_context']['participation']['source_bars'][0]['ts']+=1
        with self.assertRaisesRegex(ValueError,'SOURCE_CLOCK'):s.check_features(self.parent,r,self.v)
    def test_false_body_mean_fails(self):
        r=deepcopy(self.result);r['events'][0]['entry_context']['participation']['mean_pullback_abs_body']+=1
        with self.assertRaises(ValueError):s.check_features(self.parent,r,self.v)
    def test_filter_cannot_be_silently_disabled(self):
        r=deepcopy(self.result);e=next(e for e in r['events'] if e['exclusion_reason']==s.VETO);e['status']='COMPLETED';e['admission']=True
        with self.assertRaisesRegex(ValueError,'DISALLOWED_ADMISSION'):s.check_features(self.parent,r,self.v)
    def test_parent_atr_cannot_change(self):
        r=deepcopy(self.result);r['events'][0]['entry_context']['B']=not r['events'][0]['entry_context']['B']
        with self.assertRaisesRegex(ValueError,'PARENT_ENTRY_CONTEXT_CHANGED'):s.check_features(self.parent,r,self.v)
    def test_net_change_fails_independent_cost(self):
        r=deepcopy(self.result);r['trades'][0]['net_bps']+=10
        with self.assertRaises(ValueError):self.v.check_raw(s.gz(self.root/'DEV2025/RAW.json.gz'),r,s.read(self.root.parents[2]/s.C51/'COSTS.json'),s.read(self.root/'SPEC.json')['periods']['DEV2025'])
    def test_roundoff_is_not_DD_improvement(self):
        p=deepcopy(self.parent['metrics']);c=deepcopy(p);c['marked_DD_trade_sum_bps']-=1e-12
        self.assertFalse(s.checks(p,c,self.v)['daily_DD_down'])
    def test_changed_manifest_is_not_trusted(self):
        with self.assertRaisesRegex(ValueError,'MANIFEST_DRIFT'):s.verify(pin='0'*64)
    def test_completion_is_readonly(self):
        t=(self.root.parents[2]/'.github/workflows/kr3-c54-effort-progress-v1.yml').read_text()
        for bad in ('contents: write','git push','download-artifact','_study_v1','workflow_dispatch:','schedule:','persist-credentials: true'):self.assertNotIn(bad,t)
if __name__=='__main__':unittest.main()

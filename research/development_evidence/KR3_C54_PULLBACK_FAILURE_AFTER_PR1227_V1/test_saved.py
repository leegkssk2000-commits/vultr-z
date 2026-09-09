"""Saved-evidence regressions only; no historical strategy execution."""
from copy import deepcopy
import unittest
import verify_saved as s
import verify_details as d
class SavedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=s.HERE;cls.repo=cls.root.parents[2];cls.v=s.checker(cls.repo)
        cls.raw=s.gz(cls.root/'DEV2025/RAW.json.gz');cls.result=s.gz(cls.root/'DEV2025/RESULT.json.gz')
        cls.parent=s.gz(cls.repo/s.PARENT/'B/DEV2025/RESULT.json.gz')
    def first_floor(self,raw):
        return next(t for r in raw.values() for t in r['trades'] if t.get('exit_reason')==s.EXIT)
    def test_all_saved_economics(self):self.assertEqual(s.verify()['raw_positions'],262)
    def test_all_postrun_details(self):self.assertTrue(d.verify()['postrun_interpretation_recomputed'])
    def test_future_floor_source_fails(self):
        raw=deepcopy(self.raw);self.first_floor(raw)['original_pullback_floor']['source'][0]['bar_close_ts']+=1
        with self.assertRaisesRegex(ValueError,'FLOOR_SOURCE_CLOCK'):s.check_floor(raw,self.result,self.parent,self.v)
    def test_floor_minimum_fails(self):
        raw=deepcopy(self.raw);self.first_floor(raw)['original_pullback_floor']['price']+=1
        with self.assertRaisesRegex(ValueError,'FLOOR_MINIMUM'):s.check_floor(raw,self.result,self.parent,self.v)
    def test_C51_armed_state_conflict_fails(self):
        raw=deepcopy(self.raw);self.first_floor(raw)['profit_zone_state']['armed_index']=1
        with self.assertRaisesRegex(ValueError,'FLOOR_AFTER_C51_ARM'):s.check_floor(raw,self.result,self.parent,self.v)
    def test_signal_context_change_fails(self):
        result=deepcopy(self.result);result['events'][0]['entry_context']['B']=not result['events'][0]['entry_context']['B']
        with self.assertRaisesRegex(ValueError,'C54_ENTRY_FEATURE_CHANGED'):s.check_floor(self.raw,result,self.parent,self.v)
    def test_net_mutation_fails(self):
        result=deepcopy(self.result);result['trades'][0]['net_bps']+=10
        with self.assertRaises(ValueError):self.v.check_raw(self.raw,result,s.read(self.repo/s.C51/'COSTS.json'),s.read(self.root/'SPEC.json')['periods']['DEV2025'])
    def test_source_binding_not_self_report(self):
        raw=deepcopy(self.raw);self.first_floor(raw)['original_pullback_floor']['source'][0]['low']+=1
        self.assertNotEqual(s.digest(s.projection(raw)),s.read(self.root/'SOURCE_BINDING.json')['DEV2025']['projection_sha256'])
    def test_interpretation_number_mutation_fails(self):
        expected=s.read(self.root/'DETAILS.json')['DEV2025'];changed=deepcopy(expected);changed['net_without_hype']+=100
        with self.assertRaises(ValueError):self.v.same(changed,expected,'DERIVED_DETAILS')
    def test_float_difference_not_improvement(self):
        p=deepcopy(self.parent['metrics']);c=deepcopy(p);c['marked_DD_trade_sum_bps']-=1e-12
        self.assertFalse(s.checks(p,c,self.v)['daily_DD_down'])
    def test_manifest_changed_with_results_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,'MANIFEST_DRIFT'):s.verify(pin='0'*64)
    def test_completed_workflow_no_economics(self):
        text=(self.repo/'.github/workflows/kr3-c54-pullback-failure-v1.yml').read_text()
        for term in ('contents: write','git push','download-artifact','_study_v1','workflow_dispatch:','schedule:','persist-credentials: true'):
            self.assertNotIn(term,text)
        self.assertIn('contents: read',text)
if __name__=='__main__':unittest.main()

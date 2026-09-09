"""Saved data regressions: no engine replay or market acquisition."""
from copy import deepcopy
from unittest.mock import patch
import unittest
import verify_saved as s
class SavedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=s.HERE;cls.repo=cls.root.parents[2];cls.v=s.checker(cls.repo)
        cls.costs=s.read(cls.repo/s.C51/'COSTS.json');cls.spec=s.read(cls.root/'SPEC.json')
        cls.parent=s.gz(cls.repo/s.C54/'B/DEV2025/RESULT.json.gz');cls.result=s.gz(cls.root/'FIB/DEV2025/RESULT.json.gz')
    def test_all_saved_rows(self):self.assertEqual(s.verify()['child_raw_positions'],39)
    def test_cell_arithmetic(self):
        self.assertEqual(sum(s.check_cell(self.root,p,m,self.v,self.costs,self.spec) for p in s.PERIODS for m in s.MODES),39)
    def test_M1_original_path(self):self.assertEqual(s.check_m1(self.root,self.v,self.costs),132)
    def test_future_pivot_rejected(self):
        r=deepcopy(self.result);e=next(e for e in r['events'] if e['entry_context']['price_context']['anchor'])
        e['entry_context']['price_context']['anchor']['high']['known_index']=e['signal_index']
        with self.assertRaisesRegex(ValueError,'LOOKAHEAD_PIVOT'):s.check_context(self.parent,r,'FIB',self.v)
    def test_ratio_change_rejected(self):
        r=deepcopy(self.result);e=next(e for e in r['events'] if e['entry_context']['price_context']['anchor'])
        e['entry_context']['price_context']['depth']+=.01
        with self.assertRaises(ValueError):s.check_context(self.parent,r,'FIB',self.v)
    def test_fictitious_volume_dependency_rejected(self):
        r=deepcopy(self.result);r['events'][0]['entry_context']['price_context']['volume_used']=True
        with self.assertRaisesRegex(ValueError,'VOLUME_OR_VARIANT_DRIFT'):s.check_context(self.parent,r,'FIB',self.v)
    def test_raw_net_mutation_rejected(self):
        r=deepcopy(self.result);r['trades'][0]['net_bps']+=10
        with self.assertRaises(ValueError):self.v.check_raw(s.gz(self.root/'FIB/DEV2025/RAW.json.gz'),r,self.costs,self.spec['periods']['DEV2025'])
    def test_M1_false_recovery_number_rejected(self):
        original=s.read;data=original(self.root/'M1_DIAGNOSIS.json');data['DEV2025']['rows'][0]['observed_peak_net_bps']+=1
        def altered(p):return data if str(p).endswith('M1_DIAGNOSIS.json') else original(p)
        with patch.object(s,'read',altered):
            with self.assertRaises(ValueError):s.check_m1(self.root,self.v,self.costs)
    def test_manifest_edit_not_trusted(self):
        with self.assertRaisesRegex(ValueError,'MANIFEST_DRIFT'):s.verify(pin='0'*64)
    def test_closed_workflow_no_economic_dispatch(self):
        txt=(self.repo/'.github/workflows/c54-price-retracement-v1.yml').read_text()
        for bad in ('contents: write','git push','download-artifact','_study_v1','workflow_dispatch:','schedule:','persist-credentials: true'):self.assertNotIn(bad,txt)
if __name__=='__main__':unittest.main()

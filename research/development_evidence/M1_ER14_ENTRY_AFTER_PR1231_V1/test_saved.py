from copy import deepcopy
import unittest
from pathlib import Path
import verify_saved as s
class SavedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r=s.HERE;cls.repo=cls.r.parents[2];cls.v=s.checker(cls.repo);cls.spec=s.read(cls.r/'SPEC.json');cls.costs=s.read(cls.repo/s.C51/'COSTS.json')
        cls.parent=s.gz(cls.repo/s.OLD/'M1/DEV2025/RESULT.json.gz');cls.original=s.gz(cls.repo/s.OLD/'M1/DEV2025/RAW.json.gz')
        cls.raw=s.gz(cls.r/'DEV2025/RAW.json.gz');cls.result=s.gz(cls.r/'DEV2025/RESULT.json.gz');cls.proof=s.read(cls.r/'SOURCE_PROOF.json')['DEV2025']
    def check(self,raw=None,result=None):
        return s.check_preserved(raw or self.raw,result or self.result,self.original,self.parent,self.costs,self.spec['periods']['DEV2025'],self.proof,self.v)
    def test_full(self):self.assertEqual(s.verify()['raw_positions'],124)
    def test_all_preserved_raw(self):self.assertEqual(self.check(),(95,109))
    def test_er_value_mutation(self):
        r=deepcopy(self.raw);next(iter(r.values()))['events'][0]['er_context']['current']['value']+=.1
        with self.assertRaises(ValueError):self.check(raw=r)
    def test_future_feature_clock(self):
        r=deepcopy(self.raw);next(iter(r.values()))['events'][0]['er_context']['available_at']+=1
        with self.assertRaisesRegex(ValueError,'ER_CLOCK'):self.check(raw=r)
    def test_original_source_quote_mutation(self):
        r=deepcopy(self.result);r['events'][0]['er_context']['source_closes'][0]['close']+=1
        with self.assertRaisesRegex(ValueError,'ORIGINAL_PRICE_PROJECTION'):self.check(result=r)
    def test_net_mutation(self):
        r=deepcopy(self.result);r['trades'][0]['net_bps']+=1
        with self.assertRaises(ValueError):self.check(result=r)
    def test_removed_loss_not_phantom_win(self):
        r=deepcopy(self.raw);e=next(e for z in r.values() for e in z['events'] if e['exclusion_reason']=='ER14_NOT_INCREASING');e['admission']=True
        with self.assertRaises(ValueError):self.check(raw=r)
    def test_exit_cannot_change(self):
        r=deepcopy(self.raw);t=next(t for z in r.values() for t in z['trades']);t['exit_price']*=1.01
        with self.assertRaisesRegex(ValueError,'ORIGINAL_PATH_CHANGED'):self.check(raw=r)
    def test_details_not_just_hashes(self):
        expected=s.detail(self.parent,self.result,self.v);data=s.read(self.r/'DETAILS.json')['DEV2025'];self.v.same(data,expected,'DETAILS')
        data['foregone_closed_win_bps']+=1
        with self.assertRaises(ValueError):self.v.same(data,expected,'DETAILS')
    def test_manifest_mutation(self):
        with self.assertRaisesRegex(ValueError,'MANIFEST_DRIFT'):s.verify(pin='0'*64)
    def test_finished_workflow_no_dispatch(self):
        txt=(self.repo/'.github/workflows/m1-er14-entry-v1.yml').read_text()
        for bad in ('contents: write','git push','download-artifact','_study_v1','workflow_dispatch:','schedule:','persist-credentials: true'):self.assertNotIn(bad,txt)
if __name__=='__main__':unittest.main()

import unittest
from copy import deepcopy
import verify_saved as v
class SavedTests(unittest.TestCase):
    def raw(self):return v.gz(v.HERE/'DEV2025/RAW.json.gz')
    def costs(self):return v.read(v.OLD/'COSTS.json')
    def target(self,r):
        return next(t for data in r.values() for t in data['trades'] if t.get('profit_zone_state',{}).get('recovery_events'))
    def test_both_actual_ledgers(self):
        self.assertEqual(v.math_period('DEV2025')['rows'],203)
        self.assertEqual(v.math_period('SEEN2026')['rows'],79)
    def test_wrong_cost_rejected(self):
        r=self.raw();self.target(r)['profit_zone_state']['recovery_events'][0]['decision_cost']['cost_bps']+=10
        with self.assertRaises(ValueError):v.check_recovery(r,self.costs())
    def test_repeated_grace_rejected(self):
        r=self.raw();e=self.target(r)['profit_zone_state']['recovery_events'];e.extend(deepcopy(e))
        with self.assertRaises(ValueError):v.check_recovery(r,self.costs())
    def test_nonpositive_mark_cannot_be_fabricated(self):
        r=self.raw();self.target(r)['profit_zone_state']['recovery_events'][0]['completed_close_net_mark_bps']=1.
        with self.assertRaises(ValueError):v.check_recovery(r,self.costs())
    def test_confirmation_must_be_next_bar(self):
        r=self.raw();self.target(r)['profit_zone_state']['recovery_events'][1]['index']+=1
        with self.assertRaises(ValueError):v.check_recovery(r,self.costs())
    def test_no_fake_recovery(self):
        r=self.raw();self.target(r)['profit_zone_state']['recovery_events'][1]['kind']='CONFIRM_AFTER_ONE_CLOSE'
        with self.assertRaises(ValueError):v.check_recovery(r,self.costs())
    def test_no_replay_workflow(self):
        text=(v.ROOT/'.github/workflows/kr3-c51-recovery-v1.yml').read_text()
        for bad in ('contents: write','git push','download-artifact',' execute ',' reserve ',' freeze ','workflow_dispatch:','schedule:'):
            self.assertNotIn(bad,text)
        self.assertIn('verify_saved.py',text)
if __name__=='__main__':unittest.main()

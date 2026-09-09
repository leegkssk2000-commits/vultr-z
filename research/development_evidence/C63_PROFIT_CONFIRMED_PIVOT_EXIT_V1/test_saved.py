import unittest
from copy import deepcopy
from unittest.mock import patch
import verify_saved as v

class SavedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=v.gz(v.HERE/'DEV2025/FULL/RAW.json.gz');cls.symbol=next(s for s,x in cls.raw.items() if any(t['exit_reason']==v.REASON+'_NEXT_OPEN' for t in x['trades']))
        cls.x=cls.raw[cls.symbol];cls.t=next(t for t in cls.x['trades'] if t['exit_reason']==v.REASON+'_NEXT_OPEN')
        cls.cost=v.read(v.REPO/v.BASE/'COSTS.json')[cls.symbol];cls.end=v.read(v.HERE/'SPEC.json')['periods']['DEV2025']['runoff_end_ms']
    def path(self,t=None,tr=None):return v.path_check(t or self.t,tr or self.x['trace'],self.cost,self.end)
    def test_all_saved(self):
        out=v.verify(derived_sha='5870b2c150999de446456ce474ae514f5f8a13d6d0048350bb1ba9c301939408');self.assertEqual(sum(c['counts']['positions'] for c in out.values()),262)
    def test_guard_missing(self):
        tr=[x for x in self.x['trace'] if not (x['signal_index']==self.t['signal_index'] and x['kind']=='PROFIT_PIVOT_OBSERVATION')]
        with self.assertRaisesRegex(ValueError,'EVERY_HELD'):self.path(tr=tr)
    def test_future_confirmation(self):
        tr=deepcopy(self.x['trace']);q=next(o['newly_confirmed_low'] for o in tr if o['kind']=='PROFIT_PIVOT_OBSERVATION' and o['signal_index']==self.t['signal_index'] and o['newly_confirmed_low']);q['known_index']+=1
        with self.assertRaisesRegex(ValueError,'CONFIRMATION_CLOCK'):self.path(tr=tr)
    def test_protected_level_change(self):
        tr=deepcopy(self.x['trace']);o=next(o for o in tr if o['kind']=='PROFIT_PIVOT_OBSERVATION' and o['signal_index']==self.t['signal_index']);o['active_after']=999
        with self.assertRaises(ValueError):self.path(tr=tr)
    def test_exit_not_next_open(self):
        t=deepcopy(self.t);t['exit_ts']+=v.BAR
        with self.assertRaisesRegex(ValueError,'NEXT_OPEN_CLOCK'):self.path(t=t)
    def test_no_fake_resident_stop(self):
        t=deepcopy(self.t);t['exchange_resident_stop']=True
        with self.assertRaisesRegex(ValueError,'FALSE_PROTECTION'):self.path(t=t)
    def test_completed_workflow_no_runtime(self):
        s=(v.REPO/'.github/workflows/c63-profit-pivot-v1.yml').read_text()
        for bad in ('contents: write','economic-once','_study_v1','git push','workflow_dispatch','download','schedule:'):self.assertNotIn(bad,s)

if __name__=='__main__':unittest.main()

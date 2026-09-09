"""Saved counterexamples only; no market engine or new financial experiment."""
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import verify_saved as s

class SavedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=s.HERE;cls.raw=s.gz(cls.root/'DEV2025/FULL/RAW.json.gz')
        cls.symbol=next(k for k,v in cls.raw.items() if any(t['exit_reason']==s.REASON+'_NEXT_OPEN' for t in v['trades']))
        cls.r=cls.raw[cls.symbol];cls.t=next(t for t in cls.r['trades'] if t['exit_reason']==s.REASON+'_NEXT_OPEN')
        cls.e=next(e for e in cls.r['events'] if e['signal_index']==cls.t['signal_index'])
        cls.cost=s.read(cls.root.parents[2]/s.C51/'COSTS.json')[cls.symbol]
        cls.end=s.read(cls.root/'SPEC.json')['periods']['DEV2025']['runoff_end_ms']
    def path(self,t=None,e=None,trace=None):return s.check_path(t or self.t,e or self.e,trace or self.r['trace'],self.cost,self.end)
    def test_whole_scope(self):self.assertEqual(s.verify()['positions'],263)
    def test_first_trigger_cannot_be_erased(self):
        tr=deepcopy(self.r['trace']);row=next(z for z in tr if z['signal_index']==self.t['signal_index'] and z['kind']=='HELD_CLOSE_OBSERVATION' and z['exit_reason']==s.REASON);row['exit_reason']=None
        with self.assertRaisesRegex(ValueError,'FIRST_EXIT_REASON'):self.path(trace=tr)
    def test_omitted_held_bar_is_detected(self):
        tr=deepcopy(self.r['trace']);i=self.t['signal_index'];j=next(k for k,z in enumerate(tr) if z['signal_index']==i and z['kind']=='HELD_CLOSE_OBSERVATION');tr.pop(j)
        with self.assertRaisesRegex(ValueError,'HELD_GUARD_COVERAGE'):self.path(trace=tr)
    def test_false_net_guard_rejected(self):
        tr=deepcopy(self.r['trace']);row=next(z for z in tr if z['signal_index']==self.t['signal_index'] and z['kind']=='FAILED_BREAKOUT_OBSERVATION');row['net_mark_bps']+=1
        with self.assertRaises(ValueError):self.path(trace=tr)
    def test_native_priority(self):
        self.assertEqual(s.decision(90,95,1,1,True,100,-20),'FIXED_FLOOR_CLOSE')
        self.assertEqual(s.decision(99,90,0,1,True,100,-20),'MOMENTUM_NONPOSITIVE_CLOSE')
        self.assertEqual(s.decision(99,90,1,20,True,100,-20),'FIXED_TIME_CLOSE')
    def test_nonbreakout_not_retroactively_armed(self):self.assertIsNone(s.decision(99,90,1,1,False,100,-20))
    def test_upper_equality_and_net_equality(self):
        self.assertIsNone(s.decision(100,90,1,1,True,100,-20));self.assertEqual(s.decision(99,90,1,1,True,100,0),s.REASON)
    def test_exit_clock_change_rejected(self):
        t=deepcopy(self.t);t['exit_ts']+=s.BAR
        with self.assertRaisesRegex(ValueError,'NEXT_OPEN_CLOCK'):self.path(t=t)
    def test_fixed_range_cannot_trail(self):
        t=deepcopy(self.t);t['failed_breakout_upper']*=.99
        with self.assertRaisesRegex(ValueError,'FIXED_RANGE_CHANGED'):self.path(t=t)
    def test_fake_stop_not_allowed(self):
        t=deepcopy(self.t);t['exchange_resident_stop']=True
        with self.assertRaisesRegex(ValueError,'FAKE_RESIDENT_STOP'):self.path(t=t)
    def test_derived_pin_rejected(self):
        with self.assertRaisesRegex(ValueError,'DERIVED_PIN'):s.verify(derived_sha='0'*64)
    def test_completed_workflow_readonly(self):
        text=(self.root.parents[2]/'.github/workflows/c63-failed-breakout-exit-v1.yml').read_text()
        for bad in ('contents: write','git push','download-artifact','_study_v1','workflow_dispatch:','schedule:'):
            self.assertNotIn(bad,text)
if __name__=='__main__':unittest.main()

"""Actual saved evidence counterexamples, no alternative economic evaluation."""
from copy import deepcopy
import unittest
import verify_saved as s
class SavedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec=s.read(s.HERE/'SPEC.json');cls.cal=cls.spec['periods']['DEV2025'];cls.raw=s.gz(s.HERE/'DEV2025/RAW.json.gz');cls.res=s.gz(s.HERE/'DEV2025/RESULT.json.gz');cls.packet=s.gz(s.HERE.parents[2]/s.INPUTS/'DEV2025.json.gz')
        cls.sym=next(k for k,v in cls.raw.items() if v['trades'])
    def test_full_saved_scope(self):
        v=s.verify(partial=True);self.assertEqual(sum(x['positions'] for x in v['periods'].values()),112)
    def test_deleted_early_signal_detected(self):
        raw=deepcopy(self.raw);raw[self.sym]['events'].pop(0)
        with self.assertRaisesRegex(ValueError,'COMPLETE_SIGNAL_POOL'):s.check_core(raw,self.res,self.packet,self.cal)
    def test_future_preparation_not_accepted(self):
        raw=deepcopy(self.raw);e=raw[self.sym]['events'][0];e['entry_context']['available_at']=e['signal_ts']
        with self.assertRaises(ValueError):s.check_core(raw,self.res,self.packet,self.cal)
    def test_fake_ema_fill_detected(self):
        raw=deepcopy(self.raw);t=raw[self.sym]['trades'][0];t['entry_price']=t['entry_preparation']['level']
        with self.assertRaisesRegex(ValueError,'NEXT_ACTUAL_OPEN'):s.check_core(raw,self.res,self.packet,self.cal)
    def test_missing_wait_observation_detected(self):
        raw=deepcopy(self.raw);ls=raw[self.sym]['setup_events'];ls.pop(next(i for i,e in enumerate(ls) if e['kind']=='WAIT_PULLBACK'))
        with self.assertRaisesRegex(ValueError,'WAIT_FIRST_ACTION'):s.check_core(raw,self.res,self.packet,self.cal)
    def test_omitted_unsuccessful_squeeze_detected(self):
        raw=deepcopy(self.raw);ls=raw[self.sym]['setup_events'];ls.pop(next(i for i,e in enumerate(ls) if e['kind']=='SQUEEZE_OBSERVATION'))
        with self.assertRaisesRegex(ValueError,'ALL_SQUEEZE_OBSERVATIONS'):s.check_core(raw,self.res,self.packet,self.cal)
    def test_native_exit_reason_cannot_change(self):
        raw=deepcopy(self.raw);h=next(h for h in raw[self.sym]['trace'] if h['kind']=='HELD_CLOSE_OBSERVATION');h['exit_reason']='FIXED_TIME_CLOSE'
        with self.assertRaisesRegex(ValueError,'NATIVE_EXIT_REASON'):s.check_core(raw,self.res,self.packet,self.cal)
    def test_changed_pnl_detected(self):
        r=deepcopy(self.res);r['trades'][0]['net_bps']+=1
        with self.assertRaises(ValueError):s.check_metrics(r,self.packet,self.cal)
    def test_daily_mark_tampering_detected(self):
        r=deepcopy(self.res);r['metrics']['daily'][1]['cumulative_net_mark_bps']+=1
        with self.assertRaisesRegex(ValueError,'DAILY_SOURCE_VALUES'):s.check_metrics(r,self.packet,self.cal)
    def test_final_workflow_cannot_repeat_economics(self):
        wf=(s.HERE.parents[2]/'.github/workflows/c63-pre-release-entry-v1.yml').read_text()
        for forbidden in ('contents: write','git push','_study_v1','workflow_dispatch:','schedule:','finite-first:'):self.assertNotIn(forbidden,wf)
if __name__=='__main__':unittest.main()

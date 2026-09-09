"""Synthetic durable-claim guards. Never load market packets or run economics."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.research.rebuild import chart_mechanism_study_v1 as s


class RuntimeClaimTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.base=self.root/s.OUT;self.base.mkdir(parents=True)
        self.addCleanup(patch.stopall);patch.object(s,'ROOT',self.root).start()
        self.spec={'lane_status':{v:'READY' for v in s.VARIANTS}}
        patch.object(s,'verify_spec',return_value=self.spec).start()
        self.economic=patch.object(s.integration,'evaluate_one',side_effect=AssertionError('ECONOMIC_CALL_FORBIDDEN')).start()
        self.packet=patch.object(s,'gz',return_value={'synthetic':True}).start()
        patch.object(s.shared.old.inherited,'packet_check').start()
        s.put(self.base/'SPEC.json',{'fixture':'SYNTHETIC_ONLY'})
        self.budget={'cumulative_actual':57,'cumulative_actual_evaluations':94,'new_candidate_runs':0,
            'candidate_trials':[],'trials':[],s.KEY:dict(max_candidates=5,max_executions=10,reserved=0,
            started=0,completed=0,failed=0,remaining=10,retry=False)}
        s.put(self.base/'BUDGET.json',self.budget)
    def budget_now(self):return s.read(self.base/'BUDGET.json')
    def reserve(self):s.reserve('M1','DEV2025')
    def test_reserve_consumes_once_but_never_allocates_candidate(self):
        self.reserve();v=self.budget_now()
        self.assertEqual((v[s.KEY]['reserved'],v[s.KEY]['remaining']),(1,9))
        self.assertEqual((v['cumulative_actual'],v['cumulative_actual_evaluations']),(57,94))
        self.assertEqual(v['candidate_trials'],[]);self.packet.assert_not_called();self.economic.assert_not_called()
    def test_unresolved_claim_blocks_other_slot_without_more_consumption(self):
        self.reserve();before=self.budget_now()
        with self.assertRaisesRegex(Exception,'PREVIOUS_RUN_UNRESOLVED'):s.reserve('R1','DEV2025')
        self.assertEqual(self.budget_now(),before)
        self.assertFalse((self.base/'R1'/'DEV2025'/'ATTEMPT.json').exists())
    def test_completed_slot_still_cannot_retry(self):
        self.reserve();v=self.budget_now();v[s.KEY]['completed']=1;s.save_budget(v)
        with self.assertRaisesRegex(Exception,'NO_SLOT_RETRY'):self.reserve()
        self.assertEqual(self.budget_now(),v)
    def test_failed_consumed_slot_still_cannot_retry(self):
        self.reserve();v=self.budget_now();v[s.KEY]['failed']=1;s.save_budget(v)
        with self.assertRaisesRegex(Exception,'NO_SLOT_RETRY'):self.reserve()
        self.assertEqual(self.budget_now(),v)
    def test_source_blocked_lane_creates_no_claim(self):
        self.spec['lane_status']['M1']='NOT_RUN_SOURCE_UNAVAILABLE'
        with self.assertRaisesRegex(Exception,'LANE_SOURCE_BLOCKED'):self.reserve()
        self.assertEqual(self.budget_now(),self.budget)
        self.assertFalse((self.base/'M1'/'DEV2025'/'ATTEMPT.json').exists())
    def test_exhausted_allocation_cannot_reserve(self):
        self.budget[s.KEY].update(remaining=0,reserved=10,completed=10);s.save_budget(self.budget)
        with self.assertRaisesRegex(Exception,'PREVIOUS_RUN_UNRESOLVED'):self.reserve()
        self.assertFalse((self.base/'M1'/'DEV2025'/'ATTEMPT.json').exists())
    def test_absent_remote_proof_prevents_any_packet_read_or_economic_call(self):
        self.reserve()
        with self.assertRaises(FileNotFoundError):s.execute('M1','DEV2025',self.tmp.name,'a'*40)
        self.packet.assert_not_called();self.economic.assert_not_called()
        self.assertFalse((self.base/'M1'/'DEV2025'/'EXECUTION_STARTED.json').exists())
    def test_wrong_remote_proof_prevents_any_packet_read_or_economic_call(self):
        self.reserve();out=self.base/'M1'/'DEV2025'
        s.put(out/'REMOTE_READBACK.json',dict(commit='a'*40,attempt_sha256='wrong',budget_sha256=s.h(self.base/'BUDGET.json')))
        with self.assertRaisesRegex(Exception,'REMOTE_READBACK_BINDING'):s.execute('M1','DEV2025',self.tmp.name,'a'*40)
        self.packet.assert_not_called();self.economic.assert_not_called()
    def test_existing_started_marker_prevents_second_execution_and_budget_change(self):
        self.reserve();out=self.base/'M1'/'DEV2025';before=self.budget_now()
        s.put(out/'REMOTE_READBACK.json',dict(commit='a'*40,attempt_sha256=s.h(out/'ATTEMPT.json'),budget_sha256=s.h(self.base/'BUDGET.json')))
        s.put(out/'EXECUTION_STARTED.json',{'synthetic':'already-started'})
        with self.assertRaises(FileExistsError):s.execute('M1','DEV2025',self.tmp.name,'a'*40)
        self.economic.assert_not_called();self.assertEqual(self.budget_now(),before)
        self.assertEqual(s.read(out/'EXECUTION_STARTED.json'),{'synthetic':'already-started'})


if __name__=='__main__':unittest.main()

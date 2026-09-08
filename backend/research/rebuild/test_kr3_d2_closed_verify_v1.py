"""No-economic closure regressions on saved metadata and synthetic mutations."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from backend.research.rebuild import kr3_d2_closed_verify_v1 as v

class ClosedScopeTests(unittest.TestCase):
    def workflow(self):return (v.m.ROOT/'.github/workflows/kr3-d2-failure-v1.yml').read_text()
    def test_closed_scope_cannot_dispatch_or_write(self):
        text=self.workflow()
        for item in ('economic_once:', '--execute', 'contents: write', 'persist-credentials: true','workflow_dispatch:', 'git push','git fetch'):
            self.assertNotIn(item,text)
    def test_budget_only_changes_trigger_verification(self):
        text=self.workflow()
        self.assertEqual(text.count("- '"+v.m.p.BUDGET+"'"),2)
    def test_both_result_sets_are_required(self):
        text=self.workflow()
        for name in ('ATTEMPT.json','EXECUTION_STARTED.json','RECEIPT.json','RESULT.json.gz'):
            self.assertIn(name,text)
        self.assertIn('kr3_d2_closed_verify_v1',text)
    def test_consumed_allocation_cannot_be_reset(self):
        spec=v.read(v.m.ROOT/v.m.OUT/'SPEC.json');budget=v.read(v.m.ROOT/v.m.p.BUDGET)
        v.validate_budget(budget,spec)
        wrong=deepcopy(budget);wrong[v.m.KEY]['used']=0
        with self.assertRaisesRegex(ValueError,'ALLOCATION_2_OF_2'):v.validate_budget(wrong,spec)
    def test_wrong_ordinal_binding_rejected(self):
        spec=v.read(v.m.ROOT/v.m.OUT/'SPEC.json');budget=v.read(v.m.ROOT/v.m.p.BUDGET)
        trial=next(t for t in budget['trials'] if t['actual_experiment_ordinal']==67)
        trial['period']='SEEN2026'
        with self.assertRaisesRegex(ValueError,'EXACT_COMPLETED_TRIAL'):v.validate_budget(budget,spec)
    def test_changed_or_missing_summary_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in v.FILES:(root/name).write_bytes(b'fixture')
            files={name:v.hashlib.sha256(b'fixture').hexdigest() for name in v.FILES}
            (root/'SUMMARY_BINDING.json').write_text(json.dumps({'files_sha256':files}))
            v.verify_bound_files(root)
            (root/'REPORT.md').write_bytes(b'false positive result')
            with self.assertRaisesRegex(ValueError,'SUMMARY_BYTES_DRIFT:REPORT'):v.verify_bound_files(root)

if __name__=='__main__':unittest.main()

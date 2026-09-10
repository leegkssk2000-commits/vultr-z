"""Saved comparator provenance and future CI lifetime regressions, no replay."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import os,json,hashlib,unittest
import verify_corrected as c
class CorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs=Path(os.environ['PRICE_INPUTS']);cls.meta=c.v.read(c.HERE/'LOCAL_C70_IMPORT.json')
        cls.events=c.v.gz(c.HERE/'C70_LOCAL_EVENT_DECISIONS.json.gz');cls.original=c.v.read(c.HERE/'SUMMARY.json')
        cls.packet=c.v.gz(cls.inputs/'DEV2025.json.gz')
        cls.parent=c.v.gz(c.v.ROOT/'research/development_evidence/M1_ER_RANGE_RESCUE_AFTER_PR1232_V1/DEV2025/RESULT.json.gz')
    def check_events(self,events):return c.verify_decisions('DEV2025',events,self.packet,self.parent,self.meta)
    def reseal_projection(self,events):
        p=events['periods']['DEV2025'];p['projection_sha256']=hashlib.sha256(c.canon(p['rows'])).hexdigest()
    def test_complete_actual_event_reconstruction(self):self.assertEqual(c.verify(self.inputs)['events_checked'],142)
    def test_copied_C63_reasons_are_detected(self):
        x=deepcopy(self.events);lookup={c.v.key(e):e for e in self.parent['events']}
        for row in x['periods']['DEV2025']['rows']:row[5]=lookup[tuple(row[:3])]['exclusion_reason']
        self.reseal_projection(x)
        with self.assertRaisesRegex(AssertionError,'IMPORTED_EXCLUSION_REASON'):self.check_events(x)
    def test_omitted_original_signal_rejected(self):
        x=deepcopy(self.events);x['periods']['DEV2025']['rows'].pop();self.reseal_projection(x)
        with self.assertRaisesRegex(AssertionError,'EVENT_POOL'):self.check_events(x)
    def test_fake_admission_rejected(self):
        x=deepcopy(self.events);x['periods']['DEV2025']['rows'][0][3]=True;self.reseal_projection(x)
        with self.assertRaisesRegex(AssertionError,'IMPORTED_ADMISSION'):self.check_events(x)
    def test_source_hash_mismatch_rejected(self):
        x=deepcopy(self.events);x['periods']['DEV2025']['source_result_sha256']='0'*64
        with self.assertRaisesRegex(AssertionError,'ORIGINAL_RESULT_ID'):self.check_events(x)
    def test_all_non_event_fields_are_exactly_preserved(self):
        fixed=c.corrected_summary(self.original,self.events,self.meta)
        for per in c.PERIODS:
            for label,old in self.original['periods'][per]['snapshots'].items():
                new=fixed['periods'][per]['snapshots'][label]
                for k,value in old.items():
                    if label!='C70_LOCAL' or k not in c.EVENT_FIELDS:self.assertEqual(value,new[k])
            self.assertEqual(self.original['periods'][per]['checks'],fixed['periods'][per]['checks'])
        self.assertEqual(fixed['status'],'REJECT_KEEP_C63')
    def test_frozen_summary_and_manifest_not_rewritten(self):
        self.assertEqual(c.v.sha(c.HERE/'SUMMARY.json'),c.SUMMARY_SHA)
        for name,digest in c.v.read(c.HERE/'EVIDENCE_HASHES.json').items():self.assertEqual(c.v.sha(c.HERE/name),digest)
    def test_financial_edit_in_correction_rejected(self):
        read=c.v.read;data=deepcopy(read(c.HERE/'SUMMARY_CORRECTION.json'));data['changes']['DEV2025']['terminal_net_bps']={'after':1}
        with patch.object(c.v,'read',side_effect=lambda path:data if str(path).endswith('/SUMMARY_CORRECTION.json') else read(path)):
            with self.assertRaisesRegex(AssertionError,'FINANCIAL_DRIFT'):c.load_corrected_summary()
    def test_durable_inputs_and_no_dispatch(self):
        wf=(c.v.ROOT/'.github/workflows/c70-price-confirmation-v1.yml').read_text()
        self.assertIn('TOP5_SOURCE_CHART_MECHANISMS_AFTER_PR1228_V1/INPUTS',wf)
        self.assertIn('verify_corrected.py',wf)
        for s in ('download-artifact','34282003231','contents: write','workflow_dispatch','_study_v1','git push'):self.assertNotIn(s,wf)
    def test_unsupported_setup_metadata_not_invented(self):
        fixed=c.corrected_summary(self.original,self.events,self.meta)
        for per in c.PERIODS:self.assertNotIn('waiting_setup_no_candidate',fixed['periods'][per]['snapshots']['C70_LOCAL'])
if __name__=='__main__':unittest.main()

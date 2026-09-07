"""Stored DEV arithmetic and adversarial fixtures; no market replay."""
import gzip
import json
import unittest
from backend.research.rebuild import kr3_evidence_adapter_v1 as a


class KR3EvidenceAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = a.read_inputs()
        cls.valid = a.dry_run(cls.inputs)

    def test_stored_dev_and_existing_producer_are_bound(self):
        result = self.valid
        self.assertEqual(result['binding']['status'], 'VALID_DEV_BINDING', result['binding']['errors'])
        self.assertEqual(result['binding']['values']['closed_T'], 202)
        self.assertEqual(result['binding']['values']['open_T'], 1)
        self.assertTrue(any(c['check']=='existing_retention_producer_exact' and c['pass'] for c in result['binding']['checks']))
        self.assertFalse(result['formal_admission'])
        self.assertFalse(result['production_grade'])
        self.assertFalse(result['boundary_created'])
        self.assertFalse(result['binding']['raw_source_bytes_verified'])
        self.assertFalse(result['P0_P6_preflight']['p0_p6_passed'])
        self.assertEqual(result['P0_P6_preflight']['gates'][0]['passed'], True)

    def test_missing_and_invalid_bytes_fail_closed(self):
        missing = dict(self.inputs);missing.pop(a.ARTIFACT)
        self.assertEqual(a.dry_run(missing)['binding']['status'], 'MISSING')
        invalid = dict(self.inputs);invalid[a.ARTIFACT] = b'not-gzip'
        self.assertEqual(a.dry_run(invalid)['binding']['status'], 'INVALID')
        invalid_draft = dict(self.inputs);invalid_draft[a.DRAFT] = b'{'
        self.assertEqual(a.dry_run(invalid_draft)['binding']['status'], 'INVALID')

    def test_corrupted_code_hash_is_rejected(self):
        fixture = dict(self.inputs)
        fixture[a.REBUILD+'keltner_kr3_v1.py'] += b'\n# changed\n'
        result = a.verify_binding(fixture)
        self.assertIn('file:'+a.REBUILD+'keltner_kr3_v1.py', result['errors'])

    def changed_artifact(self, change):
        fixture = dict(self.inputs)
        artifact = json.loads(gzip.decompress(fixture[a.ARTIFACT]));change(artifact)
        fixture[a.ARTIFACT] = gzip.compress(json.dumps(artifact).encode(), mtime=0)
        return fixture

    def test_resealed_row_still_requires_economic_arithmetic(self):
        def change(doc):
            row=doc['views']['FULL']['trades'][0]
            row['cost2x_net_bps'] += 1
            row['trade_sha256']=a.sha({k:v for k,v in row.items() if k!='trade_sha256'})
        result=a.verify_binding(self.changed_artifact(change))
        self.assertIn('cost2_identity:0', result['errors'])
        self.assertIn('artifact_bytes', result['errors'])

    def test_production_label_and_wrong_candidate_rejected(self):
        def change(doc):
            doc['views']['FULL']['trades'][0]['production_grade']=True
            doc['candidate']='KR4'
        result=a.verify_binding(self.changed_artifact(change))
        self.assertIn('row_DEV_only:0',result['errors'])
        self.assertIn('candidate_FULL_identity',result['errors'])

    def test_each_formal_report_remains_incomplete(self):
        self.assertEqual(len(self.valid['reports']),9)
        for name, report in self.valid['reports'].items():
            self.assertFalse(report['complete'],name)
            self.assertFalse(report['formal_eligible'],name)
            self.assertIn('required_units',report)
            self.assertIn('consumer',report)
        self.assertIsNone(self.valid['reports']['negative_controls']['producer'])

    def test_sixteen_prior_items_preserved_one_to_one(self):
        draft=json.loads(self.inputs[a.DRAFT])
        transitions=self.valid['unresolved_transitions']
        self.assertEqual(set(transitions),set(draft['unresolved']))
        self.assertEqual(len(transitions),16)
        for key,row in transitions.items():
            self.assertEqual(row['previous'],draft['unresolved'][key])
            self.assertFalse(row['formal_satisfied'])
        self.assertEqual(self.valid['transition_counts']['ACTUAL_RESOLVED_BINDING'],1)
        self.assertFalse(self.valid['approval_bundle']['items']['initial_risk_R_denominator']['approved'])
        self.assertEqual(self.valid['market_replays'],0)


if __name__=='__main__':
    unittest.main()

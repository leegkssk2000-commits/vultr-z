"""No historical replay: reject evidence drift and false gate upgrades."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from backend.research.rebuild import step7_kr3_g5a_evidence_v1 as e


def seal(value):
    value['receipt_sha256'] = e.alpha.sha({k:v for k,v in value.items() if k!='receipt_sha256'})
    return value


class EvidenceBindingTests(unittest.TestCase):
    def test_other_dataset_history_receipt_does_not_certify_dev_slice(self):
        authority = {'immutable_history_verified': True, 'dataset_sha256': 'full'}
        self.assertFalse(e.exact_history_verified(authority, 'dev_slice'))
        self.assertTrue(e.exact_history_verified(authority, 'full'))
        self.assertFalse(e.exact_history_verified({}, 'full'))

    def test_wrong_candidate_rejected_before_files(self):
        m=seal({'candidate_sha256':'wrong','files_sha256':{}})
        with self.assertRaisesRegex(ValueError,'CANDIDATE_IDENTITY'):
            e.read_inputs(Path('/no-such-evidence'),m)

    def test_nonwhitelisted_data_rejected_before_read(self):
        m=seal({'candidate_sha256':e.CANDIDATE,'files_sha256':{'not-authorized': 'a'}})
        with self.assertRaisesRegex(ValueError,'INPUT_WHITELIST'):
            e.read_inputs(Path('/no-such-evidence'),m)

    def test_stale_pinned_bytes_rejected_without_economic_read(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); path=root/e.FILES[0];path.parent.mkdir(parents=True)
            path.write_text('{}')
            m=seal({'candidate_sha256':e.CANDIDATE,'files_sha256':{p:'0'*64 for p in e.FILES}})
            with self.assertRaisesRegex(ValueError,'BYTES_CHANGED'):
                e.read_inputs(root,m)

    def test_receipt_missing_or_tampered_not_self_asserted_proof(self):
        with self.assertRaisesRegex(ValueError,'RECEIPT_HASH'):
            e.sealed({'passed':True})
        value=seal({'passed':False});value['passed']=True
        with self.assertRaisesRegex(ValueError,'RECEIPT_HASH'):
            e.sealed(value)

    def test_entry_features_do_not_claim_held_state_is_entry_observable(self):
        fmap=e.feature_map({p:'source' for p in e.NATIVE})
        self.assertTrue(e.alpha.evaluate_p1({'feature_causal_map':fmap})['passed'])
        self.assertEqual({f['name'] for f in fmap['features']},{'trend_order','reclaim','directional_half'})
        self.assertIn('KR3_veto',{f['name'] for f in fmap['execution_state_not_mislabelled_entry_feature']})

    def test_regime_nonapplicability_does_not_pass_other_controls(self):
        fmap=e.feature_map({p:'source' for p in e.NATIVE})
        rows=[{'kind':k,'applicable':True,'passed':False} for k in ('direction_flip','time_shift_placebo','delayed_entry')]
        rows.append({'kind':'regime_permutation','applicable':False,'passed':False,
                     'not_applicable_reason':fmap['regime_feature_absent_proof']['reason']})
        gate=e.alpha.evaluate_p4({'feature_causal_map':fmap,'negative_controls_and_ablation':{
            'controls':rows,'feature_ablations':[],'holdout_outcomes_used':False}})
        codes=[x['code'] for x in gate['failures']]
        self.assertFalse(gate['passed'])
        self.assertEqual(codes.count('P4_CONTROL_FAIL'),3)
        self.assertIn('P4_FEATURE_ABLATION_MISSING',codes)
        self.assertNotIn('P4_NOT_APPLICABLE_UNJUSTIFIED',codes)

    def test_native_code_hash_is_not_prior_empirical_justification(self):
        pins={p:'code' for p in e.FILES}
        inv=e.inventory(pins,{'goals':{}})
        gate=e.alpha.evaluate_p2({'parameter_provenance':inv})
        self.assertFalse(gate['passed'])
        self.assertIn('P2_INVENTORY_INCOMPLETE',{f['code'] for f in gate['failures']})
        self.assertIn('P2_PURE_DESIGN_PRIOR_UNJUSTIFIED',{f['code'] for f in gate['failures']})


if __name__=='__main__':
    unittest.main()

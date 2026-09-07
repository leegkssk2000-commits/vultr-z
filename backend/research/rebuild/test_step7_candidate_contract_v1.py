"""New synthetic contract boundaries only; no old ledger audit or market replay."""
from copy import deepcopy
import json
import unittest
from backend.research.rebuild import step7_candidate_contract_v1 as c


class Step7ContractTests(unittest.TestCase):
    def candidate(self, profile='KR3'):
        path = c.PROFILES[profile]['implementation']
        return c.candidate_contract(profile, candidate_id=c.PROFILES[profile]['candidate_id'] or 'FROZEN_Q0_FIXTURE',
            direct_parent_id='EXACT_PARENT_FIXTURE', code_blobs={path:b'def entry():\n    return 1\ndef exit():\n    return 2\n'},
            config_blob=b'{}', mechanism_blob=b'exact fixture rule',
            entry_owner={'path':path,'function':'entry'}, exit_owner={'path':path,'function':'exit'})

    def contract(self):
        candidate = self.candidate()
        identity = {'candidate_sha256':candidate['candidate_sha256'], 'data_sha':'a'*64, 'cost_sha':'b'*64}
        specs = {name:{'producer':{'path':'fixture.py','function':'produce'}, 'command':['python','fixture.py',name],
                'evaluation_spec_sha256':'c'*64, 'input_identity':identity} for name in c.REPORTS}
        return c.producer_contract(candidate, data_sha='a'*64, cost_sha='b'*64,
            preregistration_sha='d'*64, report_specs=specs,
            producer_blobs={'fixture.py':b'def produce():\n    return None\n'})

    def execution(self, contract, name='base_replay'):
        spec = contract['reports'][name]
        artifact = {'report':name, 'input_identity':spec['input_identity'],
                    'payload':{key:[] for key in c.PAYLOAD_FIELDS[name]}}
        raw = json.dumps(artifact).encode()
        value = {'status':'COMPLETED','exit_code':0, 'evidence_class':'INDEPENDENT_ECONOMIC_EXECUTION',
                 'contract_sha256':contract['receipt_sha256'], **spec['input_identity'],
                 'report':name, 'command':spec['command'], 'producer_pin':spec['producer_pin'],
                 'evaluation_spec_sha256':spec['evaluation_spec_sha256'], 'preregistration_sha':contract['preregistration_sha'],
                 'source_execution_receipt_sha256':'e'*64, 'artifact_path':name+'.json', 'artifact_sha256':c.byte_sha(raw)}
        return c.seal(value), {name+'.json':raw}

    def test_candidate_changes_bind_full_code_and_never_invent_sl(self):
        candidate = self.candidate()
        self.assertIsNone(candidate['native']['initial_protective_sl'])
        self.assertEqual(candidate['candidate_sha256'], c.sha({k:v for k,v in candidate.items() if k!='candidate_sha256'}))
        changed = deepcopy(candidate); changed['config_sha']='f'*64
        with self.assertRaisesRegex(ValueError, 'CANDIDATE_SEAL_INVALID'):
            c.producer_contract(changed, data_sha='a'*64, cost_sha='b'*64, preregistration_sha='d'*64, report_specs={}, producer_blobs={})

    def test_q0_has_no_cap_and_time_only_cannot_be_connected(self):
        candidate=self.candidate('Q0')
        self.assertIsNone(candidate['native']['native_cap_signal_index_offset'])
        with self.assertRaisesRegex(ValueError, 'CONDITIONAL_NATIVE_EXIT_REQUIRED'):
            c.require_compatible(candidate, {'exit_model':'TIME_STOP_ONLY'})
        bridge={'exit_model':'CONDITIONAL','native_profile_sha256':c.sha(candidate['native']),
                'holding_limit':None,'intrabar_timestamp_is_exact_fill':False}
        self.assertTrue(c.require_compatible(candidate,bridge))
        bridge['holding_limit']=96
        with self.assertRaisesRegex(ValueError, 'Q0_UNLIMITED_HOLD'):
            c.require_compatible(candidate,bridge)

    def test_missing_execution_stays_incomplete(self):
        result=c.bind_economic_reports(self.contract(), {}, {})
        self.assertEqual(len(result['missing']),9)
        self.assertFalse(result['formal_admission'])

    def test_receipt_string_is_not_an_economic_report(self):
        contract=self.contract(); receipt,blobs=self.execution(contract)
        blobs['base_replay.json']=b'"PASS"'
        receipt['artifact_sha256']=c.byte_sha(blobs['base_replay.json'])
        receipt=c.seal({k:v for k,v in receipt.items() if k!='receipt_sha256'})
        with self.assertRaisesRegex(ValueError, 'ECONOMIC_PAYLOAD_REQUIRED'):
            c.bind_economic_reports(contract,{'base_replay':receipt},blobs)

    def test_receipt_cost_substitution_rejected_even_when_resealed(self):
        contract=self.contract(); receipt,blobs=self.execution(contract)
        receipt['cost_sha']='f'*64; receipt=c.seal({k:v for k,v in receipt.items() if k!='receipt_sha256'})
        with self.assertRaisesRegex(ValueError, 'EXECUTION_BINDING_MISMATCH:base_replay:cost_sha'):
            c.bind_economic_reports(contract,{'base_replay':receipt},blobs)

    def test_actual_bytes_are_required(self):
        contract=self.contract(); receipt,blobs=self.execution(contract)
        blobs['base_replay.json'] += b' '
        with self.assertRaisesRegex(ValueError,'ARTIFACT_BYTES_MISMATCH'):
            c.bind_economic_reports(contract,{'base_replay':receipt},blobs)

    def test_all_report_bindings_still_are_not_formal_pass(self):
        contract=self.contract(); receipts={}; blobs={}
        for name in c.REPORTS:
            receipt,artifact=self.execution(contract,name); receipts[name]=receipt;blobs.update(artifact)
        result=c.bind_economic_reports(contract,receipts,blobs)
        self.assertEqual(result['status'],'ALL_REPORT_BYTES_BOUND_NOT_ECONOMIC_PASS')
        self.assertFalse(result['formal_admission'])
        self.assertFalse(result['source_authenticity_certified'])

    def test_synthetic_evidence_cannot_claim_actual_execution(self):
        contract=self.contract(); receipt,blobs=self.execution(contract)
        receipt['evidence_class']='SYNTHETIC_TEST'; receipt=c.seal({k:v for k,v in receipt.items() if k!='receipt_sha256'})
        with self.assertRaisesRegex(ValueError,'FORMAL_REPORT_CLASS_REQUIRED'):
            c.bind_economic_reports(contract,{'base_replay':receipt},blobs)


if __name__ == '__main__':
    unittest.main()

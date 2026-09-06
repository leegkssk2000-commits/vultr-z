"""No-candidate authority, parent preservation and immutable diagnostic I/O."""
from copy import deepcopy
import gzip
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.research.rebuild import break_channel_q2_diagnosis_v1 as x


def originals():
    q0=x.old.seal({'budget':{'cumulative_after':24},'comparisons':{'P_to_Q':{'decision':{'decision':'DEV_INCONCLUSIVE'},'uncertainty':{}}},
                  'metrics':{'P':{},'Q':{}},'diagnostics':{'P':{},'Q':{}},'marked_diagnostics':{'P':{},'Q':{}},'artifacts':{}})
    q1=x.old.seal({'budget':{'cumulative_after':25},'decision':{'decision':'DEV_REJECT','research_reference':'Q0'},'data_reuse_history':[]})
    durable=x.old.seal({'result_receipt_sha256':q1['receipt_sha256'],'files_sha256':{},'code_files_sha256':{},'preserved_files_sha256':{}})
    return q0,q1,durable


class AuthorityTests(unittest.TestCase):
    def test_parent_status_count_and_bytes_are_verified_before_loading(self):
        for case in ('Q0_count','Q1_count','Q0_status','Q1_status','Q1_reference','changed_bytes'):
            q0,q1,d=originals()
            if case=='Q0_count':q0['budget']['cumulative_after']=23
            elif case=='Q1_count':q1['budget']['cumulative_after']=26
            elif case=='Q0_status':q0['comparisons']['P_to_Q']['decision']['decision']='PASS'
            elif case=='Q1_status':q1['decision']['decision']='PASS'
            elif case=='Q1_reference':q1['decision']['research_reference']='Q1'
            q0=x.old.seal({k:v for k,v in q0.items() if k!='receipt_sha256'})
            q1=x.old.seal({k:v for k,v in q1.items() if k!='receipt_sha256'})
            d=x.old.seal({**{k:v for k,v in d.items() if k!='receipt_sha256'},'result_receipt_sha256':q1['receipt_sha256']})
            values={x.prior.OUTPUT+'/receipt.json':q0,x.previous.OUTPUT+'/receipt.json':q1,x.previous.OUTPUT+'/durable_receipt.json':d,x.prior.CONTRACT:{}}
            with self.subTest(case=case),patch.object(x.prior,'authorize'),patch.object(x.previous,'authorize'),patch.object(x,'read',side_effect=lambda p:values[p]),patch.object(x,'Q0_SEAL',q0['receipt_sha256']),patch.object(x,'Q1_SEAL',q1['receipt_sha256']),patch.object(x.old,'file_sha',return_value='changed'),patch.object(x.prior.inputs,'load_inputs') as loader:
                with self.assertRaises(RuntimeError):x.run(Path('NEVER_LOAD'))
                loader.assert_not_called()

    def test_parent_receipt_reseal_does_not_replace_frozen_identity(self):
        q0,q1,d=originals();values={x.prior.OUTPUT+'/receipt.json':q0,x.previous.OUTPUT+'/receipt.json':q1}
        with patch.object(x.prior,'authorize'),patch.object(x.previous,'authorize'),patch.object(x,'read',side_effect=lambda p:values[p]):
            with self.assertRaisesRegex(RuntimeError,'PARENT_IDENTITY'):x.authorize()

    def test_data_or_universe_drift_blocks_all_diagnosis(self):
        q0,q1,_=originals();spec={'data_sha256':'data','cost_sha256':'cost','symbols':['S']}
        for policy,four in [({'combined_data_sha256':'wrong','cost_binding_sha256':'cost'},{'S':[]}),({'combined_data_sha256':'data','cost_binding_sha256':'wrong'},{'S':[]}),({'combined_data_sha256':'data','cost_binding_sha256':'cost'},{'OTHER':[]})]:
            with patch.object(x,'authorize',return_value=(q0,q1,spec,{})),patch.object(x.prior.inputs,'load_inputs',return_value=(policy,{},four,{},{})),patch.object(x.observability,'build') as obs,patch.object(x.losses,'build') as loss:
                with self.assertRaises(RuntimeError):x.run(Path('UNUSED'))
                obs.assert_not_called();loss.assert_not_called()


class DiagnosticBoundaryTests(unittest.TestCase):
    def test_not_run_does_not_become_reject_or_consume_a_trial(self):
        d=x.decision()
        self.assertEqual(d['economic_decision'],'NOT_RUN');self.assertIsNone(d['Q2_rule'])
        self.assertFalse(d['formal_pass']);self.assertFalse(d['candidate_implementation_allowed_by_this_report'])
        self.assertEqual(x.BUDGET['cumulative_after'],25);self.assertEqual(x.BUDGET['new_trials_consumed'],0)
        self.assertEqual(x.BUDGET['conditional_allocation_unconsumed'],1)
        self.assertFalse(x.BUDGET['Q3_authorized'])

    def test_pipeline_reproduction_never_calls_candidate_execution(self):
        q0,q1,_=originals()
        spec={'data_sha256':'data','cost_sha256':'cost','symbols':['S'],'evaluation_interval_ms':[0,3*x.prior.DAY]}
        policy={'combined_data_sha256':'data','cost_binding_sha256':'cost'}
        obs={'counts':'synthetic diagnostic only'};loss={'runs':'synthetic diagnostic only'}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/x.OUTPUT;out.mkdir(parents=True)
            (root/x.SOURCE).write_text('SOURCE FACTS ONLY')
            oldout=root/x.prior.OUTPUT;oldout.mkdir(parents=True)
            for name in ('trades','open_observations','events','daily_bars','daily_valuation'):
                p=oldout/(name+'.jsonl.gz');p.write_bytes(gzip.compress(b'',mtime=0))
                q0['artifacts'][name]={'path':str(p.relative_to(root)),'file_sha256':x.old.file_sha(p)}
            before_old={p.name:p.read_bytes() for p in oldout.iterdir()}
            with patch.object(x,'ROOT',root),patch.object(x,'CODE',[]),patch.object(x,'authorize',return_value=(q0,q1,spec,{})),patch.object(x.prior.inputs,'load_inputs',return_value=(policy,{'cost_by_symbol':{}},{'S':[]},{},{})),patch.object(x.observability,'build',return_value=obs),patch.object(x.losses,'build',return_value=loss),patch.object(x,'report',return_value=b'SYNTHETIC NOT_RUN'),patch.object(x.prior.structure,'replay') as replay,patch.object(x.previous.execution,'replay') as q1_replay:
                result=x.run(root/'INPUT');before={p.name:p.read_bytes() for p in out.iterdir()}
                repeated=x.run(root/'INPUT',verify_only=True)
                self.assertEqual(result,repeated);self.assertEqual(before,{p.name:p.read_bytes() for p in out.iterdir()})
                self.assertEqual(before_old,{p.name:p.read_bytes() for p in oldout.iterdir()})
                replay.assert_not_called();q1_replay.assert_not_called()
                self.assertIsNone(result['candidate_economics']);self.assertIsNone(result['candidate_uncertainty'])
                for k,v in x.old.probe.DEV_AUTH.items():self.assertEqual(result[k],v)
                loss['runs']='changed diagnostic'
                with self.assertRaisesRegex(RuntimeError,'REPRODUCTION_DRIFT'):x.run(root/'INPUT',verify_only=True)


if __name__=='__main__':unittest.main()

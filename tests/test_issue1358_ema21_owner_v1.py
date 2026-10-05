"""No real prices, network, production owner or actual economic callbacks."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import base64
import hashlib
import tempfile
import threading
import unittest
from unittest.mock import patch
from ops import issue1358_ema21_owner_v1 as g
from ops import issue1358_ema21_limit_v1 as m
from ops.kp_committed_cursor_snapshot_v1 import SnapshotError

ENV = {'GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':g.REPO,'GITHUB_EVENT_NAME':'push',
       'GITHUB_REF':'refs/heads/'+g.BRANCH,'GITHUB_RUN_ATTEMPT':'1','GITHUB_JOB':g.JOB,
       'GITHUB_RUN_ID':'123','GITHUB_SHA':'a'*40}
C = {'batch_id':m.BATCH,'claim_ref':g.CLAIM_REF,'execution_owner':'GITHUB_ATOMIC_REF_V1'}
A = {'batch_id':m.BATCH,'contract_sha256':'b'*64,'reviewed_parent_sha':'c'*40}

class FakeAPI:
    def __init__(self):
        self.lock=threading.Lock();self.claim=None;self.calls=[];self.diff_path=g.CAMPAIGN+'/RUN_GITHUB.json';self.approved_parent='c'*40;self.approved_contract='b'*64
        self.approval_available=True;self.other_active=[]
    def __call__(self,method,route,value=None):
        with self.lock:
            self.calls.append((method,route,value))
            if route.startswith('/actions/runs?'):
                return {'total_count':len(self.other_active),'workflow_runs':self.other_active}
            if route.startswith('/actions/runs/'):
                return {'head_sha':'a'*40,'head_branch':g.BRANCH,'event':'push','run_attempt':1,
                        'status':'in_progress','path':'.github/workflows/issue1358-ema21-limit-v1.yml'}
            if route=='/git/ref/'+g.APPROVAL_REF:
                if not self.approval_available:raise RuntimeError('GITHUB_GET_HTTP_404')
                return {'ref':'refs/'+g.APPROVAL_REF,'object':{'type':'commit','sha':'9'*40}}
            if route=='/git/commits/'+'9'*40:
                return {'parents':[{'sha':'c'*40}],'tree':{'sha':'8'*40}}
            if route=='/git/trees/'+'8'*40:
                paths=['ops/issue1358_ema21_owner_v1.py','ops/issue1358_ema21_limit_v1.py',
                       '.github/workflows/issue1358-ema21-limit-v1.yml',
                       g.CAMPAIGN+'/CONTRACT_GITHUB.json']
                raw=g.encoded({'batch_id':m.BATCH,'approved_parent_sha':self.approved_parent,
                               'contract_sha256':self.approved_contract,'max_lane_executions':1,
                               'source_sha256':{p:g.sha((g.ROOT/p).read_bytes()) for p in paths}})
                self.approval_raw=raw;self.approval_blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
                return {'tree':[{'path':'APPROVED.json','type':'blob','sha':self.approval_blob}]}
            if route.startswith('/git/blobs/'):
                return {'encoding':'base64','content':base64.b64encode(self.approval_raw).decode()}
            if route.startswith('/git/commits/'):
                return {'parents':[{'sha':'c'*40}]}
            if route.startswith('/compare/'):
                return {'total_commits':1,'files':[{'filename':self.diff_path,'status':'added'}]}
            if route in ('/git/blobs','/git/trees','/git/commits'):
                return {'sha':'d'*40}
            if route=='/git/refs':
                if self.claim is not None:raise RuntimeError('GITHUB_POST_HTTP_422')
                self.claim=value.copy();return {'ref':value['ref'],'object':{'sha':value['sha']}}
            raise AssertionError((method,route))

class GitHubOwnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.api=FakeAPI();self.n=0;self.lock=threading.Lock()
    def tearDown(self):self.tmp.cleanup()
    def fake_run(self,data,contract,out):
        with self.lock:self.n+=1
        result={'synthetic':True};g.write_once(out,'SUMMARY.json',result);return result
    def run_it(self,name='out',**kwargs):
        return g.execute({},C,A,self.root/name,api=self.api,env=ENV,run=kwargs.get('run',self.fake_run))
    def test_other_active_run_blocks_without_budget_consumption(self):
        self.api.other_active=[{'id':456}]
        with self.assertRaisesRegex(SnapshotError,'OTHER_ACTIVE_RUN_HOLD'):self.run_it()
        self.assertIsNone(self.api.claim);self.assertEqual(self.n,0)
    def test_clearance_wait_does_not_claim_until_other_ci_completes(self):
        self.api.other_active=[{'id':456}]
        def finish_saved_ci(delay):
            self.assertIsNone(self.api.claim);self.assertEqual(self.n,0)
            self.api.other_active=[]
        with patch.object(g.time,'sleep',side_effect=finish_saved_ci):
            g.execute({}, {**C,'preclaim_clearance_wait_seconds':1}, A,self.root/'out',self.api,ENV,self.fake_run)
        self.assertEqual(self.n,1);self.assertIsNotNone(self.api.claim)
    def test_normal_one_execution(self):
        self.run_it();self.assertEqual(self.n,1);self.assertTrue(self.api.claim)
        self.assertTrue((self.root/'out/COMPLETED.json').exists())
    def test_existing_output_claim_not_consumed(self):
        (self.root/'out').mkdir()
        with self.assertRaises(FileExistsError):self.run_it()
        self.assertIsNone(self.api.claim);self.assertEqual(self.n,0);self.assertEqual(self.api.calls,[])
    def test_unwritable_prepare_claim_not_consumed(self):
        with patch.object(Path,'open',side_effect=PermissionError('cannot write')):
            with self.assertRaises(PermissionError):self.run_it()
        self.assertEqual(self.api.calls,[]);self.assertEqual(self.n,0)
    def test_concurrent_outputs_one_winner(self):
        barrier=threading.Barrier(8)
        def attempt(i):
            barrier.wait()
            try:self.run_it('out'+str(i));return 1
            except RuntimeError:return 0
        with ThreadPoolExecutor(max_workers=8) as pool:self.assertEqual(sum(pool.map(attempt,range(8))),1)
        self.assertEqual(self.n,1)
    def test_changed_contract_or_output_cannot_replenish(self):
        self.run_it();altered={**A,'contract_sha256':'e'*64}
        with self.assertRaises(SnapshotError):g.execute({},C,altered,self.root/'other',self.api,ENV,self.fake_run)
        self.assertEqual(self.n,1)
    def test_retry_attempt_rejected_before_claim(self):
        with self.assertRaisesRegex(SnapshotError,'NO_RETRY'):
            g.execute({},C,A,self.root/'out',self.api,{**ENV,'GITHUB_RUN_ATTEMPT':'2'},self.fake_run)
        self.assertIsNone(self.api.claim)
    def test_pr_job_cannot_execute(self):
        with self.assertRaisesRegex(SnapshotError,'BRANCH_PUSH'):
            g.execute({},C,A,self.root/'out',self.api,{**ENV,'GITHUB_EVENT_NAME':'pull_request'},self.fake_run)
        self.assertIsNone(self.api.claim)
    def test_unapproved_repository_rejected(self):
        with self.assertRaisesRegex(SnapshotError,'GITHUB_OWNER'):
            g.execution_identity({**ENV,'GITHUB_REPOSITORY':'someone/other'},self.api)
        self.assertEqual(self.api.calls,[])
    def test_api_source_mismatch_rejected(self):
        def api(*args):return {**self.api(*args),'head_sha':'f'*40}
        with self.assertRaisesRegex(SnapshotError,'API_RUN_IDENTITY'):g.execution_identity(ENV,api)
    def test_changed_activation_parent_rejected(self):
        with self.assertRaisesRegex(SnapshotError,'PARENT_CHANGED'):
            g.execute({},C,{**A,'reviewed_parent_sha':'f'*40},self.root/'out',self.api,ENV,self.fake_run)
        self.assertIsNone(self.api.claim)
    def test_nonactivation_diff_rejected(self):
        self.api.diff_path='ops/other.py'
        with self.assertRaisesRegex(SnapshotError,'ONE_NEW_FILE'):self.run_it()
        self.assertIsNone(self.api.claim)
    def test_claim_export_failure_preserves_claim(self):
        old=g.write_once
        def write(out,name,value):
            if name=='RESERVATION.json':raise OSError('full')
            return old(out,name,value)
        with patch.object(g,'write_once',side_effect=write):
            with self.assertRaises(OSError):self.run_it()
        self.assertIsNotNone(self.api.claim);self.assertEqual(self.n,0)
        self.assertEqual(json.loads((self.root/'out/FAILED.json').read_text())['stage'],'CLAIM_EXPORT')
    def test_original_exception_survives_failed_receipt(self):
        original=RuntimeError('model error');old=g.write_once
        def run(*args):raise original
        def write(out,name,value):
            if name=='FAILED.json':raise OSError('full')
            return old(out,name,value)
        with patch.object(g,'write_once',side_effect=write):
            with self.assertRaises(RuntimeError) as got:self.run_it(run=run)
        self.assertIs(got.exception,original);self.assertIn('FAILED_RECEIPT',got.exception.__notes__[0]);self.assertIsNotNone(self.api.claim)
    def test_completion_failure_never_replays(self):
        old=g.write_once
        def write(out,name,value):
            if name=='COMPLETED.json':raise OSError('full')
            return old(out,name,value)
        with patch.object(g,'write_once',side_effect=write):
            with self.assertRaises(OSError):self.run_it()
        with self.assertRaises(RuntimeError):self.run_it('other')
        self.assertEqual(self.n,1)
    def test_interrupt_keeps_claim(self):
        def stop(*args):raise KeyboardInterrupt('test')
        with self.assertRaises(KeyboardInterrupt):self.run_it(run=stop)
        self.assertIsNotNone(self.api.claim)
        self.assertEqual(json.loads((self.root/'out/FAILED.json').read_text())['error_type'],'KeyboardInterrupt')

    def test_self_attested_parent_does_not_override_external_approval(self):
        self.api.approved_parent='f'*40
        with self.assertRaisesRegex(SnapshotError,'NOT_INDEPENDENTLY_APPROVED'):self.run_it()
        self.assertIsNone(self.api.claim);self.assertEqual(self.n,0)
    def test_self_repinned_contract_rejected(self):
        self.api.approved_contract='f'*64
        with self.assertRaisesRegex(SnapshotError,'INDEPENDENT_CONTRACT'):self.run_it()
        self.assertIsNone(self.api.claim)
    def test_missing_independent_approval_does_not_consume_claim(self):
        self.api.approval_available=False
        with self.assertRaises(RuntimeError):self.run_it()
        self.assertIsNone(self.api.claim)


if __name__=='__main__':unittest.main()

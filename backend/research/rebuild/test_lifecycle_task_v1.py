"""V3 T1-T8 plus budget and actual native protection counterexamples; no network."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from backend.research.rebuild.lifecycle_task_v1 import Registry, SCOPE, GateError, WORK, bounded_wait, digest
from backend.research.rebuild import g5_exit_ai_pilot_v1 as api
from backend.research.rebuild import trend_primary_protection_v1 as tr
from backend.research.rebuild.test_top5_mechanism_b_v1 import fixture

class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.r=Registry(Path(self.tmp.name)/'TASK.json');self.r.register(SCOPE,'V3')
    def completed(self,scope=SCOPE):
        for w in WORK:
            if w!='W6':self.r.mark(scope,w,'DONE','actual-result:'+w)
        self.r.bind_merge(scope,final_head='f',merge_sha='m',
            ci={'scope_key':scope,'head_sha':'f','run_id':1,'kind':'final_ci','conclusion':'success'},
            reproduction={'scope_key':scope,'head_sha':'m','run_id':2,'kind':'merge_reproduction','conclusion':'success'})
        return self.r.close(scope)
    def test_T1_parent_completion_does_not_block_new_authorized_scope(self):
        self.r.register('PR1204','prior');self.completed('PR1204')
        self.assertTrue(self.r.reserve(SCOPE,'W1','command','new-preparation'))
    def test_T2_rename_recovers_identity_and_budget(self):
        k=self.r.reserve(SCOPE,'W3','economic','candidate');self.r.finish_attempt(SCOPE,k,'DONE')
        a=self.r.register(SCOPE,'V2',document='a.txt',requested_id='fake-a')
        b=self.r.register(SCOPE,'V3',document='b.txt',requested_id='fake-b')
        self.assertEqual(a['task_id'],b['task_id']);self.assertEqual(b['candidate_budget_used'],1)
        with self.assertRaises(GateError):self.r.reserve(SCOPE,'W3','economic','candidate')
    def test_T3_completed_dispatch_and_downgrade_blocked(self):
        self.completed()
        for kind in ('economic','api','pr'):
            with self.assertRaises(GateError):self.r.reserve(SCOPE,'W3',kind,'again')
        with self.assertRaises(GateError):self.r.close(SCOPE,checkpoint=True)
        self.assertEqual(self.r.register(SCOPE,'new',resume=True)['task_status'],'COMPLETED')
    def test_T4_checkpoint_only_unfinished_and_budget_survive(self):
        k=self.r.reserve(SCOPE,'W3','economic','one');self.r.finish_attempt(SCOPE,k,'DONE')
        self.r.mark(SCOPE,'W3','DONE','receipt');self.r.close(SCOPE,checkpoint=True)
        with self.assertRaises(GateError):self.r.reserve(SCOPE,'W4','command','pending')
        t=self.r.register(SCOPE,'continued',resume=True);self.assertEqual(t['candidate_budget_used'],1)
        self.assertNotIn('W3',t['remaining_execution'])
        with self.assertRaises(GateError):self.r.mark(SCOPE,'W3','PENDING','reset')
        self.assertTrue(self.r.reserve(SCOPE,'W4','command','pending'))
    def test_T5_parent_success_cannot_complete_W1_W7(self):
        with self.assertRaises(GateError):self.r.bind_merge(SCOPE,final_head='f',merge_sha='m',ci={'scope_key':'PR1204'},reproduction={})
        with self.assertRaises(GateError):self.r.close(SCOPE)
        self.assertEqual(self.r.get(SCOPE)['remaining_execution'],list(WORK))
    def test_T6_collector_HEAD_does_not_reopen_exact_merge(self):
        saved=self.completed();collector_head='another-commit'
        after=self.r.register(SCOPE,'same',document=collector_head)
        self.assertEqual(saved,after);self.assertEqual(after['merge_sha'],'m')
    def test_T7_bounded_wait_unknown_preserves_request_and_reservation(self):
        clock=[0.]
        def pause(x):clock[0]+=x
        result=bounded_wait(lambda:{'status':'running','run_id':77},timeout_seconds=2,max_polls=3,clock=lambda:clock[0],pause=pause)
        self.assertEqual(result['status'],'UNKNOWN');self.assertEqual(result['last_observation']['run_id'],77)
        k=self.r.reserve(SCOPE,'W2','api','req',provider='gemini',reserve_usd=2.)
        self.r.finish_attempt(SCOPE,k,'UNKNOWN',evidence='HTTP timeout')
        t=self.r.close(SCOPE,checkpoint=True)
        self.assertEqual(t['outstanding_reserved_cost'],2.);self.assertEqual(t['billing_status'],'UNKNOWN')
        self.r.register(SCOPE,'continue',resume=True)
        with self.assertRaises(GateError):self.r.reserve(SCOPE,'W2','api','other',provider='openai',reserve_usd=1.)
        with self.assertRaises(GateError):self.r.close(SCOPE)
    def test_T8_closed_scope_isolated_from_protected_and_other_work(self):
        self.r.register('OTHER','other approval');self.completed()
        self.assertTrue(self.r.reserve('OTHER','W1','command','other'))
        self.assertEqual(self.r.get(SCOPE)['protected_background_jobs'],['Q0','G5B','existing_collectors','other_work'])
    def test_registry_two_instances_do_not_reserve_twice(self):
        self.r.reserve(SCOPE,'W3','economic','same');other=Registry(self.r.path)
        with self.assertRaises(GateError):other.reserve(SCOPE,'W3','economic','same')
        self.assertEqual(other.get(SCOPE)['candidate_budget_used'],1)
    def test_failed_and_unknown_costs_consume_provider_attempt(self):
        k=self.r.reserve(SCOPE,'W2','api','one',provider='gemini',reserve_usd=4.)
        self.r.finish_attempt(SCOPE,k,'DONE',evidence='usage only')
        self.assertEqual(self.r.get(SCOPE)['outstanding_reserved_cost'],4.)
        with self.assertRaises(GateError):self.r.reserve(SCOPE,'W2','api','two',provider='gemini',reserve_usd=.1)

COST={'fee_bps':10.,'spread_bps':1.,'impact_bps':2.,'funding_p95_per_settlement_bps':0.}
class ProtectionTests(unittest.TestCase):
    def setup_path(self,side='long',count=80):
        rows,c,e=fixture(side,count)
        for r in rows:r.update(open=102. if side=='long' else 98.,high=104.,low=96.)
        rows[1]['open']=100.
        c.st=[(99.,1)]*count if side=='long' else [(101.,-1)]*count
        return rows,c,e
    def call(self,rows,c,e,**kwargs):return tr.path(rows,e,c,cost_binding=COST,**kwargs)
    def test_strict_cost_hurdle_and_no_firstbar_samebar_touch(self):
        rows,c,e=self.setup_path();c.st[1]=(100.2,1)
        rows[1]['low']=91.
        # Floating arithmetic around equality is handled via a price-space test.
        t,o,trace,_=self.call(rows,c,e)
        self.assertTrue(all(x['kind']!='PROTECTION_ACTIVATE' for x in trace))
        c.st[1]=(101.,1);rows[2].update(open=102.,low=100.5)
        t,o,trace,_=self.call(rows,c,e)
        self.assertEqual((t['exit_index'],t['exit_price']),(2,101.))
        self.assertEqual(trace[0]['effective_from_index'],2)
    def test_long_short_monotonic_and_direction_jump_rejected(self):
        for side in ('long','short'):
            rows,c,e=self.setup_path(side);sign=1 if side=='long' else -1
            for r in rows[2:]:r.update(open=103. if sign>0 else 97.,low=102. if sign>0 else 95.,high=105. if sign>0 else 98.)
            c.st[1]=(100.+sign,sign);c.st[2]=(100.+.5*sign,sign);c.st[3]=(200. if sign>0 else 1.,-sign)
            rows[4]['open']=100.5 if sign>0 else 99.5
            t,_,trace,_=self.call(rows,c,e)
            self.assertEqual(t['exit_index'],4);self.assertEqual(t['exit_reason'],'PROTECTION_GAP_OPEN')
            levels=[x['level'] for x in trace if x['kind'].startswith('PROTECTION_') and 'level' in x]
            self.assertEqual(levels,[100.+sign])
    def test_gap_exit_cannot_see_future_HLC(self):
        rows,c,e=self.setup_path();c.st[1]=(101.,1);rows[2]['open']=99.
        before=self.call(rows,c,e)[0];rows[2].update(high=10000.,low=1.,close=5000.)
        self.assertEqual(before,self.call(rows,c,e)[0]);self.assertEqual(before['exit_price'],99.)
    def test_native_stop_tp_priority_over_intrabar_protection(self):
        rows,c,e=self.setup_path();c.st[1]=(101.,1);rows[2].update(open=102.,low=89.)
        self.assertEqual(self.call(rows,c,e)[0]['exit_reason'],'SL')
        rows[2]['low']=100.;e['tp']=105.;rows[2]['high']=106.
        self.assertEqual(self.call(rows,c,e)[0]['exit_reason'],'TP')
    def test_original_timeout_no_extension_and_terminal_censor(self):
        rows,c,e=self.setup_path();t=self.call(rows,c,e)[0]
        self.assertEqual((t['exit_index'],t['exit_reason']),(49,'TIMEOUT'))
        t,o,_,_=self.call(rows[:50],c,e);self.assertIsNone(t);self.assertFalse(o['terminal_liquidation'])
        rows[49]['low']=89.;t,o,_,_=self.call(rows[:50],c,e)
        self.assertIsNone(t);self.assertEqual(o['boundary_native_fill_reason'],'SL');self.assertLess(o['gross_mark_bps'],0)
    def test_restart_and_future_line_prefix_independence(self):
        rows,c,e=self.setup_path();c.st[5]=(101.,1);rows[6]['open']=100.
        full=self.call(rows,c,e);ck=self.call(rows[:6],c,e)[3]
        self.assertEqual(full,self.call(rows,c,e,checkpoint=json.loads(json.dumps(ck))))
        altered=deepcopy(c);altered.st[20:]=[(200.,-1)]*(len(rows)-20)
        self.assertEqual(full,self.call(rows,altered,e))
    def test_real_ownership_cooldown_blocks_followup(self):
        rows,c,e=self.setup_path();c.st[1]=(101.,1);rows[2]['open']=100.
        tape=[e]
        for i in (1,2,3):
            k=deepcopy(e);k.update(signal_index=i,signal_ts=(i+1)*tr.HOUR);tape.append(k)
        out=tr.replay(rows,tape,c,COST)
        self.assertEqual([x['status'] for x in out['events'][:3]],['COMPLETED','EXCLUDED','EXCLUDED'])

class APITests(unittest.TestCase):
    def config(self):
        d={'data_class':'DEV_USED','holdout_access':False,'source_hashes':{'fixture':'abc'},'purpose':'counterexample only'}
        q={'provider':'gemini','model':'fixture-model','official_source_url':'https://ai.google.dev/gemini-api/docs/pricing','checked_at':'fixture-not-real-price',
           'currency':'USD','adapter_verified':True,'combined_output_thinking_cap_verified':True,'tools_disabled':True,'cache_disabled':True,
           'tax_fx_upper_bound_usd':.1,'input_usd_per_million':1.,'output_thinking_usd_per_million':2.,'utf8_bytes_bound_tokens_verified':True}
        a={'scope_key':SCOPE,'approval_id':'synthetic','explicit_manual_approval':True,'provider':'gemini','model':'fixture-model',
           'dossier_sha':digest(d),'price_sha':digest(q),'allowlisted_models':['fixture-model']}
        return d,a,q
    def test_push_pr_cron_and_missing_key_have_zero_transport(self):
        d,a,q=self.config()
        for event in ('push','pull_request','schedule'):
            with self.assertRaises(GateError):api.preflight(d,a,q,event=event,key_present=True)
        with self.assertRaises(GateError):api.preflight(d,a,q,event='workflow_dispatch',key_present=False)
    def test_unknown_quote_or_input_isolation_blocks(self):
        for field,value in [('combined_output_thinking_cap_verified',False),('tax_fx_upper_bound_usd',None),('input_usd_per_million',1000.)]:
            d,a,q=self.config();q[field]=value;a['price_sha']=digest(q)
            with self.assertRaises(GateError):api.preflight(d,a,q,event='workflow_dispatch',key_present=True)
        d,a,q=self.config();d['data_class']='HOLDOUT_SEALED';a['dossier_sha']=digest(d)
        with self.assertRaises(GateError):api.preflight(d,a,q,event='workflow_dispatch',key_present=True)
    def test_timeout_one_call_no_retry_and_reservation_remains(self):
        d,a,q=self.config();calls=[]
        def fail(*args,**kwargs):calls.append(kwargs['timeout']);raise TimeoutError()
        with tempfile.TemporaryDirectory() as tmp:
            r=Registry(Path(tmp)/'TASK.json');r.register(SCOPE,'test')
            with patch.object(api,'verify_dossier_sources'):
                x=api.request_once(r,d,a,q,event='workflow_dispatch',transport=fail,key='fixture')
            self.assertEqual(calls,[45]);self.assertEqual(x['billing_status'],'UNKNOWN');self.assertIsNone(x['settled_cost'])
            with patch.object(api,'verify_dossier_sources'), self.assertRaises(GateError):api.request_once(r,d,a,q,event='workflow_dispatch',transport=fail,key='fixture')
            self.assertEqual(len(calls),1);self.assertGreater(r.get(SCOPE)['outstanding_reserved_cost'],0)
    def test_workflow_automatic_jobs_have_no_secrets_or_paid_dispatch(self):
        text=Path('.github/workflows/g5-exit-ai-research-v1.yml').read_text()
        verify=text.split('  verify:',1)[1].split('  pilot:',1)[0]
        self.assertNotIn('secrets.',verify);self.assertNotIn('g5_exit_ai_research_v2 \\',verify)
        self.assertIn("github.event_name == 'workflow_dispatch'",text)
        self.assertNotIn('--force-retry',text)

if __name__=='__main__':unittest.main()

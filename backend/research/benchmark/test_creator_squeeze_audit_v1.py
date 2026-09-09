"""Offline authorization, expense and source-fidelity tests. No model requests."""
import unittest,json
from copy import deepcopy
from backend.research.benchmark import creator_squeeze_audit_v1 as a
class AuditTests(unittest.TestCase):
 def fixture(self):
  e={'action':'created','repository':{'full_name':a.REPO},'sender':{'id':a.OWNER_ID},'comment':{'id':1,'user':{'id':a.OWNER_ID},'author_association':'OWNER','body':'APPROVE_CREATOR_SQUEEZE_AI abc'},'issue':{'number':1235,'pull_request':{'url':'x'}}}
  env={'GITHUB_EVENT_NAME':'issue_comment','GITHUB_RUN_ATTEMPT':'1'}
  pr={'number':1235,'merged':True,'merge_commit_sha':'x','head':{'ref':a.BRANCH,'repo':{'full_name':a.REPO}},'base':{'ref':'master'}}
  return e,env,pr
 def test_exact_owner_manual(self):
  e,env,pr=self.fixture();self.assertEqual(a.authorize(e,env,'abc',pr)['comment_id'],1)
 def test_push_cannot_call(self):
  e,env,pr=self.fixture();env['GITHUB_EVENT_NAME']='push'
  with self.assertRaisesRegex(ValueError,'MANUAL'):a.authorize(e,env,'abc',pr)
 def test_PR_cannot_call(self):
  e,env,pr=self.fixture();env['GITHUB_EVENT_NAME']='pull_request'
  with self.assertRaises(ValueError):a.authorize(e,env,'abc',pr)
 def test_cron_cannot_call(self):
  e,env,pr=self.fixture();env['GITHUB_EVENT_NAME']='schedule'
  with self.assertRaises(ValueError):a.authorize(e,env,'abc',pr)
 def test_repeat_attempt_cannot_call(self):
  e,env,pr=self.fixture();env['GITHUB_RUN_ATTEMPT']='2'
  with self.assertRaisesRegex(ValueError,'NO_RETRY'):a.authorize(e,env,'abc',pr)
 def test_nonowner_cannot_call(self):
  e,env,pr=self.fixture();e['comment']['user']['id']=0
  with self.assertRaisesRegex(ValueError,'OWNER'):a.authorize(e,env,'abc',pr)
 def test_sender_cannot_spoof(self):
  e,env,pr=self.fixture();e['sender']['id']=0
  with self.assertRaises(ValueError):a.authorize(e,env,'abc',pr)
 def test_unmerged_code_cannot_call(self):
  e,env,pr=self.fixture();pr['merged']=False
  with self.assertRaisesRegex(ValueError,'MERGED'):a.authorize(e,env,'abc',pr)
 def test_edited_comment_cannot_call(self):
  e,env,pr=self.fixture();e['action']='edited'
  with self.assertRaises(ValueError):a.authorize(e,env,'abc',pr)
 def test_wrong_approval_cannot_call(self):
  e,env,pr=self.fixture()
  with self.assertRaisesRegex(ValueError,'EXACT_APPROVAL'):a.authorize(e,env,'def',pr)
 def test_fork_cannot_call(self):
  e,env,pr=self.fixture();pr['head']['repo']['full_name']='attacker/clone'
  with self.assertRaises(ValueError):a.authorize(e,env,'abc',pr)
 def test_other_PR_cannot_call(self):
  e,env,pr=self.fixture();pr['number']=0
  with self.assertRaises(ValueError):a.authorize(e,env,'abc',pr)
 def ledger(self):return {'status':'ACTIVE','slots':{p:{'state':'RESERVED_NOT_STARTED','reserved_usd':2.5} for p in a.MODELS}}
 def test_reserved_before_start(self):a.can_start(self.ledger(),'gemini')
 def test_terminal_all_block(self):
  for state in a.TERMINAL:
   l=self.ledger();l['status']=state
   with self.subTest(state=state),self.assertRaisesRegex(ValueError,'TASK_TERMINAL'):a.can_start(l,'gemini')
 def test_failed_consumption_cannot_retry(self):
  l=self.ledger();l['slots']['gemini']['state']='FAILED_OR_UNKNOWN_CONSUMED'
  with self.assertRaisesRegex(ValueError,'ALREADY_STARTED'):a.can_start(l,'gemini')
 def test_unknown_stops_next_provider(self):
  l=self.ledger();l['slots']['gemini']['state']='FAILED_OR_UNKNOWN_CONSUMED'
  with self.assertRaisesRegex(ValueError,'PRIOR_REQUEST'):a.can_start(l,'openai')
 def test_budget_is_total(self):
  l=self.ledger();l['slots']['openai']['reserved_usd']=2.51
  with self.assertRaisesRegex(ValueError,'BUDGET'):a.can_start(l,'gemini')
 def test_reservation_not_freed_before_invoice(self):
  l=self.ledger();l['slots']['gemini']['state']='RESPONSE_COMPLETE';a.can_start(l,'openai');self.assertEqual(sum(x['reserved_usd'] for x in l['slots'].values()),5.)
 def test_source_requires_section(self):
  with self.assertRaisesRegex(ValueError,'START'):a.section(b'<p>error</p>','START','END')
 def test_source_no_script_as_evidence(self):
  raw=('<script>START misleading END</script><p>START '+('explicit ' *20)+'END</p>').encode();t,_=a.section(raw,'START','END');self.assertNotIn('misleading',t)
 def test_source_hash_real_bytes(self):
  r=('<p>START '+('abc '*40)+'END</p>').encode();t,v=a.section(r,'START','END');self.assertEqual(v['raw_sha256'],a.sha(r));self.assertEqual(v['selected_sha256'],a.sha(t.encode()))
 def test_input_bound(self):
  with self.assertRaisesRegex(ValueError,'INPUT'):a.make_prompt('gemini',{'x':'x'*16000},{})
 def test_no_tools_or_provider_switch(self):
  for p in a.MODELS:self.assertEqual(a.body_for(p,'JSON')['tools'],[])
  with self.assertRaises(ValueError):a.body_for('groq','x')
 def test_openai_bound_and_no_background(self):
  b=a.body_for('openai','JSON');self.assertEqual(b['max_output_tokens'],6000);self.assertFalse(b['store']);self.assertFalse(b['background']);self.assertEqual(b['prompt_cache_options'],{'mode':'explicit'})
 def test_gemini_thinking_is_counted(self):
  r={'rules':[],'unresolved':[],'evidence_class':'EDUCATIONAL','source_example_available':False,'portability_limits':[]}
  p={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(r)}]}}],'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':100,'thoughtsTokenCount':200}}
  _,_,cost=a.decode('gemini',p);self.assertAlmostEqual(cost,.0038)
  p['usageMetadata']['thoughtsTokenCount']=6001
  with self.assertRaisesRegex(ValueError,'USAGE'):a.decode('gemini',p)
 def test_truncated_response_not_success(self):
  with self.assertRaisesRegex(ValueError,'INCOMPLETE'):a.decode('openai',{'status':'incomplete'})
 def test_missing_schema_not_success(self):
  p={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'{}'}]}],'usage':{'input_tokens':1,'output_tokens':1}}
  with self.assertRaisesRegex(ValueError,'SCHEMA_KEYS'):a.decode('openai',p)
 def test_qualitative_plan_not_executable(self):
  self.assertFalse(a.contract_gate({'setup_definition':{'status':'QUALITATIVE'}})['executable_original'])
 def test_no_strategy_authority_from_AI_or_schema(self):
  keys=a.contract_gate({})['missing'];c={k:{'status':'EXPLICIT_EXECUTABLE'} for k in keys}
  out=a.contract_gate(c);self.assertTrue(out['executable_original']);self.assertFalse(out['original_strategy_economic_authorized']);self.assertEqual(out['formal_credit'],0)
 def test_current_contract_keeps_gaps(self):
  c=a.read(a.ROOT/a.OUT/'SOURCE_CONTRACT.json');g=a.contract_gate(c)
  for k in ('setup_definition','entry_expiry','residual_exit','fill_model'):self.assertIn(k,g['missing'])
if __name__=='__main__':unittest.main()

"""Artificial inputs only: request budget, independent roles and safe receipts."""
import json, unittest
from copy import deepcopy
from unittest.mock import patch
from urllib.error import HTTPError
from backend.research.benchmark import jc_independent_ai_review_v1 as r

RESULT={'supported_findings':[], 'unproven_hypotheses':[], 'source_code_mismatches':[],
        'counterexample_tests':[], 'next_action':{}, 'limitations':[]}
KEY='synthetic-not-a-real-provider-credential-12345'
def one(*args,**kwargs):return r.one(*args,source_text='artificial publisher context with disjoint wording',**kwargs)
def response():
    return {'status':'completed','id':'artificial_response','model':r.MODELS['openai'],
      'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(RESULT)}]}],
      'usage':{'input_tokens':1000,'output_tokens':700}}
def slot():return {'state':'RESERVED_NOT_STARTED','attempts':0,'reserved_usd':.75,'usage':None,'result':None}
def transport(*args,**kwargs):return r.canonical(response()),200
class IndependentReviewTests(unittest.TestCase):
    def test_budget_bound(self):
        self.assertEqual(sum(r.RESERVES.values()),1.)
        for p,(i,o) in r.RATES.items():
            self.assertLess(((r.INPUT_BYTES+1024)*i+r.OUTPUT_CAP*o)/1e6,r.RESERVES[p])
    def test_keys_not_normalized_and_other_role_runs(self):
        g,o=slot(),slot(); calls=[]
        one('gemini',KEY+'\n','{}',g,lambda:None,lambda *a,**k:calls.append(a))
        one('openai',KEY,'{}',o,lambda:None,transport)
        self.assertEqual(g['state'],'NOT_CALLED_CREDENTIAL_PREFLIGHT')
        self.assertEqual(g['error_code'],'KEY_CONTROL_CHARACTER');self.assertFalse(calls)
        self.assertEqual(g['attempts'],0);self.assertEqual(o['state'],'RESPONSE_COMPLETE')
        self.assertEqual(o['attempts'],1)
    def test_missing_key_no_call(self):
        s=slot()
        one('openai','','{}',s,lambda:None,lambda *a,**k:self.fail('network'))
        self.assertEqual(s['attempts'],0)
    def test_start_persist_precedes_transport(self):
        s=slot();events=[]
        def call(*a,**k):
            self.assertEqual(events,['STARTED']);return transport()
        one('openai',KEY,'{}',s,lambda:events.append(s['state']),call)
        self.assertEqual(events,['STARTED','RESPONSE_COMPLETE'])
    def test_failed_persist_no_call(self):
        def fail():raise RuntimeError('synthetic persistence failure')
        with self.assertRaises(RuntimeError):
            one('openai',KEY,'{}',slot(),fail,lambda *a,**k:self.fail('network'))
    def test_once_even_after_failed_request(self):
        s=slot();calls=[]
        def fail(*a,**k):calls.append(1);raise TimeoutError()
        one('openai',KEY,'{}',s,lambda:None,fail)
        self.assertEqual(len(calls),1);self.assertEqual(s['state'],'FAILED_OR_UNKNOWN_CONSUMED')
        self.assertNotIn('estimated_token_charge_usd',s)
        with self.assertRaises(ValueError):one('openai',KEY,'{}',s,lambda:None,transport)
    def test_http_status_without_raw_error(self):
        s=slot()
        def fail(*a,**k):raise HTTPError(r.URLS['openai'],401,KEY,{},None)
        one('openai',KEY,'{}',s,lambda:None,fail)
        self.assertEqual(s['http_status'],401);self.assertNotIn(KEY,json.dumps(s))
    def test_bad_json_keeps_http_status_hash(self):
        s=slot();one('openai',KEY,'{}',s,lambda:None,lambda *a,**k:(b'{',200))
        self.assertEqual(s['http_status'],200);self.assertEqual(s['error_phase'],'RESPONSE_JSON')
        self.assertEqual(s['response_sha256'],r.sha(b'{'))
    def test_bad_schema_keeps_usage(self):
        s=slot();p=response();p['output'][0]['content'][0]['text']='{}'
        one('openai',KEY,'{}',s,lambda:None,lambda *a,**k:(r.canonical(p),200))
        self.assertEqual(s['usage'],p['usage']);self.assertEqual(s['state'],'FAILED_OR_UNKNOWN_CONSUMED')
    def test_incomplete_not_success(self):
        p=response();p['status']='incomplete'
        with self.assertRaises(ValueError):r.decode('openai',p)
    def test_thinking_in_cost(self):
        p={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(RESULT)}]}}],
           'usageMetadata':{'promptTokenCount':1000,'candidatesTokenCount':300,'thoughtsTokenCount':700}}
        _,cost=r.decode('gemini',p);self.assertAlmostEqual(cost,.014)
    def test_bodies_fixed_no_tools_or_fallback(self):
        o=r.body_for('openai','{}');g=r.body_for('gemini','{}')
        self.assertFalse(o['store']);self.assertFalse(o['background']);self.assertEqual(o['tools'],[])
        self.assertEqual(g['generationConfig']['maxOutputTokens'],r.OUTPUT_CAP)
        with self.assertRaises(ValueError):r.body_for('openai','X'*(r.INPUT_BYTES+1))
    def test_source_excludes_other_plans(self):
        text='Name of Trade/Strategy: THE BEST TIME TO BUY OPTIONS Rules for Entry: '+('a '*60)+' Position Sizing: b Futures PRIVATE_OTHER_PLAN'
        result=r.section(('<p>'+text+'</p>').encode());self.assertNotIn('PRIVATE_OTHER_PLAN',result)
        with self.assertRaises(ValueError):r.section(b'no specific plan here')
    def test_ast_is_source_only(self):
        source='def ignore():\n    raise Exception()\n\ndef target(x):\n    return x+1\n'
        self.assertEqual(r.function_text(source,'target'),'def target(x):\n    return x+1')
    def test_authorization(self):
        e={'repository':{'full_name':r.REPO},'action':'created','sender':{'id':232057951},
           'comment':{'user':{'id':232057951},'author_association':'OWNER','body':r.TOKEN},'issue':{'number':99}}
        p={'number':99,'merged':True,'head':{'ref':r.BRANCH,'repo':{'full_name':r.REPO}},'base':{'ref':'master'}}
        env={'GITHUB_EVENT_NAME':'issue_comment','GITHUB_RUN_ATTEMPT':'1'}
        r.authorize(e,env,p)
        for bad in ({**env,'GITHUB_RUN_ATTEMPT':'2'},{**env,'GITHUB_EVENT_NAME':'push'}):
            with self.assertRaises(ValueError):r.authorize(e,bad,p)
        e['comment']['user']['id']=0
        with self.assertRaises(ValueError):r.authorize(e,env,p)
    def test_transport_rejects_other_hosts(self):
        with self.assertRaises(ValueError):r.request('https://example.com/',key=KEY)
    def test_model_never_sees_credentials(self):
        p=r.prompt('openai','source','gate',{'setup':'code'})
        self.assertNotIn(KEY,p);self.assertIn('Extra-wait-only witnesses are zero',p)
        self.assertNotEqual(p,r.prompt('gemini','source','gate',{'setup':'code'}))

    def test_publication_limits_and_overlap(self):
        good=deepcopy(RESULT);good['supported_findings']=['Different prose.']
        self.assertEqual(r.public_result(good,'source text'),good)
        for text,source in [('x '*151,'source'),('one two three four five six','one two three four five six seven')]:
            bad=deepcopy(RESULT);bad['supported_findings']=[text]
            with self.assertRaises(ValueError):r.public_result(bad,source)
        s=slot();p=response();p['output'][0]['content'][0]['text']=json.dumps(bad)
        r.one('openai',KEY,'{}',s,lambda:None,lambda *a,**k:(r.canonical(p),200),source_text=source)
        self.assertEqual(s['state'],'FAILED_OR_UNKNOWN_CONSUMED');self.assertIsNone(s['result'])
        self.assertEqual(s['http_status'],200);self.assertIsNotNone(s['estimated_token_charge_usd'])
    def test_all_claimed_code_dependencies_in_input(self):
        inputs=r.code_inputs()
        for name in ('features.validate','features._average','features.squeeze_features','features.confirmed_pivots',
                     'features.completed_utc_days','lifecycle.daily_features','lifecycle.setup_at'):
            self.assertIn(name,inputs)
        self.assertIn('BAR_MS=14400000',inputs['constants'])

if __name__=='__main__':unittest.main()

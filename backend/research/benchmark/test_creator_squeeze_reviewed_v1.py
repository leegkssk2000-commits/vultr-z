import unittest,json
from copy import deepcopy
from unittest.mock import patch
from backend.research.benchmark import creator_squeeze_reviewed_v1 as r
from backend.research.benchmark.test_creator_squeeze_audit_v1 import AuditTests
class ReviewTests(unittest.TestCase):
 def gem(self):return dict(rules=[dict(stage='exit',source_id='S1',locator='Exits',paraphrase='Retain stated stages.',status='EXPLICIT')],unresolved=[],evidence_class='EDUCATIONAL',source_example_available=False,portability_limits=[])
 def critic(self):return dict(mismatches=[dict(field='timing',source_id='S1',source_locator='Entry',code_symbol='squeeze_features',problem='Different timing.')],unresolved=[],counterexample_tests=['Clock boundary.'],executable_original=False,recommended_next_artifact='Bounded source map.')
 def test_valid_gemini(self):r.validate_result('gemini',self.gem())
 def test_valid_critic(self):r.validate_result('openai',self.critic())
 def test_null_rules(self):
  x=self.gem();x['rules']=None
  with self.assertRaisesRegex(ValueError,'RULES_LIST'):r.validate_result('gemini',x)
 def test_null_item(self):
  x=self.gem();x['rules']=[None]
  with self.assertRaisesRegex(ValueError,'ITEM_SCHEMA'):r.validate_result('gemini',x)
 def test_missing_nested_locator(self):
  x=self.gem();del x['rules'][0]['locator']
  with self.assertRaises(ValueError):r.validate_result('gemini',x)
 def test_wrong_source(self):
  x=self.gem();x['rules'][0]['source_id']='S9'
  with self.assertRaisesRegex(ValueError,'SOURCE_ID'):r.validate_result('gemini',x)
 def test_wrong_status(self):
  x=self.gem();x['rules'][0]['status']='PROFIT_VERIFIED'
  with self.assertRaisesRegex(ValueError,'STATUS'):r.validate_result('gemini',x)
 def test_boolean_not_string(self):
  x=self.critic();x['executable_original']='false'
  with self.assertRaisesRegex(ValueError,'BOOLEAN'):r.validate_result('openai',x)
 def test_dict_not_mismatch_list(self):
  x=self.critic();x['mismatches']={}
  with self.assertRaisesRegex(ValueError,'MISMATCH_LIST'):r.validate_result('openai',x)
 def test_dict_not_string_counterexample(self):
  x=self.critic();x['counterexample_tests']=[{}]
  with self.assertRaisesRegex(ValueError,'STRING_LIST'):r.validate_result('openai',x)
 def test_null_unresolved(self):
  x=self.gem();x['unresolved']=None
  with self.assertRaises(ValueError):r.validate_result('gemini',x)
 def test_decode_applies_shape_before_return(self):
  x=self.gem();x['rules']=None
  payload=dict(candidates=[dict(finishReason='STOP',content=dict(parts=[dict(text=json.dumps(x))]))],usageMetadata=dict(promptTokenCount=1,candidatesTokenCount=1,thoughtsTokenCount=0))
  with self.assertRaisesRegex(ValueError,'RULES_LIST'):r.checked_decode('gemini',payload)
 def test_exact_merge(self):
  e,env,pr=AuditTests().fixture()
  with patch.object(r.a,'git',return_value='x'):self.assertEqual(r.exact_authorize(e,env,'abc',pr)['merge_sha'],'x')
 def test_newer_master_not_allowed(self):
  e,env,pr=AuditTests().fixture()
  with patch.object(r.a,'git',return_value='newer'):
   with self.assertRaisesRegex(ValueError,'EXACT_APPROVED'):r.exact_authorize(e,env,'abc',pr)
 def test_typed_prompt_bound(self):
  t=r.typed_prompt('openai',{},{});self.assertIn('arrays of strings',t)
  with self.assertRaises(ValueError):r.typed_prompt('openai',{'x':'a'*16000},{})
 def test_single_entrypoint_restores_hooks(self):
  before=(r.a.authorize,r.a.decode,r.a.make_prompt)
  with patch.object(r.a,'run',side_effect=RuntimeError('offline')):
   with self.assertRaises(RuntimeError):r.run()
  self.assertEqual(before,(r.a.authorize,r.a.decode,r.a.make_prompt))
if __name__=='__main__':unittest.main()

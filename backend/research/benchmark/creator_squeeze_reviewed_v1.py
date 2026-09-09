"""Reviewed execution boundary for the finite source audit; no new provider route."""
import argparse,json
from urllib.parse import urlsplit
from backend.research.benchmark import creator_squeeze_audit_v1 as a
AUTH,DECODE,PROMPT,REQUEST=a.authorize,a.decode,a.make_prompt,a.Request

def exact_authorize(event,env,approval_sha,pr):
 auth=AUTH(event,env,approval_sha,pr)
 a.need(a.git('rev-parse','HEAD')==auth['merge_sha'],'EXECUTION_NOT_EXACT_APPROVED_MERGE')
 return auth

def media_request(url,*args,**kwargs):
 """Correct the reviewed runner's GitHub media header without changing I/O."""
 parts=urlsplit(url)
 if parts.scheme=='https' and parts.netloc=='api.github.com':
  headers=dict(kwargs.get('headers',{}));headers['Accept']='application/vnd.github+json'
  kwargs=dict(kwargs,headers=headers)
 return REQUEST(url,*args,**kwargs)

def validate_result(provider,result):
 a.need(isinstance(result,dict),'RESULT_OBJECT')
 def text(x):return isinstance(x,str) and bool(x.strip())
 def strings(key):
  a.need(isinstance(result.get(key),list) and all(text(x) for x in result[key]),'RESULT_STRING_LIST:'+key)
 strings('unresolved')
 if provider=='gemini':
  a.need(type(result.get('source_example_available')) is bool,'RESULT_BOOLEAN')
  a.need(text(result.get('evidence_class')),'RESULT_EVIDENCE_CLASS');strings('portability_limits')
  rows=result.get('rules');fields=('stage','source_id','locator','paraphrase','status')
  a.need(isinstance(rows,list) and bool(rows),'RESULT_RULES_LIST')
 else:
  a.need(provider=='openai','RESULT_PROVIDER')
  a.need(type(result.get('executable_original')) is bool,'RESULT_BOOLEAN')
  a.need(text(result.get('recommended_next_artifact')),'RESULT_RECOMMENDATION');strings('counterexample_tests')
  rows=result.get('mismatches');fields=('field','source_id','source_locator','code_symbol','problem')
  a.need(isinstance(rows,list),'RESULT_MISMATCH_LIST')
 for row in rows:
  a.need(isinstance(row,dict) and all(text(row.get(k)) for k in fields),'RESULT_ITEM_SCHEMA')
  a.need(row['source_id'] in a.SOURCES,'RESULT_SOURCE_ID')
  if provider=='gemini':a.need(row['status'] in ('EXPLICIT','QUALITATIVE','UNSPECIFIED'),'RESULT_STATUS')
 return result

def checked_decode(provider,payload):
 result,usage,cost=DECODE(provider,payload);validate_result(provider,result)
 a.need(cost>=0,'NEGATIVE_USAGE_COST')
 return result,usage,cost

def typed_prompt(provider,sources,code,gemini=None):
 text=PROMPT(provider,sources,code,gemini);obj=json.loads(text)
 obj['task']+=' All unresolved/portability_limits/counterexample_tests values are arrays of strings; availability/executable fields are booleans; other scalar fields are strings. Only the two supplied code functions were inspected, not the whole order or fill engine.'
 text=json.dumps(obj,ensure_ascii=False,separators=(',',':'))
 a.need(len(text.encode())<=a.INPUT_BYTES,'INPUT_BOUND_EXCEEDED')
 return text

def run():
 original=(a.authorize,a.decode,a.make_prompt,a.Request)
 a.authorize,a.decode,a.make_prompt,a.Request=exact_authorize,checked_decode,typed_prompt,media_request
 try:return a.run()
 finally:a.authorize,a.decode,a.make_prompt,a.Request=original

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--run',action='store_true');args=p.parse_args()
 if args.run:
  outcome=run()
  if outcome and outcome['status']!='COMPLETED':raise SystemExit(2)
 else:print(json.dumps(a.contract_gate(a.read(a.ROOT/a.OUT/'SOURCE_CONTRACT.json'))))

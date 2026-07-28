from __future__ import annotations
import argparse, hashlib, json, os, urllib.request, urllib.error
from pathlib import Path
from typing import Any, Mapping

VERSION='R7A4D_STRATEGY11_GEMINI22_SECOND_CAUSAL_V1'
FORBIDDEN=('api_key','secret','token','password','credential','account','order_id','position_id')

def load(p: Path)->Any: return json.loads(p.read_text(encoding='utf-8'))
def stable(v: Any)->str: return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sanitize(v: Any, depth:int=0)->Any:
    if depth>7:return '<depth-limit>'
    if isinstance(v,Mapping):
        return {str(k):sanitize(x,depth+1) for k,x in v.items() if not any(t in str(k).lower() for t in FORBIDDEN)}
    if isinstance(v,list):return [sanitize(x,depth+1) for x in v[:250]]
    if isinstance(v,str):return v[:3000]
    if isinstance(v,(int,float,bool)) or v is None:return v
    return str(v)[:500]

def call(key:str,prompt:str)->tuple[str,dict[str,Any]]:
    models=['models/gemini-3.6-flash','models/gemini-2.5-flash']
    body=json.dumps({'contents':[{'role':'user','parts':[{'text':prompt}]}],'generationConfig':{'responseMimeType':'application/json','temperature':0.05,'maxOutputTokens':16384}}).encode()
    errors=[]
    for model in models:
        try:
            req=urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/{model}:generateContent',data=body,headers={'x-goog-api-key':key,'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(req,timeout=900) as r:d=json.load(r)
            text='\n'.join(p.get('text','') for c in d.get('candidates',[]) for p in c.get('content',{}).get('parts',[]) if isinstance(p.get('text'),str)).strip()
            obj=json.loads(text)
            if isinstance(obj,list) and len(obj)==1 and isinstance(obj[0],dict):obj=obj[0]
            if not isinstance(obj,dict):raise ValueError('NON_OBJECT_JSON')
            return model,obj
        except Exception as e:errors.append(f'{model}:{type(e).__name__}:{e}')
    raise RuntimeError('GEMINI_FAILED|'+'|'.join(errors))

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--artifact-root',required=True);ap.add_argument('--out',required=True);a=ap.parse_args()
    root=Path(a.artifact_root);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    final=load(root/'final/final.json')
    assert final['state']=='PASS' and final['strategy_count']==22 and final['active_l080_queue']==[]
    key=os.environ.get('GEMINI_API_KEY','').strip()
    if not key:raise RuntimeError('GEMINI_API_KEY_MISSING')
    profiles={p.stem:load(p) for p in sorted((root/'plan/profiles').glob('*.json'))}
    rows={r['strategy_id']:r for r in final['rows']}
    ids=list(rows)
    calls=[]; reviews=[]
    for idx,group in enumerate((ids[:11],ids[11:]),1):
        payload=[{'strategy_id':sid,'final':sanitize(rows[sid]),'profile':sanitize(profiles.get(f'S{ids.index(sid)+1:02d}',{}))} for sid in group]
        prompt='''You are an independent second-pass causal reviewer for quantitative strategies that produced no candidate under a prior bounded BE/partial/trailing/time-stop L085 replay. Do not repeat those axes unless a genuinely different mechanism is evidenced. For each strategy decide either WAIT_W1 or NOVEL_CAUSAL_AXIS. A novel axis must be single-cause, falsifiable, bounded, and inferable only from supplied anonymized metrics/structure. Do not claim improvement. Return JSON: {status:"PASS",rows:[{strategy_id,decision,causal_axis,why_distinct,evidence,required_w1_fields,falsification_test,overfit_risk}]}.''' + '\nINPUT='+json.dumps(payload,sort_keys=True)
        model,res=call(key,prompt);reviews.extend(res.get('rows',[]));calls.append({'stage':f'GROUP_{idx}','model':model,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'response_sha256':stable(res)})
    adjud_prompt='''Red-team these second-pass reviews. Reject duplicated prior axes, unsupported causal stories, parameter mining, winner contamination, or anything not testable on a new non-overlap W1 window. This is the final second review; all strategies must end in W1_CAUSAL_WAIT. Preserve at most a research note for genuinely novel axes, but execution_allowed must remain false. Return JSON {status:"PASS",rows:[{strategy_id,final_state:"W1_CAUSAL_WAIT",research_note|null,reopen_condition}],approved_execution_count:0}. INPUT='''+json.dumps(sanitize(reviews),sort_keys=True)
    model,adj=call(key,adjud_prompt);calls.append({'stage':'RED_TEAM','model':model,'prompt_sha256':hashlib.sha256(adjud_prompt.encode()).hexdigest(),'response_sha256':stable(adj)})
    result={'schema_version':'1.0','version':VERSION,'state':'PASS','strategy_count':22,'second_causal_review_complete':True,'GEMINI_USED':True,'free_only':True,'gemini_call_count':len(calls),'call_audit':calls,'rows':adj.get('rows',[]),'approved_execution_count':0,'next':'W1_CAUSAL_WAIT','source_final_sha256':stable(final),'private_code_sent':False,'account_data_sent':False,'exchange_credentials_sent':False,'canonical_mutated':False,'registry_mutated':False,'protected_mutations':0,'execution_allowed':False,'paper_allowed':False,'live_allowed':False,'order_authority':'BLOCKED','blockers':[]}
    assert len(result['rows'])==22
    (out/'second_causal_review.json').write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'state':'PASS','strategies':22,'next':'W1_CAUSAL_WAIT'}))
    return 0
if __name__=='__main__':raise SystemExit(main())

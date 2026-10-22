"""Reuse the completed C trace; do not regenerate prices, native signals or PnL."""
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict
import json,gzip,hashlib
S=Path(__file__).resolve().parent
P=Path('/home/z/z/runtime/k126_c_veto_consume_20261022_v1')
def sha(b):return hashlib.sha256(b).hexdigest()
def array_items(path):
 decoder=json.JSONDecoder();buf='';started=False;eof=False
 with gzip.open(path,'rt') as f:
  while True:
   if not eof:
    chunk=f.read(262144);eof=not chunk;buf+=chunk
   while True:
    buf=buf.lstrip()
    if not started:
     if not buf:break
     if not buf.startswith('['):raise ValueError('ARRAY_REQUIRED')
     buf=buf[1:];started=True;continue
    if buf.startswith(','):buf=buf[1:];continue
    if buf.startswith(']'):return
    if not buf:break
    try:value,end=decoder.raw_decode(buf)
    except json.JSONDecodeError:
     if eof:raise
     break
    yield value;buf=buf[end:]
   if eof:raise ValueError('INCOMPLETE_ARRAY')

def main():
 receipt=json.loads((P/'observer/OBSERVER_RECEIPT.json').read_bytes())
 for n,pin in receipt['files'].items():
  if sha((P/'observer'/n).read_bytes())!=pin['sha256']:raise ValueError('TRACE_CHANGED:'+n)
 attribution=json.loads((P/'ORIGIN_ATTRIBUTION_ALL126.json').read_bytes())
 latest=json.loads((P/'SUMMARY.json').read_bytes());removed={tuple(t['key']) for t in latest['removed']}
 groups=defaultdict(list);tracking={}
 for r in attribution:
  k=tuple(r['key']);groups[k[0]].append(r);tracking[k]={'key':r['key'],'side':k[1],'touch_ts_ms':r['touch_origin']['available_ts_ms'],'entry_ts_ms':r['entry_ts_ms'],
   'first_known_veto_ts_ms':r['veto_events'][0]['signal_ts_ms'] if r['veto_events'] else None,'frozen_objective':None,'first_objective_hit_ts_ms':None,
   'outcomes_diagnostic_only':{**r['analysis_only'],'removed_by_C114':k in removed}}
 for x in array_items(P/'observer/NATIVE_ORIGINS_ALL.json.gz'):
  for r in groups[x['symbol']]:
   t=tracking[tuple(r['key'])];ts=x['signal_ts_ms']
   if not(t['touch_ts_ms']<=ts<=t['entry_ts_ms']):continue
   z=x['native_inputs_asof'];side=t['side']
   if ts==t['touch_ts_ms']:t['frozen_objective']=float(z['prior20_high' if side==1 else 'prior20_low'])
   target=t['frozen_objective']
   if target is None:raise ValueError('MISSING_TOUCH_RECORD')
   extreme=z['row_ohlc']['high' if side==1 else 'low']
   if t['first_objective_hit_ts_ms'] is None and ((extreme>=target) if side==1 else (extreme<=target)):t['first_objective_hit_ts_ms']=ts
 allrows=list(tracking.values())
 if len(allrows)!=126 or any(t['frozen_objective'] is None for t in allrows):raise ValueError('INCOMPLETE126')
 for t in allrows:t['veto_and_objective_complete_by_entry']=t['first_known_veto_ts_ms'] is not None and t['first_objective_hit_ts_ms'] is not None
 result={'at_utc':datetime.now(timezone.utc).isoformat(),'classification':'SAVED_INCUMBENT_CAUSAL_STRUCTURE_DIAGNOSTIC_NOT_POLICY_PERFORMANCE','existing_trace_sha_verified':True,
  'trace_commit':'441fa935d1a7d6711ef8287ef0a6bf34054c6796','trace_pins':receipt['files'],'all126':allrows,
  'interpretation':'A saved original path can motivate an expiry hypothesis; only full chronology measures the effect, including new touches and replacement trades. Outcomes are analysis labels, never execution inputs.',
  'selected_policy_comparisons':0,'parameter_sweep':False,'orders':0}
 with (S/'DIAGNOSTIC.json').open('x') as f:json.dump(result,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
 for t in allrows:
  if t['first_known_veto_ts_ms'] is not None:print(json.dumps(t),flush=True)
 print('SAVED_TRACE126_DIAGNOSED_NO_PRICE_REPLAY',flush=True)
if __name__=='__main__':main()

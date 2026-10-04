"""Independent saved-only arithmetic and paired attribution; no model imports."""
from pathlib import Path
import argparse, hashlib, json, math, lzma, tempfile, sys
from collections import defaultdict

START=1789502400000;END=1791075300000
PARENT='scalp7_squeeze_panic_cost4_parent_utc30m_v2'
CHILD='scalp7_squeeze_panic_cost4_be1r_utc30m_v2'
def h(raw):return hashlib.sha256(raw).hexdigest()
def near(a,b):
 if a is None or b is None:assert a is b,(a,b)
 else:assert math.isfinite(float(a)) and math.isclose(a,b,abs_tol=1e-7,rel_tol=1e-10),(a,b)
def key(t):return (t['symbol'],t['side'],t['signal_ts_ms'])
def scored(rows):return [r for r in rows if START<=r['signal_ts_ms']<END and r['outcome_available_ts_ms']<END]
def metrics(rows,mult):
 rows=sorted(scored(rows),key=lambda r:(r['outcome_available_ts_ms'],r['exit_ts_ms'],r['symbol'],r['identity'],r['signal_ts_ms']))
 nets=[r['gross_bps']-mult*r['cost_bps'] for r in rows]
 gains=sum(x for x in nets if x>0);loss=-sum(x for x in nets if x<0)
 groups=defaultdict(float);streak=longest=0
 for r,n in zip(rows,nets):
  groups[r['outcome_available_ts_ms']]+=n
  streak=streak+1 if n<0 else 0;longest=max(longest,streak)
 nav=peak=dd=0
 for stamp in sorted(groups):nav+=groups[stamp];peak=max(peak,nav);dd=max(dd,peak-nav)
 return {'T':len(nets),'WR_pct':100*sum(n>0 for n in nets)/len(nets) if nets else None,
 'Gross_bps':sum(r['gross_bps'] for r in rows),'Cost_bps':sum(mult*r['cost_bps'] for r in rows),
 'Net_bps':sum(nets),'NetExp_bps_T':sum(nets)/len(nets) if nets else None,
 'PF':gains/loss if loss else None,'DD_bps':dd,'MaxLossStreak':longest}
def audit(root):
 raw=(root/'SUMMARY.json').read_bytes();summary=json.loads(raw)
 completion=json.loads((root/'COMPLETED.json').read_text());assert completion['summary_sha256']==h(raw)
 assert summary['economic_lane_executions']==2 and summary['shared_frame_builds']==1
 assert not summary['unused_oos_certified'] and not summary['g5_promotion'] and not summary['realtime_fill_certified']
 report={'summary_sha256':h(raw),'new_economic_calls':0,'market_replays':0,'lanes':{},'status':'PASS'}
 allrows={}
 for identity in (PARENT,CHILD):
  raw=(root/identity/'RESULT.json').read_bytes();result=json.loads(raw)
  done=json.loads((root/identity/'COMPLETED.json').read_text());assert done['result_sha256']==h(raw) and done['executions']==1
  rows=result['trades'];assert len(set(map(key,rows)))==len(rows)
  assert len(result['signals'])==len(rows)+len(result['unresolved'])+sum(result['rejections'].values())
  for t in rows:
   s=t['symbol'];near(t['side']*(t['exit_prices'][s]/t['entry_prices'][s]-1)*10000,t['gross_bps'])
   near(t['gross_bps']-t['cost_bps'],t['net_bps'])
   assert t['signal_available_ms']<t['entry_ts_ms']<=t['exit_ts_ms']<=t['outcome_available_ts_ms']
   assert t['entry_ts_ms']%60000==0 and t['fill_is_model_not_exchange'] and t['order_authority']=='BLOCKED'
  for event in result['events']:
   assert event['input_ready_ms']<event['order_effective_ms'] and event['order_effective_ms']%60000==0
  observed={}
  for mult in (1,2):
   recalc=metrics(rows,mult)
   for k,v in recalc.items():near(v,result['reference'+str(mult)+'x'][k])
   observed[str(mult)+'x']=recalc
  report['lanes'][identity]={'raw_complete':len(rows),'scored_complete':len(scored(rows)),'unresolved':len(result['unresolved']),
                            'signals':len(result['signals']),'rejections':result['rejections'],'events':len(result['events']),
                            'result_sha256':h(raw),'metrics':observed}
  allrows[identity]={key(t):t for t in scored(rows)}
 p=allrows[PARENT];c=allrows[CHILD];common=p.keys()&c.keys()
 pair={}
 for mult in (1,2):
  deltas={k:(c[k]['gross_bps']-mult*c[k]['cost_bps'])-(p[k]['gross_bps']-mult*p[k]['cost_bps']) for k in common}
  beneficial=[k for k in common if deltas[k]>1e-7];hurt=[k for k in common if deltas[k]<-1e-7]
  parent_positive=[k for k in common if p[k]['gross_bps']-mult*p[k]['cost_bps']>0]
  pair[str(mult)+'x']={'common_T':len(common),'improved_T':len(beneficial),'worsened_T':len(hurt),'unchanged_T':len(common)-len(beneficial)-len(hurt),
   'common_net_delta_bps':sum(deltas.values()),'parent_only_T':len(p.keys()-c.keys()),'child_only_T':len(c.keys()-p.keys()),
   'improvements_bps':sum(deltas[k] for k in beneficial),'deterioration_bps':sum(deltas[k] for k in hurt),
   'parent_winners_hurt_T':sum(k in hurt for k in parent_positive),
   'winner_to_loss_T':sum((c[k]['gross_bps']-mult*c[k]['cost_bps'])<=0 for k in parent_positive),
   'rows':[{'key':list(k),'parent_net_bps':p[k]['gross_bps']-mult*p[k]['cost_bps'],
            'child_net_bps':c[k]['gross_bps']-mult*c[k]['cost_bps'],'delta_bps':deltas[k],
            'parent_exit':p[k]['reason'],'child_exit':c[k]['reason']} for k in sorted(common)]}
 report['paired']=pair
 return report
def main():
 a=argparse.ArgumentParser(description=__doc__)
 a.add_argument('--bundle',type=Path,required=True)
 a.add_argument('--sha256',required=True)
 a.add_argument('--output',type=Path,required=True)
 args=a.parse_args();raw=args.bundle.read_bytes()
 if sys.flags.optimize:raise RuntimeError('AUDIT_REQUIRES_ASSERTIONS_ENABLED')
 assert h(raw)==args.sha256,'BUNDLE_HASH_MISMATCH'
 decoder=lzma.LZMADecompressor(memlimit=256*1024*1024)
 payload=decoder.decompress(raw,max_length=32*1024*1024+1)
 assert decoder.eof and not decoder.unused_data and len(payload)<=32*1024*1024,'BUNDLE_DECOMPRESSION_LIMIT'
 files=json.loads(payload)
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary)
  for name,text in files.items():
   dest=root/name
   assert not Path(name).is_absolute() and '..' not in Path(name).parts,'UNSAFE_BUNDLE_PATH'
   dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
  report=audit(root)
 with args.output.open('x') as f:json.dump(report,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
 print(json.dumps({k:v for k,v in report.items() if k!='paired'},indent=2))
if __name__=='__main__':main()

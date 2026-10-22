"""Independent saved-row audit, three-way comparison, append-only persistence."""
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict
import json,gzip,hashlib,math,sys
S=Path(__file__).resolve().parent;P=Path('/home/z/z/runtime/k126_c_veto_consume_20261022_v1')
sys.path.insert(0,str(S));import persist,owner_record

def sha(raw):return hashlib.sha256(raw).hexdigest()
def put(n,v):
 with (S/n).open('x') as f:json.dump(v,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
def metrics(rows,m):
 ordered=sorted(rows,key=lambda r:(r['outcome_available_ts_ms'],r['exit_ts_ms'],str(r['symbol']),str(r['identity']),r['signal_ts_ms']))
 ns=[float(r['gross_bps'])-m*float(r['cost_bps']) for r in ordered]
 cohorts=defaultdict(float);run=maxrun=0
 for r,n in zip(ordered,ns):
  cohorts[int(r['outcome_available_ts_ms'])]+=n
  run=run+1 if n<0 else 0;maxrun=max(maxrun,run)
 equity=peak=dd=0.
 for stamp in sorted(cohorts):
  equity+=cohorts[stamp];peak=max(peak,equity);dd=max(dd,peak-equity)
 worst=run_loss=0.
 for r in sorted(rows,key=lambda r:(r['outcome_available_ts_ms'],r['symbol'],r['entry_ts_ms'])):
  n=float(r['gross_bps'])-m*float(r['cost_bps'])
  if n<0:run_loss+=n;worst=min(worst,run_loss)
  else:run_loss=0.
 loss=-sum(n for n in ns if n<0)
 return {'Net_bps':sum(ns),'PF':sum(n for n in ns if n>0)/loss if loss else None,'T':len(ns),'DD_bps':dd,'MaxLossStreak':maxrun,'worst_loss_run_bps':worst,'wins':sum(n>0 for n in ns),'losses':sum(n<0 for n in ns),'DD_kind':'realized_equal_notional_trade_bps; simultaneous outcome cohorts netted together'}
def key(r):return (r['symbol'],int(r['side']),int(r['signal_ts_ms']))
def net(r,m=1):return float(r['gross_bps'])-m*float(r['cost_bps'])
def finish():
 summary=json.loads((S/'SUMMARY.json').read_bytes());raw=(S/'ROWS.json').read_bytes()
 if sha(raw)!=summary['rows_sha256']:raise ValueError('ROW_SHA_MISMATCH')
 rows=json.loads(raw)['trades'];old=json.loads(gzip.decompress((P/'incumbent/ROWS.json.gz').read_bytes()))['trades'];risk=json.loads((P/'ROWS.json').read_bytes())['trades']
 audits={}
 for label,rs,expected in [('retained126',old,summary['baseline']),('risk114',risk,summary['risk114']),('new',rows,summary['child'])]:
  audits[label]={}
  for m in [1,2]:
   got=metrics(rs,m)
   for k in ['Net_bps','PF','T','DD_bps','MaxLossStreak','worst_loss_run_bps']:
    if got[k] is None or not math.isclose(got[k],expected[f'cost{m}x'][k],abs_tol=1e-7,rel_tol=1e-10):raise ValueError('INDEPENDENT_MISMATCH:'+label+':'+k)
   audits[label][f'cost{m}x']=got
  if len({key(t) for t in rs})!=len(rs):raise ValueError('DUPLICATE_ROWS')
  for t in rs:
   if not math.isclose(net(t),float(t['net_bps']),abs_tol=1e-7):raise ValueError('COST_RECONCILIATION')
   if t['entry_ts_ms']<t['signal_ts_ms'] or t['exit_ts_ms']<t['entry_ts_ms']:raise ValueError('ROW_CLOCK')
 newmap={key(t):t for t in rows};winners=[t for t in old if net(t)>0]
 retention={'original_winners':len(winners),'same_entry_retained':sum(key(t) in newmap for t in winners),'same_entry_and_same_net':sum(key(t) in newmap and abs(net(t)-net(newmap[key(t)]))<1e-7 for t in winners),
  'missing':[{'key':list(key(t)),'old_net1x':net(t)} for t in winners if key(t) not in newmap]}
 put('ARITHMETIC_AUDIT.json',{'at_utc':datetime.now(timezone.utc).isoformat(),'independent_saved_row_arithmetic':True,'metrics':audits,'winner_retention':retention,'source_replays':0,'rows_sha256':sha(raw),'orders':0})
 with (S/'ROWS.json.gz').open('xb') as f:f.write(gzip.compress(raw,mtime=0))
 lines=['# K126 conditional veto expiry: actual single-comparison result','', 'Unit: equal-notional summed trade-bps, NOT account return. Used development data, NOT untouched OOS.','', '|Metric|Retained K126|C114 immediate reset|Conditional objective expiry|','|---|---:|---:|---:|']
 for level in ['cost1x','cost2x']:
  for k in ['T','Net_bps','PF','MaxLossStreak','worst_loss_run_bps','DD_bps']:
   lines.append(f"|{level} {k}|{summary['baseline'][level][k]}|{summary['risk114'][level][k]}|{summary['child'][level][k]}|")
 lines+=['', '## What changed', 'Only untraded setup lifetime after a known regime veto: preserve the setup until its touch-time prior20 objective has already been reached, then expire and require a new native EMA touch. Existing entries without a veto and accepted positions are not subjected to the new expiry. Original stop/exit/cost formulas remain fixed. The 20-bar reference is already in native code; it is a mechanical proxy, not a source-exact author rule.','', '## Actual economics and falsification', 'Complete chronology includes changed initial geometry, lost/replaced entries, occupancy and inherited carry cost. No loser deletion or winner whitelist. Both prior controls remain immutable.',f"Disposition versus retained126: {summary['disposition']}",'', 'Against saved114:', '```json',json.dumps(summary['against_C114'],indent=2),'```','', 'Formerly missed five winners:','```json',json.dumps(summary['previously_missed_five_winners'],indent=2),'```','', 'Original126 winner retention:','```json',json.dumps(retention,indent=2),'```','', 'All126 attribution:','```json',json.dumps(summary['attribution'],indent=2),'```','', 'Original worst8 entries:','```json',json.dumps(summary['original_worst8'],indent=2),'```','', '## Limitations', 'Repeated use of the same development sample can overfit. Independent untouched evaluation, account NAV/MTM and actual historical funding are not verified. No Shadow/Live replacement, no order or paid API. D risk allocation and the reserved Squeeze comparison remain untouched.']
 with (S/'RESULT.md').open('x') as f:f.write('\n'.join(lines)+'\n')
 names=['RESULT.md','SUMMARY.json','ROWS.json.gz','ARITHMETIC_AUDIT.json','SOURCE_AND_RULE.md','DIAGNOSTIC.json','EXECUTION_FREEZE.json','objective_lifetime.py','test_objective_lifetime.py','SYNTHETIC_TESTS.log','run_compare.py','audit_finish.py','CANDIDATE_STARTED.json','CANDIDATE_AUTHORITY.json','CANDIDATE_EXECUTION.log','PROCESS_EXIT.json']
 receipt=persist.save('completion',names)
 owner_record.update('TERMINAL',{'phase_detail':'ONE_CONDITIONAL_LIFETIME_COMPARISON_COMPLETE','new_policy_comparisons':1,'economic_started':True,'completed_at_utc':datetime.now(timezone.utc).isoformat(),'result_commit':receipt['commit'],'result_path':receipt['path']+'/RESULT.md','summary_sha256':sha((S/'SUMMARY.json').read_bytes()),'disposition':summary['disposition'],'retained_incumbent':'81a12c422ee9329996d2f6b983267d2def490d4b','retained_risk_alternative':'441fa935d1a7d6711ef8287ef0a6bf34054c6796','orders':0,'current_shadow_changes':0})
 print('COMPLETE_STORED',receipt['commit'],flush=True)
 print(json.dumps({'metrics':audits,'winner_retention':retention,'vs126':summary['attribution'],'vs114':summary['against_C114'],'restored5':summary['previously_missed_five_winners']},ensure_ascii=False),flush=True)
if __name__=='__main__':finish()

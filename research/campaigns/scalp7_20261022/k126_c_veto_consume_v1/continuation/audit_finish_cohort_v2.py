"""Saved-row arithmetic and append-only owner completion; never replay prices."""
from pathlib import Path
from datetime import datetime,timezone
import json,gzip,hashlib,math,sys
S=Path(__file__).resolve().parent
sys.path.insert(0,str(S));import persist,owner_record

def sha(b):return hashlib.sha256(b).hexdigest()
def save(n,v):
 with (S/n).open('x') as f:json.dump(v,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
def metrics(rows,m):
 ordered=sorted(rows,key=lambda r:(r['outcome_available_ts_ms'],r['exit_ts_ms'],str(r['symbol']),str(r['identity']),r['signal_ts_ms']))
 ns=[float(r['gross_bps'])-m*float(r['cost_bps']) for r in ordered]
 from collections import defaultdict
 cohorts=defaultdict(float);run=maxrun=0
 for r,n in zip(ordered,ns):
  cohorts[int(r['outcome_available_ts_ms'])]+=n
  run=run+1 if n<0 else 0;maxrun=max(maxrun,run)
 equity=peak=dd=0.
 for stamp in sorted(cohorts):
  equity+=cohorts[stamp];peak=max(peak,equity);dd=max(dd,peak-equity)
 # Existing support's monetary-streak tie convention is separate and retained.
 worst=run_loss=0.
 for r in sorted(rows,key=lambda r:(r['outcome_available_ts_ms'],r['symbol'],r['entry_ts_ms'])):
  n=float(r['gross_bps'])-m*float(r['cost_bps'])
  if n<0:run_loss+=n;worst=min(worst,run_loss)
  else:run_loss=0.
 loss=-sum(n for n in ns if n<0)
 return {'Net_bps':sum(ns),'PF':sum(n for n in ns if n>0)/loss if loss else None,'T':len(ns),'DD_bps':dd,'MaxLossStreak':maxrun,'worst_loss_run_bps':worst,'wins':sum(n>0 for n in ns),'DD_kind':'realized_equal_notional_trade_bps; simultaneous outcome cohorts netted together'}

def finish():
 findings=json.loads((S/'ORIGIN_FINDINGS.json').read_text())
 names=['CONSUMPTION_SCOPE.md','FREEZE.json','EXTRACT_RECEIPT.json','ORIGIN_FINDINGS.json','ORIGIN_ATTRIBUTION_ALL126.json','observer/OBSERVER_RECEIPT.json','observer/ENTRY_ORIGINS_ALL126.json','observer/NATIVE_ORIGINS_ALL.json.gz','observer/STARTED.json']
 result_path=S/'SUMMARY.json'
 if result_path.exists():
  summary=json.loads(result_path.read_text());raw=(S/'ROWS.json').read_bytes()
  if sha(raw)!=summary['rows_sha256']:raise ValueError('ROWS_SHA_CHANGED')
  rows=json.loads(raw)['trades'];audits={}
  for m in [1,2]:
   got=metrics(rows,m);expected=summary['child'][f'cost{m}x']
   for key in ['Net_bps','PF','T','DD_bps','MaxLossStreak','worst_loss_run_bps']:
    if got[key] is None or not math.isclose(got[key],expected[key],abs_tol=1e-7,rel_tol=1e-10):raise ValueError('ARITHMETIC_MISMATCH:'+key)
   audits[f'cost{m}x']=got
  for r in rows:
   if not math.isclose(float(r['gross_bps'])-float(r['cost_bps']),float(r['net_bps']),abs_tol=1e-8):raise ValueError('ROW_GROSS_COST_NET_MISMATCH')
   if r['entry_ts_ms']<r['signal_ts_ms'] or r['exit_ts_ms']<r['entry_ts_ms']:raise ValueError('NONCAUSAL_ROW')
  if any(rows[i]['outcome_available_ts_ms']>rows[i+1]['outcome_available_ts_ms'] for i in range(len(rows)-1)):raise ValueError('OUTCOME_ORDER_CHANGED')
  save('ARITHMETIC_AUDIT.json',{'at_utc':datetime.now(timezone.utc).isoformat(),'independent_saved_row_arithmetic':True,'metrics':audits,'orders':0,'rows_sha256':sha(raw),'economic_replays':0})
  with (S/'ROWS.json.gz').open('xb') as f:f.write(gzip.compress(raw,mtime=0))
  lines=['# Work C actually consumed — state-lifetime comparison','', 'Classification: ACTUAL_FIXED_SINGLE_CANDIDATE_USED_DEV. No account NAV, historical actual funding, independent OOS or promotion claim.','', 'C source commit: 77ce5616ed6e29c421592f319e7253b81dd79bdc. Incumbent:81a12c422ee9329996d2f6b983267d2def490d4b. Original K126 also retained.','', '|Metric|Incumbent|Candidate|','|---|---:|---:|']
  for level in ['cost1x','cost2x']:
   for metric in ['T','Net_bps','PF','MaxLossStreak','worst_loss_run_bps','DD_bps']:
    lines.append(f"|{level} {metric}|{summary['baseline'][level][metric]}|{summary['child'][level][metric]}|")
  lines += ['', 'Unit: equal-notional summed trade-bps, not account return.',f"Disposition: {summary['disposition']}",'', 'Origin attribution is before-entry evidence, not proof that a reset is profitable. Full chronology includes changed signals, occupancy, extra/missed trades, recovery winners and inherited reference 1x/2x costs with the same extra carry scenario.', '', 'Attribution:', '```json',json.dumps(summary['attribution'],indent=2),'```','Cohorts:', '```json',json.dumps(summary['cohorts'],indent=2),'```', '', 'Current Shadow changes0; orders0; D risk allocation not applied; reserved S comparison untouched.']
  consumed=1;disposition=summary['disposition'];names+=['SUMMARY.json','ROWS.json.gz','ARITHMETIC_AUDIT.json','CANDIDATE_STARTED.json','CANDIDATE_AUTHORITY.json','CANDIDATE_EXECUTION.log','run_compare.py','EXECUTION_FREEZE.json']
 else:
  if findings['candidate_source_question_supported_for_one_test']:raise ValueError('SUPPORTED_CANDIDATE_HAS_NO_RESULT')
  consumed=0;disposition='NO_TARGET_ANCESTRY_NO_CANDIDATE_REPLAY'
  lines=['# Work C exact-incumbent trace complete','', 'No new economic result. The observed target ancestry does not justify this exact C hypothesis for the worst8. Existing improved incumbent retained.','',json.dumps({k:findings[k] for k in ['all126','worst8','winners','large_winners']},indent=2)]
 with (S/'RESULT.md').open('x') as f:f.write('\n'.join(lines)+'\n')
 names+=['RESULT.md','audit_finish.py','audit_finish_cohort_v2.py','AUDIT_DEFINITION_REPAIR.json']
 stored=persist.save('completion',names)
 owner_record.update('TERMINAL',{'phase_detail':'C_ORIGIN_AND_SINGLE_RULE_CONSUMED','new_policy_comparisons':consumed,'economic_started':bool(consumed),'completed_at_utc':datetime.now(timezone.utc).isoformat(),'result_commit':stored['commit'],'result_path':stored['path']+'/RESULT.md','disposition':disposition,'retained_incumbent':'81a12c422ee9329996d2f6b983267d2def490d4b','orders':0,'current_shadow_changes':0})
 print((S/'RESULT.md').read_text(),flush=True)
if __name__=='__main__':finish()

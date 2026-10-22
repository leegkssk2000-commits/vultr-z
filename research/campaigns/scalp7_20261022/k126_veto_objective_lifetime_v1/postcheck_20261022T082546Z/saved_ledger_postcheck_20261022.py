"""Read-only saved-ledger sensitivity review. No policy replay, selection, or orders."""
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
import gzip, hashlib, json, math

S = Path(__file__).resolve().parent
C = Path('/home/z/z/runtime/k126_c_veto_consume_20261022_v1')
EXPECTED = {
 'K126': (C/'incumbent/ROWS.json.gz', '98eaa46994eb8c4e9d89e7e17bbb9a9cce97b86f6a3a727c11e8136da75a85f3'),
 'C114': (C/'ROWS.json', 'b039b46bf0239536f1120a35877699ca0b01a969ba3efc1f0e6a530805a52e9d'),
 'K117': (S/'ROWS.json', '7cba96a0627dbec42459f344a6e8e7dd70d97f87d71dfb573e10975153d7d0a7'),
}
SUMMARY_SHA = 'c2dfcdbec704fb7ab020c2d4d53293fd03dab5820672e0ac6fb4f9aa6094e5ae'
FREEZE_SHA = '918d00133ddb1b498bd93353a48f6e8a75f2da83b4062e3430db52b99b57ef0a'

def sha(raw):
 return hashlib.sha256(raw).hexdigest()
def net(r, m=1):
 return float(r['gross_bps']) - m * float(r['cost_bps'])
def key(r):
 return (r['symbol'], int(r['side']), int(r['signal_ts_ms']))
def metrics(rows, m):
 ordered = sorted(rows, key=lambda r: (r['outcome_available_ts_ms'], r['exit_ts_ms'], r['symbol'], r['identity'], r['signal_ts_ms']))
 ns = [net(r,m) for r in ordered]
 gains = math.fsum(n for n in ns if n>0); losses = -math.fsum(n for n in ns if n<0)
 by_time=defaultdict(float); run=longest=0
 for r,n in zip(ordered,ns):
  by_time[int(r['outcome_available_ts_ms'])] += n
  run=run+1 if n<0 else 0; longest=max(longest,run)
 eq=peak=dd=0.
 for stamp in sorted(by_time):
  eq+=by_time[stamp]; peak=max(peak,eq); dd=max(dd,peak-eq)
 run_loss=worst=0.
 for r in sorted(rows,key=lambda r:(r['outcome_available_ts_ms'],r['symbol'],r['entry_ts_ms'])):
  n=net(r,m)
  if n<0: run_loss+=n; worst=min(worst,run_loss)
  else: run_loss=0.
 return {'T':len(rows),'Net_bps':math.fsum(ns),'PF':gains/losses if losses else None,
 'WR_pct':100*sum(n>0 for n in ns)/len(ns) if ns else None,
 'MaxLossStreak':longest,'DD_bps':dd,'worst_loss_run_bps':worst}

def main():
 summary_raw=(S/'SUMMARY.json').read_bytes(); freeze_raw=(S/'EXECUTION_FREEZE.json').read_bytes()
 if sha(summary_raw)!=SUMMARY_SHA or sha(freeze_raw)!=FREEZE_SHA:
  raise ValueError('FROZEN_RESULT_CHANGED')
 summary=json.loads(summary_raw); freeze=json.loads(freeze_raw)
 for path,pin in freeze['code_sha256'].items():
  if sha(Path(path).read_bytes())!=pin: raise ValueError('FROZEN_CODE_CHANGED:'+path)
 datasets={}; input_proofs={}
 for label,(path,pin) in EXPECTED.items():
  raw=path.read_bytes(); payload=gzip.decompress(raw) if path.suffix=='.gz' else raw
  if sha(payload)!=pin: raise ValueError('LEDGER_HASH_CHANGED:'+label)
  obj=json.loads(payload); rows=obj['trades']
  if obj.get('unresolved') or obj.get('boundary_excluded'): raise ValueError('UNRESOLVED_INPUT:'+label)
  if len({key(r) for r in rows})!=len(rows):raise ValueError('DUPLICATE_TRADE:'+label)
  for r in rows:
   if not r['signal_ts_ms']<=r['entry_ts_ms']<=r['exit_ts_ms']<=r['outcome_available_ts_ms']: raise ValueError('TRADE_TIME_INVALID')
   if r['partition']!='rolling':raise ValueError('OUTSIDE_USED_DEV')
   if not math.isfinite(net(r)) or not math.isfinite(float(r['cost_bps'])) or r['cost_bps']<=0:raise ValueError('INVALID_ECONOMICS')
  expected=summary[{'K126':'baseline','C114':'risk114','K117':'child'}[label]]
  for m in [1,2]:
   got=metrics(rows,m)
   for field in got:
    if not math.isclose(got[field],expected[f'cost{m}x'][field],abs_tol=1e-7,rel_tol=1e-10):raise ValueError('ARITHMETIC_MISMATCH:'+label+':'+field)
  datasets[label]=rows
  input_proofs[label]={'path':str(path),'stored_sha256':sha(raw),'uncompressed_sha256':pin,'rows':len(rows)}
 windows=sorted({r['window_label'] for rs in datasets.values() for r in rs},key=lambda w:int(w.rsplit('_',1)[1]))
 symbols=sorted({r['symbol'] for rs in datasets.values() for r in rs})
 if len(windows)!=9 or len(symbols)!=6:raise ValueError('COMPARISON_SCOPE_CHANGED')
 result={
 'at_utc':datetime.now(timezone.utc).isoformat(),
 'classification':'SAVED_LEDGER_SENSITIVITY_NOT_NEW_POLICY_OR_INDEPENDENT_VALIDATION',
 'source_result_commit':'8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8',
 'candidate':summary['candidate'],'summary_sha256':SUMMARY_SHA,'execution_freeze_sha256':FREEZE_SHA,
 'inputs':input_proofs,'window_count':len(windows),'symbol_count':len(symbols),'used_days':245,
 'unit':'equal-notional summed trade-bps; not account NAV/MTM',
 'source_replays':0,'new_policy_comparisons':0,'market_api_calls':0,'orders':0,'shadow_changes':0,
 'parameter_or_symbol_selection':False,'independent_OOS':False,'historical_actual_funding_verified':False,
 'variants':{},'paired_window_deltas':{},'paired_symbol_deltas':{},
 'interpretation':'Leave-one-out figures subtract already recorded trades only. They are sensitivity diagnostics, not a rerun with a removed market or independent OOS.',
 }
 for label,rows in datasets.items():
  out={'metrics':{f'cost{m}x':metrics(rows,m) for m in [1,2]},'windows':{},'symbols':{},'sides':{},'sensitivity':{}}
  for field,vals,dest in [('window_label',windows,'windows'),('symbol',symbols,'symbols'),('side',[-1,1],'sides')]:
   for val in vals:out[dest][str(val)]={f'cost{m}x':metrics([r for r in rows if r[field]==val],m) for m in [1,2]}
  for m in [1,2]:
   level=f'cost{m}x'; largest=max(rows,key=lambda r:net(r,m))
   best_window=max(windows,key=lambda w:out['windows'][w][level]['Net_bps'])
   out['sensitivity'][level]={
    'exclude_largest_winner':{'excluded_key':list(key(largest)),'excluded_net':net(largest,m),'remaining':metrics([r for r in rows if key(r)!=key(largest)],m)},
    'best_window':best_window,
    'exclude_best_window':metrics([r for r in rows if r['window_label']!=best_window],m),
    'exclude_each_window':{w:metrics([r for r in rows if r['window_label']!=w],m) for w in windows},
    'exclude_each_symbol':{s:metrics([r for r in rows if r['symbol']!=s],m) for s in symbols},
    'positive_windows':sum(out['windows'][w][level]['Net_bps']>0 for w in windows),
    'negative_windows':sum(out['windows'][w][level]['Net_bps']<0 for w in windows),
    'all_leave_one_window_net_positive':all(math.fsum(net(r,m) for r in rows if r['window_label']!=w)>0 for w in windows),
    'all_leave_one_symbol_net_positive':all(math.fsum(net(r,m) for r in rows if r['symbol']!=s)>0 for s in symbols),
   }
  result['variants'][label]=out
 for field,values,dest in [('window_label',windows,'paired_window_deltas'),('symbol',symbols,'paired_symbol_deltas')]:
  for val in values:
   result[dest][val]={f'cost{m}x':math.fsum(net(r,m) for r in datasets['K117'] if r[field]==val)-math.fsum(net(r,m) for r in datasets['K126'] if r[field]==val) for m in [1,2]}
 old={key(r):r for r in datasets['K126']}; new={key(r):r for r in datasets['K117']}
 winners=[r for r in old.values() if net(r)>0]; large=[r for r in winners if r['mfe_R']>=2]
 result['winner_retention']={'original_winners':len(winners),'retained_same_entry_and_net':sum(key(r) in new and math.isclose(net(r),net(new[key(r)]),abs_tol=1e-8) for r in winners),
 'large_winners':len(large),'large_same_entry_and_net':sum(key(r) in new and math.isclose(net(r),net(new[key(r)]),abs_tol=1e-8) for r in large),
 'removed_losses':sum(net(r)<0 for k,r in old.items() if k not in new),'removed_winners':sum(net(r)>0 for k,r in old.items() if k not in new)}
 result['objective_event_time_check']={'events':len(json.loads((S/'ROWS.json').read_bytes()).get('objective_expiry_events',[]))}
 for e in json.loads((S/'ROWS.json').read_bytes()).get('objective_expiry_events',[]):
  if max(e['touch_ts_ms'],e['first_objective_hit_ts_ms'],e['first_known_veto_ts_ms'])>e['expired_ts_ms']:raise ValueError('NONCAUSAL_EXPIRY_EVENT')
 result['objective_event_time_check']['all_evidence_known_no_later_than_expiry']=True
 result['next_scope']={
  'preserve':'Freeze K117 as a development challenger; retain immutable K126/C114. No current strategy, Shadow, risk budget or promotion change.',
  'do_not':'Do not retune or manufacture a numeric filter for the remaining loss windows. Do not relabel used historical windows as untouched OOS.',
  'next_unfinished':'Identify an existing authorized untouched/prospective validation contract and inputs for this exact frozen identity. Reuse existing engine; no new platform, paid API, live orders, or unapproved replacement of B.',
  'parallel_independent':'Existing reserved Squeeze comparison can proceed separately under the same single economic owner after checking its current receipt and authority; no budget transfer from S to K.',
 }
 with (S/'SAVED_LEDGER_POSTCHECK_20261022.json').open('x') as f:json.dump(result,f,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
 lines=['# Frozen K117: saved-ledger sensitivity review','',
 'Classification: SAVED_LEDGER_SENSITIVITY_NOT_NEW_POLICY_OR_INDEPENDENT_VALIDATION.',
 'All values below use the completed 245-day development ledger. No new price replay, orders, Shadow changes or parameter/symbol selection.',
 'Source economic result: 8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8; K126 and C114 are preserved.',
 'Unit: equal-notional summed trade-bps, not account return. Realized DD nets simultaneous outcomes; no account MTM drawdown claim.','',
 '|Metric|K126|C114|Frozen K117|','|---|---:|---:|---:|']
 for m in [1,2]:
  level=f'cost{m}x'
  for met in ['T','Net_bps','PF','WR_pct','MaxLossStreak','worst_loss_run_bps','DD_bps']:
   lines.append('|'+level+' '+met+'|'+'|'.join(str(result['variants'][x]['metrics'][level][met]) for x in ['K126','C114','K117'])+'|')
 lines+=['','## Concentration sensitivity; subtraction only, not independent replays',
 '|Diagnostic|K126 net2x|C114 net2x|K117 net2x|','|---|---:|---:|---:|']
 for title,path in [('Exclude largest winner',('exclude_largest_winner','remaining')),('Exclude best original rolling window',('exclude_best_window',))]:
  vals=[]
  for label in ['K126','C114','K117']:
   value=result['variants'][label]['sensitivity']['cost2x']
   for part in path:value=value[part]
   vals.append(str(value['Net_bps']))
  lines.append('|'+title+'|'+'|'.join(vals)+'|')
 newtest=result['variants']['K117']['sensitivity']['cost2x']
 lines+=['',f"K117 positive/negative cost2x windows: {newtest['positive_windows']}/{newtest['negative_windows']} of9. The number of profitable windows has NOT improved.",
 'Every leave-one-window and leave-one-symbol cost2x remainder is positive. This does not show every window or every symbol is individually profitable.',
 'Compared with K126, five windows improve and four are unchanged at both costs. This is used-data attribution, not an unseen-period test.',
 'Remaining cost2x loss windows: rolling2, rolling4, rolling6, rolling7, rolling9. BTC component is also negative at cost2x. No losing period or symbol is removed from the strategy.',
 'Completed-trade rate: 117/245 = 0.477551 per day, below the eventual combined3-4/day objective. This comparison does not validate a common-account portfolio.','',
 '## Winner preservation',json.dumps(result['winner_retention'],ensure_ascii=False,sort_keys=True),
 'All34 original large winners retain their entry and net. Of69 original winners,68 are unchanged; one38.9714153578 trade-bps ordinary winner remains excluded.',
 '## Next execution boundary',json.dumps(result['next_scope'],ensure_ascii=False,indent=2),
 '## Integrity',
 'Three source-ledger hashes and all frozen code hashes checked; independent arithmetic agrees with stored metrics. Event-time checks cover215 objective-expiry records.',
 'No new experiment, no account NAV or historical funding claim, no fresh/OOS PASS.']
 with (S/'SAVED_LEDGER_POSTCHECK_20261022.md').open('x') as f:f.write('\n'.join(lines)+'\n')
 print('SAVED_POSTCHECK',json.dumps({'input_hashes_match':True,'cost2x_exclude_best_window':newtest['exclude_best_window']['Net_bps'],'cost2x_exclude_top_trade':newtest['exclude_largest_winner']['remaining']['Net_bps'],'positive_windows':newtest['positive_windows'],'negative_windows':newtest['negative_windows'],'winner_retention':result['winner_retention'],'new_policy_runs':0}),flush=True)
if __name__=='__main__': main()

"""Read-only causal anatomy of saved K126 trades. No strategy replay/selection."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter, defaultdict
import json, gzip, hashlib, io, math
import pandas as pd
S=Path('/home/z/z/runtime/k126_worst8_parallel_20261021')
BASE=Path('/home/z/z/runtime/k126_pullback_structure_failure_20261021_v1')
CACHE=Path('/home/z/z/runtime/k_winner_handoff_20261021T1230Z')
def sha(b):return hashlib.sha256(b).hexdigest()
def iso(t):return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()
def key(t):return (t['symbol'],int(t['side']),int(t['signal_ts_ms']))
def enc(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def put(n,v):
 b=enc(v)
 with (S/n).open('xb') as f:f.write(b)
 return sha(b)
def main():
 S.mkdir(exist_ok=False)
 raw=(BASE/'SUMMARY.json').read_bytes();assert sha(raw)=='a69e1cce4b5dffe004d49820ced626962795952f2e7b06226eb71ad77b8f7812'
 summ=json.loads(raw);rawrows=(BASE/'ROWS.json').read_bytes();assert sha(rawrows)==summ['rows_sha256']
 trades=json.loads(rawrows)['trades'];assert len(trades)==126 and len({key(t) for t in trades})==126
 keys={tuple(k) for k in summ['baseline']['cost1x']['longest_loss_run_keys']}
 pairs=json.loads((BASE/'PAIRED_ALL126.json').read_bytes())['paired'];pairmap={tuple(p['key']):p for p in pairs}
 meta=json.loads((CACHE/'INPUT_CACHE.json').read_bytes());frames={};input_pins={}
 for sym,rec in meta['symbols'].items():
  b=(CACHE/rec['path']).read_bytes();assert sha(b)==rec['sha256']
  f=pd.read_csv(io.BytesIO(b),compression='gzip',float_precision='round_trip');assert len(f)==17519
  assert not f.open_ts_ms.duplicated().any() and f.open_ts_ms.is_monotonic_increasing
  frames[sym]=f;input_pins[sym]=dict(path=str(CACHE/rec['path']),sha256=sha(b),rows=len(f))
 allrows=[];paths=[]
 for t in sorted(trades,key=lambda v:(v['entry_ts_ms'],v['symbol'])):
  sym=t['symbol'];side=t['side'];sig=t['signal'];entry=t['entry_prices'][sym];atr=sig['meta']['atr_price'];stop=sig['stop_price']
  if side*(entry-stop)<=0:stop=entry-side*sig['meta']['fallback_stop_atr_mult']*atr
  risk=side*(entry-stop);assert risk>0 and atr>0
  f=frames[sym];prior=f[(f.available_ts_ms<=t['entry_ts_ms'])&(f.segment_id==sig['segment_id'])]
  field='low' if side==1 else 'high';reference=sig['invalidation_price']
  matches=prior[(prior[field]-reference).abs()<=max(abs(reference),1.)*1e-12]
  lastmatch=int(matches.iloc[-1].available_ts_ms) if not matches.empty else None
  # Strictly earlier outcomes only. Same-time order needs the native event contract.
  known=[u for u in trades if u['outcome_available_ts_ms']<t['entry_ts_ms']]
  known=sorted(known,key=lambda u:(u['outcome_available_ts_ms'],u['symbol'],u['entry_ts_ms']))
  active=[u for u in trades if u['side']==side and u['entry_ts_ms']<=t['entry_ts_ms']<u['outcome_available_ts_ms']]
  current={'key':list(key(t)),'entry_utc':iso(t['entry_ts_ms']),'exit_utc':iso(t['exit_ts_ms']),'outcome_known_utc':iso(t['outcome_available_ts_ms']),
    'entry_ts_ms':t['entry_ts_ms'],'outcome_available_ts_ms':t['outcome_available_ts_ms'],'side':side,'symbol':sym,
    'entry_price':entry,'initial_stop':stop,'invalidation_price':reference,'frozen_ATR_price':atr,
    'initial_risk_price':risk,'initial_risk_ATR':risk/atr,'initial_stop_distance_pct':risk/entry*100,
    'structure_stop_gap_ATR':abs(stop-reference)/atr,'latest_matching_extreme_available_ts_ms':lastmatch,
    'matching_extreme_age_min_NOT_STATE_TOUCH_AGE':(t['entry_ts_ms']-lastmatch)/60000 if lastmatch is not None else None,
    'same_side_open_keys_at_entry':[list(key(u)) for u in active],
    'known_previous_closed_keys':[list(key(u)) for u in known[-8:]],
    'known_previous_closed_net':[u['net_bps'] for u in known[-8:]],
    'same_timestamp_outcomes_excluded_count':sum(u['outcome_available_ts_ms']==t['entry_ts_ms'] for u in trades),
    'outcome_labels_NOT_FEATURES':{'reason':t['reason'],'net1x':t['net_bps'],'net2x':t['gross_bps']-2*t['cost_bps'],'gross':t['gross_bps'],'final_mfe_R':t['mfe_R'],'worst8_member':key(t) in keys},
    'native_structure_exit_observed_before_old_exit':pairmap[key(t)]['first_failure'] is not None}
  allrows.append(current)
  # Fixed all126 coverage, not a loss-only path dataset. All labels stay in allrows.
  held=f[(f.open_ts_ms>=t['signal_open_ts_ms'])&(f.open_ts_ms<=t['exit_ts_ms'])]
  paths.append({'trade_key':list(key(t)),'raw_ohlc_includes_terminal_bar_not_known_before_its_close':True,'bars':json.loads(held.to_json(orient='records',double_precision=15)),
    'WARNING':'Raw bars are NOT a newly simulated fill or dynamic-stop trace. Stop-hit bar extrema must not be used before the stop. Outcome labels are separate.'})
 worst=[r for r in allrows if tuple(r['key']) in keys];assert len(worst)==8
 worstsum=sum(r['outcome_labels_NOT_FEATURES']['net1x'] for r in worst);assert math.isclose(worstsum,-1128.2251166863311,abs_tol=1e-8)
 scratch=[r for r in worst if r['outcome_labels_NOT_FEATURES']['reason']=='HG_FROZEN_5BAR_MFE_SCRATCH']
 stops=[r for r in worst if r['outcome_labels_NOT_FEATURES']['reason']=='STOP_FIRST']
 overlap_start=max(r['entry_ts_ms'] for r in scratch);overlap_end=min(r['outcome_available_ts_ms'] for r in scratch)
 assert len(scratch)==4 and overlap_start<overlap_end
 latest_entry=max(r['entry_ts_ms'] for r in scratch);first_outcome=min(r['outcome_available_ts_ms'] for r in scratch)
 by_time=defaultdict(list)
 for t in trades:by_time[t['outcome_available_ts_ms']].append(t)
 mixed=[{'utc':iso(st),'keys':[list(key(t)) for t in rr],'net1x':[t['net_bps'] for t in rr]} for st,rr in by_time.items() if min(t['net_bps'] for t in rr)<0<max(t['net_bps'] for t in rr)]
 cohort={}
 for name,pred in [('all126',lambda r:True),('loss57',lambda r:r['outcome_labels_NOT_FEATURES']['net1x']<0),('winner69',lambda r:r['outcome_labels_NOT_FEATURES']['net1x']>0)]:
  rr=[r for r in allrows if pred(r)];vals=pd.Series([r['initial_risk_ATR'] for r in rr])
  cohort[name]={'count':len(rr),'risk_ATR_min':float(vals.min()),'risk_ATR_median':float(vals.median()),'risk_ATR_max':float(vals.max())}
 result={'at_utc':datetime.now(timezone.utc).isoformat(),'classification':'SAVED_LEDGER_PLUS_CAUSAL_RAW_PATH_DIAGNOSIS_NOT_NEW_ECONOMIC_RESULT',
  'baseline_commit':'81a12c422ee9329996d2f6b983267d2def490d4b','summary_sha256':sha(raw),'rows_sha256':sha(rawrows),'market_input_pins':input_pins,
  'worst8_net_trade_bps':worstsum,'worst8_start_utc':min(r['entry_utc'] for r in worst),'worst8_last_outcome_utc':max(r['outcome_known_utc'] for r in worst),
  'stop4_net':sum(r['outcome_labels_NOT_FEATURES']['net1x'] for r in stops),'scratch4_net':sum(r['outcome_labels_NOT_FEATURES']['net1x'] for r in scratch),
  'scratch4_loss_share_pct':sum(r['outcome_labels_NOT_FEATURES']['net1x'] for r in scratch)/worstsum*100,
  'scratch4_concurrent_interval_utc':[iso(overlap_start),iso(overlap_end)],'scratch4_all_entered_before_any_own_loss_known':latest_entry<first_outcome,
  'scratch4_risk_ATR_range':[min(r['initial_risk_ATR'] for r in scratch),max(r['initial_risk_ATR'] for r in scratch)],
  'worst8_no_actionable_whole_structure_exit':all(not r['native_structure_exit_observed_before_old_exit'] for r in worst),
  'worst8':worst,'all126_entry_geometry_by_outcome_DIAGNOSTIC_ONLY':cohort,'mixed_sign_same_outcome_timestamps':mixed,
  'new_strategy_FULL':0,'new_policy_economic_comparisons':0,'orders':0,'current_shadow_changes':0,
  'interpretation':['STOP_FIRST and SCRATCH are outcome labels, not proven causal filters.',
    'The latest close-through-whole-structure rule had no actionable pre-exit event in any of the worst8.',
    'Four scratch losses overlap. Waiting for their realized losses cannot retroactively prevent their earlier entries.',
    'Large initial risk/ATR changes the scale of MFE_R and the existing scratch hurdle; provenance/stale-state is an open question, not a proven bug.',
    'Never turn this observed risk_ATR range, outcome labels or dated cohort into a numerical filter.',
    'Matching raw extreme age is not exact native touch/state origin. Native state tracing is still needed.',
    'The 8-loss row run depends on native tie ordering; preserve it and report decision batches separately, never relabel it away.']}
 put('ANATOMY.json',result);put('ENTRY_GEOMETRY_ALL126.json',allrows)
 with (S/'RAW_PATHS_ALL126.json.gz').open('xb') as f:f.write(gzip.compress(enc(paths),mtime=0))
 lines=['# K126 worst8: execution-time anatomy, no new economics','', 'Classification: '+result['classification'],
  'Source: '+result['baseline_commit'], 'All126 included; outcomes are diagnostic labels only.','',
  f"Worst8 total: {worstsum:.8f} trade-bps; STOP4 {result['stop4_net']:.8f}; SCRATCH4 {result['scratch4_net']:.8f}.",
  f"Four scratch positions overlap {iso(overlap_start)} to {iso(overlap_end)}. Loss share {result['scratch4_loss_share_pct']:.5f}%.",
  'All four entries predate the first realized loss among them. This refutes a retrospective claim that a post-loss cooldown would prevent all four.',
  'Whole-pullback close exit did not precede original exits for any of the eight.','',
  '|Entry UTC|Symbol/side|Reason|Net trade-bps|Initial risk/ATR|Raw matching extreme age min (not exact state age)|',
  '|---|---|---|---:|---:|---:|']
 for r in worst:lines.append(f"|{r['entry_utc']}|{r['symbol']}/{r['side']}|{r['outcome_labels_NOT_FEATURES']['reason']}|{r['outcome_labels_NOT_FEATURES']['net1x']:.8f}|{r['initial_risk_ATR']:.5f}|{r['matching_extreme_age_min_NOT_STATE_TOUCH_AGE']}|")
 lines+=['','## What to implement next, separately','C: exact state/level provenance and pre-exit observability; a single justified adapter, no parameter sweep.','D: causal same-direction exposure and same-time outcome audit, with complete winning counterexamples and unit/SSOT binding.','A remains the only economic owner. C/D must not run competing FULL.','',*result['interpretation'],'','No new profit increase, loss reduction, live performance or independentOOS is claimed by this diagnostic.']
 with (S/'ANATOMY.md').open('x') as f:f.write('\n'.join(lines)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ['worst8','market_input_pins','mixed_sign_same_outcome_timestamps']},ensure_ascii=False,indent=2))
 print('EVIDENCE_DIR',str(S))
if __name__=='__main__':main()

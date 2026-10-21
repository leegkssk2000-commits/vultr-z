"""Saved observer receipt only; join exact native ancestry, never create a policy result."""
from pathlib import Path
from collections import defaultdict,Counter
from datetime import datetime,timezone
import json,gzip,hashlib
S=Path(__file__).resolve().parent;O=S/'observer'
KNOWN={'TREND_COHERENT','COMPRESSION','VOL_EXPANSION_MIXED','RANGE_MIXED'}
def sha(b):return hashlib.sha256(b).hexdigest()
def put(n,v):
 with (S/n).open('x') as f:json.dump(v,f,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def main():
 receipt=json.loads((O/'OBSERVER_RECEIPT.json').read_bytes())
 for n,p in receipt['files'].items():
  if sha((O/n).read_bytes())!=p['sha256']:raise ValueError('OBSERVER_OUTPUT_PIN_CHANGED:'+n)
 entries=json.loads((O/'ENTRY_ORIGINS_ALL126.json').read_bytes())
 observations=json.loads(gzip.decompress((O/'NATIVE_ORIGINS_ALL.json.gz').read_bytes()))
 saved=json.loads(gzip.decompress((S/'incumbent/ROWS.json.gz').read_bytes()))
 summary=json.loads((S/'incumbent/SUMMARY.json').read_bytes())
 rows={ (r['symbol'],int(r['side']),int(r['signal_ts_ms'])):r for r in saved['trades'] }
 worst={tuple(k) for k in summary['child']['cost1x']['longest_loss_run_keys']}
 vetoes=defaultdict(list)
 for r in observations:
  origin=r['origin_after_policy']['touch'];ad=r['admission']
  if origin and ad['state']=='REGIME_INELIGIBLE_NO_RESET' and ad['reason'] in KNOWN:
   event={'signal_ts_ms':r['signal_ts_ms'],'regime':ad['reason'],'native_event':r['native_event_observed'],'touch_origin':origin,'policy_state_after':r['policy_state_after'],'bar_clock':r['bar_clock']}
   vetoes[(r['symbol'],r['segment_id'],origin['available_ts_ms'])].append(event)
 joined=[]
 for e in entries:
  key=tuple(e['trade_key']);r=rows[key];rec=e['origin_observation'];origin=rec['origin_after_policy']['touch']
  known=origin is not None
  events=[] if not known else [v for v in vetoes[(rec['symbol'],rec['segment_id'],origin['available_ts_ms'])] if v['signal_ts_ms']<rec['signal_ts_ms']]
  net=float(r['gross_bps'])-float(r['cost_bps'])
  joined.append({'key':list(key),'entry_ts_ms':r['entry_ts_ms'],'known_origin':known,'touch_origin':origin,'known_ineligible_veto_ancestry':bool(events),'veto_events':events,
   'touch_age_minutes_at_entry':None if not known else (r['entry_ts_ms']-origin['available_ts_ms'])/60000,
   'weak_bars_retained':rec['features_asof']['weak_bars_retained_since_observed_touch'],
   'reference_origin':rec['origin_after_policy']['pull_low' if r['side']==1 else 'pull_high'],
   'initial_risk_over_atr':e['initial_risk_over_signal_atr'],
   'analysis_only':{'original_worst8':(r['symbol'],r['side'],r['entry_ts_ms']) in worst,'net1x':net,'net2x':float(r['gross_bps'])-2*float(r['cost_bps']),'reason':r['reason'],'large_winner':net>0 and r['mfe_R']>=2},
   'outcome_labels_not_decision_features':True})
 if len(joined)!=126 or len({tuple(j['key']) for j in joined})!=126:raise ValueError('ALL126_JOIN_INCOMPLETE')
 target=[j for j in joined if j['analysis_only']['original_worst8']]
 if len(target)!=8:raise ValueError('WORST8_JOIN_INCOMPLETE')
 def group(a):return {'T':len(a),'known_origins':sum(x['known_origin'] for x in a),'known_veto_ancestry_T':sum(x['known_ineligible_veto_ancestry'] for x in a),'net1x_diagnostic_not_effect':sum(x['analysis_only']['net1x'] for x in a)}
 eligible=all(x['known_origin'] for x in target) and any(x['known_ineligible_veto_ancestry'] for x in target)
 result={'at_utc':datetime.now(timezone.utc).isoformat(),'classification':'ACTUAL_INCUMBENT_NATIVE_STATE_ATTRIBUTION_NOT_ECONOMIC_IMPROVEMENT',
  'raw126_exact':receipt['raw126_exact'],'incumbent':'81a12c422ee9329996d2f6b983267d2def490d4b','source_commit':'77ce5616ed6e29c421592f319e7253b81dd79bdc',
  'all126':group(joined),'worst8':group(target),'losses':group([j for j in joined if j['analysis_only']['net1x']<0]),
  'winners':group([j for j in joined if j['analysis_only']['net1x']>0]),'large_winners':group([j for j in joined if j['analysis_only']['large_winner']]),
  'target_details':target,'candidate_source_question_supported_for_one_test':eligible,
  'interpretation':'Ancestry proves occurrence, not that resetting improves economics. Include every winning counterexample in full chronology. Absence refutes this exact explanation for target paths.',
  'new_policy_comparisons':0,'orders':0,'shadow_changes':0}
 put('ORIGIN_ATTRIBUTION_ALL126.json',joined);put('ORIGIN_FINDINGS.json',result)
 print('ORIGIN_FINDINGS',json.dumps({k:v for k,v in result.items() if k!='target_details'},ensure_ascii=False),flush=True)
 for j in target:print('WORST8_ORIGIN',json.dumps(j,ensure_ascii=False),flush=True)
if __name__=='__main__':main()

"""Chronological occupancy validation of the SAME frozen 2R/25->50bar hypothesis.
No parameter search, new source API, orders, runtime deployment or S slot usage.
"""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
import fcntl, hashlib, json, os, sys
import pandas as pd
STAGE=Path(__file__).resolve().parent
REPO=Path('/home/z/worktrees/zel-work-b-retry-6f7a4217-20261020')
SOURCE=Path('/home/z/z/runtime/economic7_campaign_20260915')
sys.path[:0]=[str(REPO),str(STAGE)]
from backend.research.rebuild import scalp7_source_data_v2 as source
from backend.research.rebuild import scalp7_rolling_context_v2 as context
from backend.research.rebuild import scalp7_execution_v2 as execution
from backend.research.rebuild import scalp7_positive_lanes_v2 as positive
from ops import scalp7_keltner_fresh_touch_successor_v1 as k
import winner_timeout_comparison as paired
import run_paired as accounting
from exact_saved_csv_source import EXPECTED
START,END,RAWSTART,TF=1768262400000,1789430400000,1757894400000,1800000
def now():return datetime.now(timezone.utc).isoformat()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def blob(value):return (json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
def save(name,value):
 raw=blob(value)
 with (STAGE/name).open('xb') as h:h.write(raw)
 return sha(raw)
def key(t):return (str(t['symbol']),int(t['side']),int(t['signal_ts_ms']))
def full_frames():
 for rel,pin in source.MANIFEST_HASHES.items():
  if sha((SOURCE/rel).read_bytes())!=pin:raise ValueError('PINNED_MANIFEST_CHANGED:'+rel)
 bound={};evidence={}
 for symbol in source.SYMBOLS:
  parts=[];receipts=[];base=SOURCE/'canonical_12m'
  for p in sorted((base/'1m'/symbol).glob('*.csv.gz')):
   a,b=map(int,p.name.replace('.csv.gz','').split('_'))
   if not (b>RAWSTART and a<START):continue
   receipt_path=base/'daily_receipts'/symbol/(p.name.replace('.csv.gz','.json'))
   r=json.loads(receipt_path.read_bytes());u=dict(r);internal=u.pop('receipt_sha256')
   if sha(source.json_bytes(u))!=internal:raise ValueError('PREFIX_DAILY_RECEIPT_INVALID:'+p.name)
   artifact=next(v for v in r['artifacts'] if v['timeframe_minutes']==1)
   raw=p.read_bytes()
   if artifact['path']!=str(p.relative_to(base)) or sha(raw)!=artifact['sha256']:raise ValueError('PREFIX_DAILY_ARTIFACT_CHANGED')
   frame=pd.read_csv(p,float_precision='round_trip')
   if len(frame)!=int(artifact['row_count']):raise ValueError('PREFIX_SOURCE_COUNT')
   parts.append(frame[(frame.timestamp_ms>=RAWSTART)&(frame.timestamp_ms<START)])
   receipts.append({'path':str(p.relative_to(SOURCE)),'sha256':sha(raw),'daily_receipt_sha256':internal})
  minutes=pd.concat(parts,ignore_index=True).sort_values('timestamp_ms').reset_index(drop=True)
  prefix=source.aggregate_minutes(minutes,30)
  tail=pd.read_csv(STAGE/('BOUND_'+symbol+'_30m.csv.gz'),float_precision='round_trip')
  if sha(tail.to_csv(index=False).encode())!=EXPECTED[symbol]:raise ValueError('BOUND_CACHE_CHANGED')
  if int(prefix.iloc[0].open_ts_ms)!=RAWSTART or int(prefix.iloc[-1].close_ts_ms)!=START:raise ValueError('PREFIX_INCOMPLETE')
  full=pd.concat([prefix,tail],ignore_index=True)
  if len(full)!=17519:raise ValueError('YEAR_SOURCE_COUNT')
  execution._frame_records(full,30)
  bound[symbol]=full
  evidence[symbol]={'prefix_rows':len(prefix),'used_dev_rows':len(tail),'all_rows':len(full),
   'full_csv_sha256':sha(full.to_csv(index=False).encode()),'prefix_inputs':receipts}
  print('PAST_PREFIX_BOUND',symbol,len(full),flush=True)
 save('CHRONO_SOURCE_BINDING.json',evidence)
 return bound
def run():
 lock=(STAGE/'paired.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 if (STAGE/'CHRONO_STARTED.json').exists():raise ValueError('CHRONO_ALREADY_STARTED_NO_REPLAY')
 freeze=(STAGE/'FREEZE.json').read_bytes()
 if sha(freeze)!='98c194bdb25df2ca54c56ced9a5c9537adfd0787698cf5aa472855094b46e168':raise ValueError('RULE_FREEZE_CHANGED')
 paired.verify_dependencies()
 control_report=json.loads((STAGE/'CONTROL_RESULT.json').read_text());saved=control_report['result']['trade_rows']
 save('CHRONO_STARTED.json',{'at_utc':now(),'pid':os.getpid(),'owner':'CLOUD_WORK_COORDINATOR_ISSUE1358_V1',
  'user_authority':'연결 계산 들어가; complete same winner-management comparison including opportunity occupancy',
  'rule_freeze_sha256':sha(freeze),'same_hypothesis_no_retune':True,'new_K_chronological_component_cap':1,
  'old_K_approval_reconsumed':False,'S_approved_slot_consumed':0,'root_strategy_mutated':False})
 frames=full_frames()
 campaign=json.loads((REPO/'research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json').read_text())
 windows=campaign['windows'];features=context.cross_features(frames);bound,fits=context.bind_context(frames,features,windows)
 fit_sha=sha(json.dumps(fits,sort_keys=True,separators=(',',':')).encode())
 if fit_sha!=control_report['context_fit_sha256']:raise ValueError('CONTEXT_FIT_NOT_EXACT:'+fit_sha)
 save('CHRONO_CONTEXT_PARITY.json',{'at_utc':now(),'context_fit_sha256':fit_sha,'exact':True})
 print('ORIGINAL_CONTEXT_FITS_EXACT',fit_sha,flush=True)
 snapshot=json.loads((REPO/'research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json').read_text())
 costs=snapshot['costs_bps']
 # Necessary exact baseline reproducibility check, not another candidate/old result claim.
 baseline=k._fresh_touch_successor(bound,costs,windows)
 control=[t for t in baseline['trades'] if t['partition']=='rolling']
 if control!=saved:raise ValueError('FULL128_BASELINE_EXACT_PARITY_FAILED')
 if [x for x in baseline['unresolved'] if x['partition']=='rolling']!=control_report['result']['unresolved']:raise ValueError('BASELINE_UNRESOLVED_CHANGED')
 save('CHRONO_CONTROL_PARITY.json',{'at_utc':now(),'exact128_trade_rows_equal':True,'unresolved_equal':True})
 print('CHRONOLOGICAL128_CONTROL_EXACT',flush=True)
 original_single=execution._single;decisions=[];carry_by_key={};attribution=[]
 def wrapped(signal,frame,records,index,cost,callback,entry_update=None):
  if int(signal['signal_ts_ms'])<START:
   return original_single(signal,frame,records,index,cost,callback,entry_update)
  if signal['identity']!=positive.KELTNER_PARENT or int(signal['max_hold_bars'])!=25:raise ValueError('CHRONO_WRONG_CONTROL_SIGNAL')
  changed=deepcopy(signal);changed['max_hold_bars']=50;trace=[]
  child,unresolved,until,reason=original_single(changed,frame,records,index,cost,paired._continuation_callback(trace),entry_update)
  for item in trace:decisions.append({'trade_key':list(key(signal)),**item})
  if child is not None:
   cost_add=0.0;detail={'additional_events':0}
   if int(child['hold_bars'])>25:
    same_entry_base,_,_,base_reason=original_single(signal,frame,records,index,cost,callback,entry_update)
    if same_entry_base is None or base_reason is not None:raise ValueError('EXTENDED_ENTRY_NO_BASE_PATH')
    cost_add,detail=accounting.carry_scenario(same_entry_base,child,snapshot['snapshots'][signal['symbol']])
    attribution.append({'trade_key':list(key(signal)),'baseline25_exit_ts_ms':same_entry_base['exit_ts_ms'],
     'child_exit_ts_ms':child['exit_ts_ms'],'extra_carry_scenario_bps':cost_add,'detail':detail})
   carry_by_key[key(signal)]=cost_add
  return child,unresolved,until,reason
 execution._single=wrapped
 try:result=k._fresh_touch_successor(bound,costs,windows)
 finally:execution._single=original_single
 for collection in ('trades','unresolved','boundary_excluded'):
  for t in result[collection]:
   if t.get('partition')!='rolling':continue
   t['management_comparison_identity']='scalp7_keltner_hg_fresh_touch_winner_timeout50_utc30m_v1'
   t['control_lineage_identity']=t['identity']
 rows=[t for t in result['trades'] if t['partition']=='rolling']
 unresolved=[t for t in result['unresolved'] if t['partition']=='rolling']
 boundary=[t for t in result['boundary_excluded'] if t['partition']=='rolling']
 old={key(t):t for t in saved};new={key(t):t for t in rows};common=set(old)&set(new)
 removed=[old[i] for i in sorted(set(old)-set(new))];added=[new[i] for i in sorted(set(new)-set(old))]
 carries=[]
 for row in rows:
  extra=carry_by_key[key(row)]
  if extra is None:continue
  t=deepcopy(row);t['cost_bps']+=extra;t['net_bps']=t['gross_bps']-t['cost_bps'];carries.append(t)
 complete_carry=len(carries)==len(rows)
 group_stats={}
 for label,test in [('large35',lambda t:t['mfe_R']>=2),('remainder93',lambda t:t['mfe_R']<2)]:
  members={key(t) for t in saved if test(t)}
  kept=[t for t in carries if key(t) in members]
  group_stats[label]={'baseline_count':len(members),'retained_count':len(kept),
   'baseline_net1x':accounting.total([old[i] for i in members],1),
   'baseline_net2x':accounting.total([old[i] for i in members],2),
   'retained_scenario_net1x':accounting.total(kept,1),'retained_scenario_net2x':accounting.total(kept,2),
   'missing_original_keys':[list(i) for i in sorted(members-set(new))]}
 summary={'schema':'zel.keltner.winner_timeout.chronological_result.v1','completed_at_utc':now(),
  'owner':'CLOUD_WORK_COORDINATOR_ISSUE1358_V1','rule_freeze_sha256':sha(freeze),
  'control_receipt':control_report['receipt_sha256'],'context_fit_sha256':fit_sha,
  'real_price_comparison':True,'all_opportunity_chronology_and_state_replayed':True,
  'new_management_candidate_evaluated':1,'paired_then_chronological_same_rule':True,'S_slot_consumed':0,
  'control_T':len(saved),'child_T':len(rows),'child_unresolved':len(unresolved),'child_boundary_excluded':len(boundary),
  'control_metrics':k._metrics(saved),'child_static_metrics':k._metrics(rows),
  'child_extra_carry_scenario_metrics':k._metrics(carries) if complete_carry else None,
  'net1x_control':accounting.total(saved,1),'net2x_control':accounting.total(saved,2),
  'net1x_child_static':accounting.total(rows,1),'net2x_child_static':accounting.total(rows,2),
  'net1x_child_carry_scenario':accounting.total(carries,1) if complete_carry else None,
  'net2x_child_carry_scenario':accounting.total(carries,2) if complete_carry else None,
  'total_extra_carry_scenario_bps':sum(carry_by_key[key(row)] for row in rows if carry_by_key[key(row)] is not None),
  'removed_original_trades':[{'trade_key':list(key(t)),'net1x':t['net_bps'],'net2x':t['gross_bps']-2*t['cost_bps'],'mfe_R':t['mfe_R'],'reason':t['reason']} for t in removed],
  'added_trades':[{'trade_key':list(key(t)),'net1x':t['net_bps'],'net2x':t['gross_bps']-2*t['cost_bps'],'mfe_R':t['mfe_R'],'reason':t['reason']} for t in added],
  'cohorts':group_stats,'timeout_decisions':decisions,'incremental_carry_attribution':attribution,
  'candidate_count':result['candidate_count_by_partition'],'admitted_count':result['admitted_count_by_partition'],
  'rejections_by_partition':result['rejections_by_partition'],
  'account_nav':False,'fresh_oos':False,'historical_latency_observed':False,'actual_historical_funding_complete':False,
  'costs_are_frozen_reference_plus_conservative_extra_settlement_scenario':True,
  'entry_filter_added':False,'root_strategy_changes':0,'shadow_changes':0,'orders':0,'promotion':False,
  'chronological_rows_sha256':save('CHRONO_ROWS.json',{'trades':rows,'carry_scenario_trades':carries,'unresolved':unresolved,'boundary_excluded':boundary})}
 digest=save('CHRONO_SUMMARY.json',summary)
 print('CHRONO_COMPLETE',now(),'SHA256',digest,flush=True)
 print(json.dumps({n:summary[n] for n in ('control_T','child_T','child_unresolved','net1x_control','net2x_control','net1x_child_static','net2x_child_static','net1x_child_carry_scenario','net2x_child_carry_scenario','removed_original_trades','added_trades','cohorts')},ensure_ascii=False),flush=True)
if __name__=='__main__':
 try:run()
 except Exception as exc:
  if not (STAGE/'CHRONO_FAILURE.json').exists():save('CHRONO_FAILURE.json',{'at_utc':now(),'error':type(exc).__name__,'message':str(exc)})
  raise

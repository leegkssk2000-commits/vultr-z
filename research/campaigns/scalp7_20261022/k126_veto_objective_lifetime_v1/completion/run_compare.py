"""One source-frozen C state-lifetime comparison, all native chronological entries."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
import sys,os,json,gzip,hashlib,io,fcntl,inspect,math
S=Path(__file__).resolve().parent
I=Path('/home/z/z/runtime/k126_pullback_structure_failure_20261021_v1')
P=Path('/home/z/z/runtime/k126_c_veto_consume_20261022_v1')
C=P/'work_c_exact';CACHE=Path('/home/z/z/runtime/k_winner_handoff_20261021T1230Z')
sys.path.insert(0,str(I));import structural_failure as structure
h=structure.h
sys.path.insert(0,str(C));import run_owner_observer as observer
sys.path.insert(0,str(S));import objective_lifetime as adapter
sys.path.insert(0,'/home/z/z/runtime/k_h02_prior_trend_20261021');import run_h02 as support
from backend.research.rebuild import scalp7_source_data_v2 as source,scalp7_rolling_context_v2 as context
import pandas as pd
OWNER='CLOUD_WORK_COORDINATOR_ISSUE1358_V1'
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def encoded(v):return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def save(n,v):
 b=encoded(v)
 with (S/n).open('xb') as f:f.write(b)
 return sha(b)
def key(r):return (r['symbol'],int(r['side']),int(r['signal_ts_ms']))
def net(r,m=1):return float(r['gross_bps'])-m*float(r['cost_bps'])
def brief(r):return {'key':list(key(r)),'entry_ts_ms':r['entry_ts_ms'],'exit_ts_ms':r['exit_ts_ms'],'net1x':net(r),'net2x':net(r,2),'reason':r['reason']}
def run():
 locks=[]
 for p in [h.BASE/'paired.lock',S/'candidate_once.lock']:
  handle=p.open('rb' if p.exists() else 'a+');fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(handle)
 if (S/'CANDIDATE_STARTED.json').exists():raise ValueError('STARTED_ALREADY_EXISTS_NO_REPLAY')
 freeze=json.loads((S/'EXECUTION_FREEZE.json').read_bytes())
 for p,pin in freeze['code_sha256'].items():
  if sha(Path(p).read_bytes())!=pin:raise ValueError('EXECUTION_SOURCE_CHANGED:'+p)
 diagnostic=json.loads((S/'DIAGNOSTIC.json').read_bytes())
 if diagnostic['existing_trace_sha_verified'] is not True:raise ValueError('UNVERIFIED_DIAGNOSTIC')
 auth=json.loads((S/'CANDIDATE_AUTHORITY.json').read_bytes())
 if auth['owner']!=OWNER or auth['candidate']!=adapter.IDENTITY or auth['capacity']!='CLEAR':raise ValueError('UNBOUND_AUTHORITY')
 saved,baseline_summary=observer.load_saved(P/'incumbent')
 receipt=json.loads((P/'observer/OBSERVER_RECEIPT.json').read_bytes())
 if not all(receipt[k] for k in ['raw126_exact','unresolved_exact','boundary_excluded_exact']):raise ValueError('OBSERVER_PARITY_REQUIRED')
 for p,pin in observer.RUNTIME_PINS.items():observer.checked_bytes(p,pin)
 for p,pin in observer.REPO_PINS.items():observer.checked_bytes(h.REPO/p,pin)
 h.timeout.verify_dependencies()
 save('CANDIDATE_STARTED.json',{'at_utc':now(),'pid':os.getpid(),'owner':OWNER,'candidate':adapter.IDENTITY,'new_policy_comparisons':1,'observer_receipt_sha256':sha((P/'observer/OBSERVER_RECEIPT.json').read_bytes()),'authority':auth,'parameter_sweep':False})
 cache=json.loads((CACHE/'INPUT_CACHE.json').read_bytes());binding=json.loads(observer.checked_bytes(h.BASE/'CHRONO_SOURCE_BINDING.json',observer.BINDING_SHA))
 if set(cache['symbols'])!=set(source.SYMBOLS):raise ValueError('SYMBOLS_CHANGED')
 frames={}
 for symbol in source.SYMBOLS:
  rec=cache['symbols'][symbol];raw=observer.checked_bytes(CACHE/rec['path'],rec['sha256'])
  frame=pd.read_csv(io.BytesIO(raw),compression='gzip',float_precision='round_trip')
  if len(frame)!=17519 or sha(frame.to_csv(index=False).encode())!=binding[symbol]['full_csv_sha256']:raise ValueError('FRAME_CHANGED:'+symbol)
  frames[symbol]=frame
 windows=json.loads((h.REPO/'research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json').read_bytes())['windows']
 snapshot=json.loads((h.REPO/'research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json').read_bytes());costs=snapshot['costs_bps']
 bound,fits=context.bind_context(frames,context.cross_features(frames),windows)
 fitsha=sha(json.dumps(fits,sort_keys=True,separators=(',',':')).encode())
 if fitsha!=observer.CONTEXT_SHA:raise ValueError('CONTEXT_CHANGED')
 incumbent=structure.ExitComparison(True).build();source_text=inspect.getsource(structure.h.k._fresh_touch_successor)
 if adapter.build(incumbent,source_text=source_text,enabled=False) is not incumbent:raise ValueError('DISABLED_CONTROL_NOT_IDENTICAL')
 candidate=adapter.build(incumbent,source_text=source_text,enabled=True)
 print('ACTUAL_ONE_CANDIDATE_CHRONOLOGY_START',now(),flush=True)
 result=candidate(bound,costs,windows)
 rawrows=[r for r in result['trades'] if r['partition']=='rolling']
 unres=[r for r in result['unresolved'] if r['partition']=='rolling'];boundary=[r for r in result['boundary_excluded'] if r['partition']=='rolling']
 bywindow={w['label']:w for w in windows};prepared={}
 def frame_for(row):
  k=(row['window_label'],row['symbol'])
  if k not in prepared:
   w=bywindow[row['window_label']];f=bound[row['symbol']]
   f=f[(f.open_ts_ms>=int(w['start_ms'])-200*h.TF)&(f.close_ts_ms<=int(w['end_ms']))].reset_index(drop=True)
   rec,idx=h.execution._frame_records(f,30);prepared[k]=(f,rec,idx)
  return prepared[k]
 rows=[];carry=[]
 for row in rawrows:
  t=deepcopy(row);extra=0.;detail={'additional_events':0}
  if int(row['exit_ts_ms'])-int(row['entry_ts_ms'])>25*h.TF:
   f,rec,idx=frame_for(row);sig=deepcopy(row['signal']);sig['identity']=h.positive.KELTNER_PARENT;sig['max_hold_bars']=25
   base,op,until,why=h.execution._single(sig,f,rec,idx,costs[row['symbol']],h.positive.exit_update,h.positive.entry_update)
   if base is None or op or why:raise ValueError('CARRY_REFERENCE_UNKNOWN')
   extra,detail=support.accounting.carry_scenario(base,row,snapshot['snapshots'][row['symbol']])
   if extra is None:raise ValueError('CARRY_UNKNOWN')
  t['cost_bps']+=extra;t['net_bps']=net(t);t['management_comparison_identity']=adapter.IDENTITY;rows.append(t)
  if extra or detail.get('additional_events'):carry.append({'key':list(key(t)),'extra_bps':extra,'detail':detail})
 old=saved['trades'];before=support.compact(old);after=support.compact(rows)
 for level in ['cost1x','cost2x']:
  for metric in ['Net_bps','T','PF','DD_bps','MaxLossStreak','worst_loss_run_bps']:
   if not math.isclose(before[level][metric],baseline_summary['child'][level][metric],rel_tol=1e-11,abs_tol=1e-7):raise ValueError('BASELINE_METRIC_DRIFT:'+metric)
 oldmap={key(r):r for r in old};newmap={key(r):r for r in rows}
 if len(newmap)!=len(rows):raise ValueError('DUPLICATE_CANDIDATE_ENTRY')
 common=oldmap.keys()&newmap.keys();removed=[oldmap[k] for k in sorted(oldmap.keys()-newmap.keys())];added=[newmap[k] for k in sorted(newmap.keys()-oldmap.keys())]
 changed=[{'key':list(k),'old':brief(oldmap[k]),'new':brief(newmap[k]),'delta1x':net(newmap[k])-net(oldmap[k])} for k in sorted(common) if oldmap[k]['exit_ts_ms']!=newmap[k]['exit_ts_ms'] or abs(net(newmap[k])-net(oldmap[k]))>1e-8]
 attr={}
 for m in [1,2]:
  delta=sum(net(t,m) for t in rows)-sum(net(t,m) for t in old);cd=sum(net(newmap[k],m)-net(oldmap[k],m) for k in common);an=sum(net(t,m) for t in added);rn=sum(net(t,m) for t in removed)
  if abs(delta-(cd+an-rn))>1e-7:raise ValueError('ATTRIBUTION_MISMATCH')
  attr[f'cost{m}x']={'net_delta':delta,'common_delta':cd,'added_net':an,'removed_net':rn,'reconciled':True}
 cohorts={}
 for label,pred in [('large_winners',lambda r:net(r)>0 and r['mfe_R']>=2),('ordinary_winners',lambda r:net(r)>0 and r['mfe_R']<2),('losses',lambda r:net(r)<0)]:
  group=[r for r in old if pred(r)];ks={key(r) for r in group}
  cohorts[label]={'baseline_T':len(group),'baseline_net1x':sum(net(r) for r in group),'retained_T':len(ks&newmap.keys()),'retained_net1x':sum(net(newmap[k]) for k in ks&newmap.keys()),'removed_T':len(ks-newmap.keys()),'removed_net1x':sum(net(oldmap[k]) for k in ks-newmap.keys())}
 worst={tuple(k) for k in before['cost1x']['longest_loss_run_keys']}
 targets=[r for r in old if (r['symbol'],r['side'],r['entry_ts_ms']) in worst]
 target_result=[{'old':brief(r),'new':brief(newmap[key(r)]) if key(r) in newmap else None,'same_original_entry_retained':key(r) in newmap} for r in targets]
 c114_saved=json.loads((P/'ROWS.json').read_bytes());c114summary=json.loads((P/'SUMMARY.json').read_bytes())
 if sha((P/'ROWS.json').read_bytes())!=c114summary['rows_sha256']:raise ValueError('C114_SAVED_ROWS_CHANGED')
 risk114=support.compact(c114_saved['trades']);rmap={key(t):t for t in c114_saved['trades']}
 for lev in ['cost1x','cost2x']:
  for field in ['T','Net_bps','PF','DD_bps','MaxLossStreak','worst_loss_run_bps']:
   if not math.isclose(risk114[lev][field],c114summary['child'][lev][field],abs_tol=1e-7):raise ValueError('C114_METRIC_DRIFT')
 rcommon=rmap.keys()&newmap.keys();radded=[newmap[k] for k in newmap.keys()-rmap.keys()];rremoved=[rmap[k] for k in rmap.keys()-newmap.keys()]
 rattr={}
 for m in [1,2]:
  cd=sum(net(newmap[k],m)-net(rmap[k],m) for k in rcommon);an=sum(net(t,m) for t in radded);rn=sum(net(t,m) for t in rremoved);delta=after[f'cost{m}x']['Net_bps']-risk114[f'cost{m}x']['Net_bps']
  if abs(delta-(cd+an-rn))>1e-7:raise ValueError('C114_ATTRIBUTION_MISMATCH')
  rattr[f'cost{m}x']={'net_delta':delta,'common_delta':cd,'added_net':an,'removed_net':rn,'reconciled':True}
 missed5=[t for t in old if key(t) not in rmap and net(t)>0]
 restored=[{'old':brief(t),'child':brief(newmap[key(t)]) if key(t) in newmap else None,'restored':key(t) in newmap} for t in missed5]
 rsha=save('ROWS.json',{'trades':rows,'raw_trades':rawrows,'unresolved':unres,'boundary_excluded':boundary,'carry_scenario':carry,'native_traces':result.get('traces',[]),'objective_expiry_events':candidate.events})
 better_net=all(after[k]['Net_bps']>=before[k]['Net_bps']-1e-7 for k in ['cost1x','cost2x'])
 no_worse_risk=all(after[k]['DD_bps']<=before[k]['DD_bps']+1e-7 and after[k]['worst_loss_run_bps']>=before[k]['worst_loss_run_bps']-1e-7 and after[k]['MaxLossStreak']<=before[k]['MaxLossStreak'] for k in ['cost1x','cost2x'])
 disposition='PRESERVE_DEV_CANDIDATE_PENDING_INDEPENDENT_VALIDATION' if better_net and no_worse_risk and not unres and not boundary else 'REJECT_OR_TRADEOFF_KEEP_INCUMBENT'
 summary={'at_utc':now(),'classification':'ACTUAL_ONE_FIXED_OBJECTIVE_LIFETIME_FULL_CHRONOLOGY_USED_DEV','candidate':adapter.IDENTITY,'C_observer_source_commit':'77ce5616ed6e29c421592f319e7253b81dd79bdc','C114_saved_commit':'441fa935d1a7d6711ef8287ef0a6bf34054c6796','risk114':risk114,'against_C114':rattr,'previously_missed_five_winners':restored,'objective_expiry_events_count':len(candidate.events),'incumbent_commit':'81a12c422ee9329996d2f6b983267d2def490d4b','baseline':before,'child':after,'original_K126_control':baseline_summary['baseline'],'attribution':attr,'cohorts':cohorts,'removed':list(map(brief,removed)),'added':list(map(brief,added)),'changed_common':changed,'original_worst8':target_result,'child_unresolved':len(unres),'child_boundary_excluded':len(boundary),'context_fit_sha256':fitsha,'rows_sha256':rsha,'source_hashes_exact':True,'observer_raw126_exact':True,'new_hypotheses':1,'S_budget_consumed':0,'D_risk_policy_applied':False,'parameter_sweep':False,'account_NAV_MTM':False,'actual_historical_funding_verified':False,'fresh_OOS':False,'orders':0,'current_shadow_changes':0,'promotion':False,'disposition':disposition}
 save('SUMMARY.json',summary)
 print('COMPLETE',json.dumps({k:summary[k] for k in ['at_utc','baseline','child','attribution','cohorts','child_unresolved','disposition']},ensure_ascii=False),flush=True)
if __name__=='__main__':
 try:run()
 except Exception as e:
  if not (S/'CANDIDATE_FAILURE.json').exists():save('CANDIDATE_FAILURE.json',{'at_utc':now(),'error_type':type(e).__name__,'error':str(e),'no_blind_retry':True})
  raise

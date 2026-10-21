"""One user-authorized all128 paired used-DEV comparison; no orders, tokens or network."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime, timezone
import fcntl, hashlib, importlib.util, json, math, os, sys, traceback
STAGE = Path(__file__).resolve().parent
REPO = Path('/home/z/worktrees/zel-work-b-retry-6f7a4217-20261020')
SOURCE = Path('/home/z/z/runtime/economic7_campaign_20260915')
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(STAGE))
from backend.research.rebuild import scalp7_source_data_v2 as source
from ops import scalp7_keltner_fresh_touch_successor_v1 as k
import winner_timeout_comparison as paired
START, END, TF = 1768262400000, 1789430400000, 1800000
EXPECTED = {
 'BTC-USDT':'ec97e77c70e96eb480092d75a6e9291050b9ba491c27cd066ae0b9d3b7d4015d',
 'DOGE-USDT':'17da06e501c43e16802f7473655fe2511fea2c7fcb7ea534a9c6ac24a5fec26b',
 'ETH-USDT':'dcbf70620b28219e8382b8e14394cc495921a543ae46823adade05bcf1e487e2',
 'LINK-USDT':'5e1e52f8e8973c20aab1c2b9287843d2f2334f8c7444a1366d18094c095eb578',
 'SOL-USDT':'618a85896f739174b9a6535ef7a81478069d0640eab5c55e30beb51f2500becc',
 'XRP-USDT':'d6afbcb2b2537d1d0fe30373f61756854e8b4e03d3ebdf0459aea7d573f71641'}
def now(): return datetime.now(timezone.utc).isoformat()
def sha(raw): return hashlib.sha256(raw).hexdigest()
def encode(value):
 return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False,
                    default=lambda x: x.item() if hasattr(x,'item') else str(x))+'\n').encode()
def save(name,value):
 raw=encode(value)
 with (STAGE/name).open('xb') as handle: handle.write(raw)
 return sha(raw)
def key(row): return (row['symbol'],int(row['side']),int(row['signal_ts_ms']))
def total(rows,m): return sum(float(x['gross_bps'])-m*float(x['cost_bps']) for x in rows)
def carry_scenario(base, child, snap):
 if child is None: return None, None
 if int(child['exit_ts_ms'])==int(base['exit_ts_ms']): return 0.0, {'additional_events':0}
 a,b=int(base['exit_ts_ms']),int(child['exit_ts_ms'])
 if b<a: raise ValueError('EXTENSION_EXIT_PRECEDES_CONTROL')
 stamps=sorted(int(r['ts_ms']) for r in snap['funding_rows'])
 diffs={y-x for x,y in zip(stamps,stamps[1:])}
 if diffs!={28800000}: return None, {'clock':'UNBOUND_NOT_ZERO','observed_diffs':sorted(diffs)}
 period=28800000; phase=stamps[0]%period
 if any(t%period!=phase for t in stamps): raise ValueError('FUNDING_PHASE_DRIFT')
 first=((a-phase+period-1)//period)*period+phase
 times=list(range(first,b+1,period))
 remaining=1.0-float(base['signal']['partial_fraction'])
 reserve=float(snap['funding_p95_abs_bps'])
 return len(times)*remaining*reserve, {'additional_events':len(times),'event_times_ms':times,
  'remaining_notional_fraction':remaining,'reserve_bps_per_event':reserve,
  'clock':'CURRENT_SNAPSHOT_8H_INFERRED_HISTORICAL_SCENARIO_NOT_VERIFIED_HISTORY',
  'interval_convention':'INCLUSIVE_BOTH_ENDPOINTS_CONSERVATIVE_NO_CREDIT'}
def run():
 lock=(STAGE/'paired.lock').open('a+')
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 if (STAGE/'STARTED_BOUND_CSV.json').exists(): raise ValueError('ALREADY_STARTED_NO_BLIND_REPLAY')
 freeze_raw=(STAGE/'FREEZE.json').read_bytes(); freeze=json.loads(freeze_raw)
 if sha(freeze_raw)!='98c194bdb25df2ca54c56ced9a5c9537adfd0787698cf5aa472855094b46e168':raise ValueError('FREEZE_CHANGED')
 paired.verify_dependencies()
 control_raw=(STAGE/'CONTROL_RESULT.json').read_bytes()
 if sha(control_raw)!='d62a9513996c8b2d0e648803ff8e498e31bb029faaa6008c125eee68dc8b85a1': raise ValueError('CONTROL_RAW_MISMATCH')
 control_report=json.loads(control_raw); controls=control_report['result']['trade_rows']
 if len(controls)!=128 or len({key(t) for t in controls})!=128: raise ValueError('ALL128_CONTROL_REQUIRED')
 save('STARTED_BOUND_CSV.json',{'at_utc':now(),'pid':os.getpid(),'freeze_sha256':sha(freeze_raw),
  'owner':freeze['owner'],'type':'PAIRED_ONE_AXIS_DIAGNOSTIC','new_full':0,'squeeze_budget_consumed':0})
 print('SOURCE_BINDING_STARTED',now(),flush=True)
 frames=__import__('exact_saved_csv_source').load_exact(SOURCE)
 if set(frames)!=set(EXPECTED):raise ValueError('SYMBOL_COHORT_CHANGED')
 receipts={}
 for symbol,frame in frames.items():
  if frame.attrs['source_inventory_sha256']!=control_report['source_inventory_sha256']:raise ValueError('SOURCE_INVENTORY_MISMATCH')
  selected=frame[(frame.open_ts_ms>=START)&(frame.open_ts_ms<END)].copy().reset_index(drop=True)
  digest=sha(selected.to_csv(index=False).encode())
  if len(selected)!=11759 or digest!=EXPECTED[symbol]:raise ValueError('USED_DEV_CSV_PARITY_FAILED:'+symbol+':'+digest)
  receipts[symbol]={'used_dev_rows':len(selected),'csv_sha256':digest,'segment_count':int(selected.segment_id.nunique())}
 save('SOURCE_BINDING.json',{'at_utc':now(),'inventory':control_report['source_inventory_sha256'],'symbols':receipts,
  'historical_availability':'BAR_CLOSE_MODEL_NOT_OBSERVED_DELIVERY','market_api_calls':0})
 print('ALL6_SOURCE_PARITY_PASS',now(),flush=True)
 campaign=json.loads((REPO/'research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json').read_text())
 windows={w['label']:w for w in campaign['windows']}
 cost_path=REPO/'research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json'
 cost_raw=cost_path.read_bytes(); costs=json.loads(cost_raw)
 results=[]; changed=[]; child_static=[]; child_carry=[]
 for idx,base in enumerate(controls):
  w=windows[base['window_label']]
  if w['partition']!='rolling' or not int(w['start_ms'])<=int(base['entry_ts_ms'])<int(w['end_ms']):raise ValueError('ORIGINAL_ROLLING_WINDOW_DRIFT')
  frame=frames[base['symbol']]
  frame=frame[(frame.open_ts_ms>=int(w['start_ms'])-200*TF)&(frame.close_ts_ms<=int(w['end_ms']))].reset_index(drop=True)
  item=paired.compare_one(base,frame,window_end_ms=int(w['end_ms']),hard_max_hold_bars=50,
    horizon_authority='FREEZE.json:sha256:'+sha(freeze_raw),additional_carry_bps=None)
  item['trade_key']=list(key(base)); item['saved_window_label']=base['window_label']
  child=item['child']
  if child is not None:
   child['window_label']=base['window_label'];child['partition']=base['partition']
   child_static.append(deepcopy(child))
   carry,detail=carry_scenario(base,child,costs['snapshots'][base['symbol']])
   item['incremental_carry_scenario_bps']=carry; item['carry_scenario_detail']=detail
   item['actual_historical_incremental_carry_bps']=None if child['exit_ts_ms']!=base['exit_ts_ms'] else 0.0
   if carry is not None:
    valued=deepcopy(child);valued['cost_bps']+=carry;valued['net_bps']=valued['gross_bps']-valued['cost_bps'];child_carry.append(valued)
    item['net_delta_inherited_cost_plus_carry_scenario_1x']=float(child['gross_bps'])-float(base['gross_bps'])-carry
    item['net_delta_inherited_cost_plus_carry_scenario_2x']=float(child['gross_bps'])-float(base['gross_bps'])-2*carry
   if child['exit_ts_ms']!=base['exit_ts_ms'] or abs(child['gross_bps']-base['gross_bps'])>1e-8:
    changed.append({'trade_key':list(key(base)),'window_label':base['window_label'],'side':base['side'],
     'entry_ts_ms':base['entry_ts_ms'],'base_exit_ts_ms':base['exit_ts_ms'],'child_exit_ts_ms':child['exit_ts_ms'],
     'base_reason':base['reason'],'child_reason':child['reason'],'base_hold_bars':base['hold_bars'],'child_hold_bars':child['hold_bars'],
     'extra_hold_minutes':(child['exit_ts_ms']-base['exit_ts_ms'])/60000,
     'base_net1x':base['net_bps'],'child_net1x_static':child['net_bps'],
     'gross_delta_trade_bps':item['gross_delta_trade_bps'],'additional_carry_scenario_bps':carry,
     'scenario_delta1x':item.get('net_delta_inherited_cost_plus_carry_scenario_1x'),
     'scenario_delta2x':item.get('net_delta_inherited_cost_plus_carry_scenario_2x'),
     'timeout_decisions':item['timeout_decisions']})
  results.append(item)
  if (idx+1)%16==0:print('PAIRED_CONTROLS_REPRODUCED',idx+1,flush=True)
 conflicts=[]
 for item in results:
  a,b=item['control'],item['child']
  if b is None or b['exit_ts_ms']<=a['exit_ts_ms']:continue
  release=max(int(b['exit_ts_ms']),int(b['outcome_available_ts_ms']))+(TF if b['reason']=='OPEN_GAP_STOP' else 0)
  for other in controls:
   if other['symbol']==a['symbol'] and other['window_label']==a['window_label'] and key(other)!=key(a) and int(a['exit_ts_ms'])<=int(other['entry_ts_ms'])<release:
    conflicts.append({'extended':list(key(a)),'later_control_entry':list(key(other)),'later_control_net1x':other['net_bps']})
 complete=len(child_static)==len(controls);carry_complete=len(child_carry)==len(controls)
 groups={}
 for label,predicate in [('large35',lambda t:t['mfe_R']>=2.0),('remainder93',lambda t:t['mfe_R']<2.0),('all128',lambda t:True)]:
  selected=[i for i in results if predicate(i['control'])]
  bas=[i['control'] for i in selected]; keys={key(t) for t in bas}
  sta=[x for x in child_static if key(x) in keys];car=[x for x in child_carry if key(x) in keys]
  groups[label]={'T':len(bas),'base_net1x':total(bas,1),'base_net2x':total(bas,2),
   'child_static_net1x':total(sta,1) if len(sta)==len(bas) else None,'child_static_net2x':total(sta,2) if len(sta)==len(bas) else None,
   'child_carry_scenario_net1x':total(car,1) if len(car)==len(bas) else None,'child_carry_scenario_net2x':total(car,2) if len(car)==len(bas) else None}
 summary={'schema':'zel.keltner.winner_timeout.real_paired_summary.v1','completed_at_utc':now(),
  'freeze_sha256':sha(freeze_raw),'source_control_receipt':control_report['receipt_sha256'],'cost_snapshot_sha256':sha(cost_raw),
  'source_binding':receipts,'controls_reproduced':len(results),'paired_children_resolved':len(child_static),
  'hard_max_hold_bars':50,'changed_trades':changed,'unchanged_trades':len(results)-len(changed),
  'unresolved':sum(x['child'] is None for x in results),'groups':groups,
  'control_metrics':k._metrics(controls),'paired_static_metrics':k._metrics(child_static) if complete else None,
  'paired_carry_scenario_metrics':k._metrics(child_carry) if carry_complete else None,
  'baseline_admitted_entry_overlap_conflicts':conflicts,'all_opportunity_timeline_replayed':False,
  'actual_historical_incremental_funding_complete':False,'account_nav':False,'fresh_oos':False,
  'new_paired_economic_comparisons':1,'new_full':0,'squeeze_budget_consumed':0,'orders':0,'promotion':False,
  'interpretation':'ALL128_SAME_ENTRY_REAL_PRICE_COMPARISON; static and extra-carry scenario are not actual historical execution costs; no changed-occupancy acceptance.'}
 summary['paired_rows_sha256']=save('PAIRED_ROWS.json',results)
 digest=save('SUMMARY.json',summary)
 print('COMPLETE',now(),'SUMMARY_SHA256',digest,flush=True)
 print(json.dumps({'groups':groups,'changed_trades':changed,'conflicts':conflicts,'resolved':len(child_static),'summary_sha256':digest},ensure_ascii=False),flush=True)
if __name__=='__main__':
 try:run()
 except Exception as exc:
  print('FAILED',type(exc).__name__,str(exc),flush=True)
  if not (STAGE/'FAILURE.json').exists():save('FAILURE.json',{'at_utc':now(),'type':type(exc).__name__,'message':str(exc),'economic_success':False})
  raise

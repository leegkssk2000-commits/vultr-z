"""Inspect completed C/D passive traces. No new fills, signals, or strategy runs."""
from pathlib import Path
from collections import Counter
from statistics import median
from datetime import datetime,timezone
import json,gzip,hashlib,math
S=Path(__file__).resolve().parent
BASE=Path('/home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1')
C=Path('/home/z/z/runtime/k117_passive_exit_observer_c_20261022_v1')
D=Path('/home/z/k117_be_observer_d_once_20261022_v1')
PIN='7cba96a0627dbec42459f344a6e8e7dd70d97f87d71dfb573e10975153d7d0a7'
def read(p):return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())
def key(r):return (r['symbol'],int(r['side']),int(r['signal_ts_ms']))
def net(r,m=1):return float(r['gross_bps'])-m*float(r['cost_bps'])
def describe(vals):return {'n':len(vals),'minimum':min(vals) if vals else None,'median':median(vals) if vals else None,'maximum':max(vals) if vals else None}
def validate_file(folder,name,rec):
    raw=(folder/name).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=rec['sha256']:raise ValueError('TRACE_SHA_CHANGED:'+name)
raw=(BASE/'ROWS.json').read_bytes()
if hashlib.sha256(raw).hexdigest()!=PIN:raise ValueError('BASELINE_CHANGED')
saved=json.loads(raw);rows=saved['trades'];rm={key(r):r for r in rows}
result={'at_utc':datetime.now(timezone.utc).isoformat(),'classification':'ACTUAL_PASSIVE_TRACE_APPLIED_NO_NEW_POLICY_OR_ECONOMICS','baseline_rows_sha256':PIN,'new_policy_comparisons':0,'orders':0,'current_shadow_changes':0,'baseline_metrics':read(BASE/'SUMMARY.json')['child'],'C':{'completed':False},'D':{'completed':False}}
allrows={k:{'key':list(k),'analysis_only_outcome_labels':{'net1x':net(r),'net2x':net(r,2),'reason':r['reason']}} for k,r in rm.items()}
if (C/'PASSIVE_EXIT_OBSERVER_RECEIPT.json').exists():
    rec=read(C/'PASSIVE_EXIT_OBSERVER_RECEIPT.json')
    for name,pin in rec['files'].items():validate_file(C,name,pin)
    entries=read(C/'EXIT_TRACE_ALL117.json.gz');cm={tuple(r['signal_key']):r for r in entries}
    if set(cm)!=set(rm):raise ValueError('C_COVERAGE_CHANGED')
    for k,r in rm.items():
        t=cm[k];events=t['session']['events'];pre=[e for e in events if e['kind']=='CALLBACK_PRE']
        adverse=[e for e in pre if r['side']*(e['completed_bar']['close']-r['entry_prices'][r['symbol']])<0]
        first=adverse[0] if adverse else None
        allrows[k]['C']={'touch_bound':t['touch_binding']['status']=='BOUND_TO_ACTUAL_K117_OBJECTIVE_TOUCH','completed_callbacks':len(pre),'first_adverse_close_available_ts_ms':first['decision_available_ts_ms'] if first else None,'first_adverse_close_to_exit_minutes':(r['exit_ts_ms']-first['decision_available_ts_ms'])/60000 if first else None,'first_adverse_close_hold_bars':first['position']['hold_bars'] if first else None,'scratch_scheduled':[{'at':e['decision_available_ts_ms'],'hold_bars':e['position']['hold_bars']} for e in events if e['kind']=='BAR_COMMITTED' and e['scratch_scheduled']]}
    cg={}
    for name,predicate in [('loss1x',lambda r:net(r)<0),('winner1x',lambda r:net(r)>0),('cost_cross',lambda r:net(r)>0 and net(r,2)<0)]:
        selected=[allrows[k]['C'] for k,r in rm.items() if predicate(r)]
        cg[name]={'T':len(selected),'no_completed_callback':sum(x['completed_callbacks']==0 for x in selected),'with_adverse_completed_close':sum(x['first_adverse_close_available_ts_ms'] is not None for x in selected),'adverse_close_to_exit_minutes':describe([x['first_adverse_close_to_exit_minutes'] for x in selected if x['first_adverse_close_to_exit_minutes'] is not None])}
    result['C']={'completed':True,'receipt':rec,'all117_touch_bound':sum(x['C']['touch_bound'] for x in allrows.values()),'groups':cg,'interpretation':'Adverse closes are observed history, not a proven failure rule or alternative fill.'}
if (D/'OBSERVER_RECEIPT.json').exists():
    rec=read(D/'OBSERVER_RECEIPT.json')
    for name,pin in rec['files'].items():validate_file(D,name,pin)
    entries=read(D/'BE_ALL117.json.gz');dm={tuple(r['key']):r for r in entries}
    if set(dm)!=set(rm):raise ValueError('D_COVERAGE_CHANGED')
    for k,r in rm.items():
        events=dm[k]['events'];arms=[e for e in events if e['kind']=='CALLBACK_AFTER' and e.get('be_first_arm')];parts=[e for e in events if e['kind']=='PARTIAL_FILLED'];terminal=[e for e in events if e['kind']=='TERMINAL']
        if len(terminal)!=1:raise ValueError('D_TERMINAL_NOT_UNIQUE')
        t=terminal[0];p=t['position'];gross=p['realized_parts_bps']+p['remaining']*p['side']*(t['exit_prices'][r['symbol']]/p['entry_price']-1)*10000
        if not math.isclose(gross,r['gross_bps'],abs_tol=1e-7):raise ValueError('TRACE_GROSS_MISMATCH')
        if not math.isclose(gross-r['cost_bps'],net(r),abs_tol=1e-7):raise ValueError('TRACE_NET_MISMATCH')
        if any(not e['monotonic'] for e in events if e['kind']=='STOP_APPLIED'):raise ValueError('STOP_LOOSENED')
        first=arms[0] if arms else None
        requests=[e for e in events if e['kind']=='STOP_APPLIED'];activated=[e for e in events if e['kind']=='BAR_START' and e['activation_of_request_event_seq'] is not None]
        allrows[k]['D']={'be_arms':len(arms),'first_be_arm_available_ts_ms':first['available_ts_ms'] if first else None,'be_arm_to_exit_minutes':(r['exit_ts_ms']-first['available_ts_ms'])/60000 if first else None,'stop_request_count':len(requests),'activated_next_bar_count':len(activated),'partial_count':len(parts),'partial_event_times':[e['available_ts_ms'] for e in parts],'runner_arms':sum(e['kind']=='CALLBACK_AFTER' and e.get('runner_first_arm',False) for e in events),'terminal_reason':t['reason'],'terminal_precedence':t['precedence'],'final_remaining':p['remaining'],'realized_parts_bps':p['realized_parts_bps'],'reconciled_gross':gross,'first_arm_completed_close':first['completed_close'] if first else None,'first_arm_expected_fee_be':first['expected_fee_be_from_frozen_rule'] if first else None}
    dg={}
    for name,predicate in [('all117',lambda r:True),('loss1x',lambda r:net(r)<0),('winner1x',lambda r:net(r)>0),('cost_cross',lambda r:net(r)>0 and net(r,2)<0)]:
        selected=[allrows[k]['D'] for k,r in rm.items() if predicate(r)]
        dg[name]={'T':len(selected),'be_armed':sum(x['be_arms']>0 for x in selected),'partial_executed':sum(x['partial_count']>0 for x in selected),'runner_armed':sum(x['runner_arms']>0 for x in selected),'be_arm_to_exit_minutes':describe([x['be_arm_to_exit_minutes'] for x in selected if x['be_arm_to_exit_minutes'] is not None])}
    result['D']={'completed':True,'receipt':rec,'all117_gross_cost_net_reconciled':True,'groups':dg,'interpretation':'Exact original protection/fill accounting only; no alternative stop policy has been evaluated.'}
if not result['C']['completed'] or not result['D']['completed']:raise ValueError('BOTH_ACTUAL_RECEIPTS_REQUIRED')
result['C_D_matched117']=all((allrows[k]['C']['completed_callbacks']>0)==any(e['kind']=='CALLBACK_BEFORE' for e in dm[k]['events']) for k in rm)
for name,value in [('TRACE_FINDINGS.json',result),('TRACE_FACTS_ALL117.json',list(allrows.values()))]:
    with (S/name).open('x') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('baseline_metrics',)},ensure_ascii=False),flush=True)

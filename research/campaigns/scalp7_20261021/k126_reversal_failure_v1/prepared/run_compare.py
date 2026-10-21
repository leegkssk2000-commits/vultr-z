"""One frozen post-entry exit comparison; paired attribution plus complete chronology."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
from collections import Counter
import fcntl, gzip, hashlib, io, json, math, os, sys
import pandas as pd
from reversal_failure import ExitComparison, IDENTITY, REASON, h
sys.path.insert(0,'/home/z/z/runtime/k_h02_prior_trend_20261021')
import run_h02 as support
from backend.research.rebuild import scalp7_source_data_v2 as source, scalp7_rolling_context_v2 as context
S=Path(__file__).resolve().parent
CACHE=Path('/home/z/z/runtime/k_winner_handoff_20261021T1230Z')
OWNER='CLOUD_WORK_COORDINATOR_ISSUE1358_V1'
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def encoded(v):return (json.dumps(v,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
def save(n,v):
    b=encoded(v)
    with (S/n).open('xb') as f:f.write(b)
    return sha(b)
def key(t):return (str(t['symbol']),int(t['side']),int(t['signal_ts_ms']))
def normalized(t):return {k:v for k,v in t.items() if k not in ('management_comparison_identity','control_lineage_identity')}
def net(t,m=1):return float(t['gross_bps'])-m*float(t['cost_bps'])
def brief(t):return {'key':list(key(t)),'net1x':net(t),'net2x':net(t,2),'reason':t['reason'],'entry_ts_ms':t['entry_ts_ms'],'exit_ts_ms':t['exit_ts_ms'],'mfe_R_analysis_only':t['mfe_R']}

def run():
    locks=[]
    for p in [h.BASE/'paired.lock', S/'invocation.lock']:
        f=p.open('a+');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(f)
    if (S/'STARTED.json').exists():raise ValueError('ALREADY_STARTED_NO_BLIND_REPLAY')
    freeze=json.loads((S/'FREEZE.json').read_text())
    for name,pin in freeze['code_pins'].items():
        if sha(Path(name).read_bytes())!=pin:raise ValueError('FROZEN_CODE_CHANGED:'+name)
    authority=json.loads((S/'START_AUTHORITY.json').read_text())
    if authority['candidate']!=IDENTITY or authority['owner']!=OWNER or authority['capacity']!='CLEAR':raise ValueError('AUTHORITY_NOT_BOUND')
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name)==os.getpid():continue
        try:args=[a.decode(errors='replace') for a in (p/'cmdline').read_bytes().split(b'\0') if a]
        except OSError:continue
        if not args or 'python' not in Path(args[0]).name:continue
        if any(a.endswith('/run_compare.py') or a.endswith('/run_h02.py') or a.endswith('/run_handoff.py') or a.endswith('/run_chronological.py') for a in args):raise ValueError('OTHER_COMPARISON_RUNNING:'+p.name)
        if '--candidate' in args and any(a.endswith('adapter.py') for a in args):raise ValueError('NATIVE_CANDIDATE_RUNNING:'+p.name)
    save('STARTED.json',{'at_utc':now(),'pid':os.getpid(),'owner':OWNER,'candidate':IDENTITY,'freeze_sha256':sha((S/'FREEZE.json').read_bytes()),'authority':authority,'new_hypotheses':1,'paired_and_chronological_same_rule':True})
    base_summary_raw=(h.BASE/'CHRONO_SUMMARY.json').read_bytes()
    if sha(base_summary_raw)!='beea1d45254694629225755449a09dc7a6efc687b9b402dff9903863f82df9b8':raise ValueError('BASELINE_SUMMARY_CHANGED')
    prior_summary=json.loads(base_summary_raw);rr=(h.BASE/'CHRONO_ROWS.json').read_bytes()
    if sha(rr)!=prior_summary['chronological_rows_sha256']:raise ValueError('BASELINE_ROWS_CHANGED')
    prior=json.loads(rr);saved=prior['carry_scenario_trades']
    cache=json.loads((CACHE/'INPUT_CACHE.json').read_text());binding=json.loads((h.BASE/'CHRONO_SOURCE_BINDING.json').read_text())
    if set(cache['symbols'])!=set(source.SYMBOLS):raise ValueError('SYMBOL_SET_CHANGED')
    frames={}
    for symbol in source.SYMBOLS:
        rec=cache['symbols'][symbol];raw=(CACHE/rec['path']).read_bytes()
        if sha(raw)!=rec['sha256']:raise ValueError('CACHE_BYTES_CHANGED:'+symbol)
        f=pd.read_csv(io.BytesIO(raw),compression='gzip',float_precision='round_trip')
        if len(f)!=17519 or sha(f.to_csv(index=False).encode())!=binding[symbol]['full_csv_sha256']:raise ValueError('SOURCE_FRAME_CHANGED:'+symbol)
        frames[symbol]=f
    windows=json.loads((h.REPO/'research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json').read_text())['windows']
    bound,fits=context.bind_context(frames,context.cross_features(frames),windows)
    fitsha=sha(json.dumps(fits,sort_keys=True,separators=(',',':')).encode())
    if fitsha!=prior_summary['context_fit_sha256']:raise ValueError('CONTEXT_FIT_CHANGED')
    snapshot=json.loads((h.REPO/'research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json').read_text());costs=snapshot['costs_bps']
    disabled=ExitComparison(False);control=disabled.build()(bound,costs,windows)
    ctrl=[t for t in control['trades'] if t['partition']=='rolling']
    if ctrl!=[normalized(t) for t in prior['trades']]:raise ValueError('CONTROL126_NOT_EXACT')
    if [t for t in control['unresolved'] if t['partition']=='rolling']!=prior['unresolved']:raise ValueError('CONTROL_UNRESOLVED_CHANGED')
    save('CONTROL_PARITY.json',{'at_utc':now(),'exact126_rows':True,'unresolved_exact':True,'six_source_hashes_exact':True,'context_fit_sha256':fitsha})
    print('CONTROL126_EXACT',now(),flush=True)
    bywindow={w['label']:w for w in windows};prepared={}
    def frame_for(row):
        pk=(row['window_label'],row['symbol'])
        if pk not in prepared:
            w=bywindow[row['window_label']];f=bound[row['symbol']]
            f=f[(f.open_ts_ms>=int(w['start_ms'])-200*h.TF)&(f.close_ts_ms<=int(w['end_ms']))].reset_index(drop=True)
            records,index=h.execution._frame_records(f,30);prepared[pk]=(f,records,index)
        return prepared[pk]
    def apply_carry(row):
        t=deepcopy(row);extra=0.;detail={'additional_events':0}
        if int(row['exit_ts_ms'])-int(row['entry_ts_ms'])>25*h.TF:
            f,records,index=frame_for(row);sig=deepcopy(row['signal']);sig['identity']=h.positive.KELTNER_PARENT;sig['max_hold_bars']=25
            base,unres,_,why=h.execution._single(sig,f,records,index,costs[row['symbol']],h.positive.exit_update,h.positive.entry_update)
            if base is None or unres or why:raise ValueError('CARRY_REFERENCE_UNKNOWN')
            extra,detail=support.accounting.carry_scenario(base,row,snapshot['snapshots'][row['symbol']])
            if extra is None:raise ValueError('CARRY_COST_UNKNOWN')
        t['cost_bps']+=extra;t['net_bps']=t['gross_bps']-t['cost_bps'];t['management_comparison_identity']=IDENTITY
        return t,extra,detail
    # Same-entry comparison covers ALL126, never only the known losers.
    paired=[];paired_rows=[];paired_unresolved=[];observer=ExitComparison(True)
    for old in saved:
        f,records,index=frame_for(old);sig=deepcopy(old['signal']);sig['identity']=h.positive.KELTNER_PARENT;sig['max_hold_bars']=25
        t,unres,until,why=observer.single(sig,f,records,index,costs[old['symbol']],h.positive.exit_update,h.positive.entry_update)
        if why:raise ValueError('PAIRED_ADMISSION_DRIFT:'+str(why))
        if unres:
            paired_unresolved.append({'key':list(key(old)),'unresolved':unres});continue
        if t is None:raise ValueError('PAIRED_MISSING')
        t['window_label']=old['window_label'];t['partition']=old['partition'];t,extra,detail=apply_carry(t)
        paired_rows.append(t)
        evt=next((e for e in reversed(observer.events) if tuple(e['trade_key'])==key(old)),None)
        paired.append({'key':list(key(old)),'baseline':brief(old),'child':brief(t),'delta1x':net(t)-net(old),'delta2x':net(t,2)-net(old,2),
            'first_failure':evt,'earlier_exit_minutes':(int(old['exit_ts_ms'])-int(t['exit_ts_ms']))/60000.,
            'existing_stop_or_exit_precedes_rule':t['reason']!=REASON,'extra_carry_scenario_bps':extra})
    save('PAIRED_ALL126.json',{'paired':paired,'unresolved':paired_unresolved,'all_control_entries':126,'counterfactual_not_final_portfolio':True})
    print('PAIRED_ALL126_DONE',now(),flush=True)
    enabled=ExitComparison(True);result=enabled.build()(bound,costs,windows)
    rawrows=[t for t in result['trades'] if t['partition']=='rolling'];rows=[];carry=[]
    for row in rawrows:
        t,extra,detail=apply_carry(row);rows.append(t)
        if extra or detail.get('additional_events'):carry.append({'key':list(key(t)),'extra_bps':extra,'detail':detail})
    unres=[t for t in result['unresolved'] if t['partition']=='rolling'];boundary=[t for t in result['boundary_excluded'] if t['partition']=='rolling']
    oldmap={key(t):t for t in saved};newmap={key(t):t for t in rows}
    if len(oldmap)!=len(saved) or len(newmap)!=len(rows):raise ValueError('DUPLICATE_KEYS')
    removed=[oldmap[k] for k in sorted(oldmap.keys()-newmap.keys())];added=[newmap[k] for k in sorted(newmap.keys()-oldmap.keys())];common=sorted(oldmap.keys()&newmap.keys())
    changed=[]
    for k in common:
        a,b=oldmap[k],newmap[k]
        if abs(net(a)-net(b))>1e-8 or a['exit_ts_ms']!=b['exit_ts_ms']:
            changed.append({'key':list(k),'baseline':brief(a),'child':brief(b),'delta1x':net(b)-net(a),'delta2x':net(b,2)-net(a,2)})
    attr={}
    for m in (1,2):
        delta=sum(net(t,m) for t in rows)-sum(net(t,m) for t in saved)
        common_delta=sum(net(newmap[k],m)-net(oldmap[k],m) for k in common)
        if abs(delta-(common_delta+sum(net(t,m) for t in added)-sum(net(t,m) for t in removed)))>1e-7:raise ValueError('ATTRIBUTION_MISMATCH')
        attr[f'cost{m}x']={'net_delta':delta,'common_delta':common_delta,'added_net':sum(net(t,m) for t in added),'removed_net':sum(net(t,m) for t in removed),'reconciled':True}
    before,after=support.compact(saved),support.compact(rows)
    groups={}
    for label,pred in [('large_winners',lambda t:net(t)>0 and t['mfe_R']>=2),('ordinary_winners',lambda t:net(t)>0 and t['mfe_R']<2),('losses',lambda t:net(t)<0)]:
        members=[t for t in saved if pred(t)];ks={key(t) for t in members}
        groups[label]={'baseline_T':len(members),'baseline_net1x':sum(net(t) for t in members),'retained_T':len(ks&newmap.keys()),'retained_net1x':sum(net(newmap[k]) for k in ks&newmap.keys()),'missing_keys':[list(k) for k in sorted(ks-newmap.keys())]}
    changed_p=[p for p in paired if p['child']['reason']==REASON and p['earlier_exit_minutes']>0]
    loss_p=[p for p in changed_p if p['baseline']['net1x']<0];win_p=[p for p in changed_p if p['baseline']['net1x']>0]
    paired_summary={'same_entries':len(paired),'unresolved':len(paired_unresolved),'changed_earlier_T':len(changed_p),
        'baseline_loser_T':len(loss_p),'loser_delta1x':sum(p['delta1x'] for p in loss_p),'baseline_winner_T':len(win_p),'winner_delta1x':sum(p['delta1x'] for p in win_p),
        'net_delta1x':sum(p['delta1x'] for p in paired),'net_delta2x':sum(p['delta2x'] for p in paired),
        'positive_delta_T':sum(p['delta1x']>1e-8 for p in paired),'negative_delta_T':sum(p['delta1x']< -1e-8 for p in paired),
        'earlier_minutes_total':sum(p['earlier_exit_minutes'] for p in changed_p)}
    worst_keys={tuple(k) for k in before['cost1x']['longest_loss_run_keys']}
    worst_pairs=[p for p in paired if tuple(p['key']) in worst_keys]
    worst={'baseline_keys':[list(k) for k in sorted(worst_keys)],'paired_delta1x':sum(p['delta1x'] for p in worst_pairs),'paired_changed_T':sum(abs(p['delta1x'])>1e-8 for p in worst_pairs),'pairs':worst_pairs}
    money_better=all(after[l]['Net_bps']>=before[l]['Net_bps']-1e-7 for l in ('cost1x','cost2x'))
    loss_better=all(after[l]['worst_loss_run_bps']>=before[l]['worst_loss_run_bps']-1e-7 and after[l]['DD_bps']<=before[l]['DD_bps']+1e-7 for l in ('cost1x','cost2x'))
    state='PRESERVE_DEV_CANDIDATE_FOR_INDEPENDENT_VALIDATION' if money_better and loss_better and not unres and not boundary else 'REJECT_OR_TRADEOFF_REQUIRES_EXPLICIT_REVIEW_KEEP_K126'
    rsha=save('ROWS.json',{'trades':rows,'raw_trades':rawrows,'unresolved':unres,'boundary_excluded':boundary,'child_failure_events':enabled.events,'baseline_failure_events':disabled.events,'carry_scenario':carry})
    summary={'at_utc':now(),'candidate':IDENTITY,'baseline_commit':'308bd2deb7acaaacf1adb582206e78262d72c9d1','classification':'ACTUAL_EXIT_ONLY_USED_DEV_PAIRED_AND_FULL_CHRONOLOGICAL',
      'rule_sha256':sha((S/'FREEZE.json').read_bytes()),'baseline':before,'child':after,'attribution':attr,'paired':paired_summary,'original_worst8':worst,'cohorts':groups,
      'changed_common':changed,'removed':list(map(brief,removed)),'added':list(map(brief,added)),'child_unresolved':len(unres),'child_boundary_excluded':len(boundary),
      'actual_same_prices':True,'context_fit_sha256':fitsha,'source_motivated_not_source_exact':True,'fresh_OOS':False,'account_NAV_MTM':False,
      'actual_historical_funding_verified':False,'baseline_reference_cost_plus_extra_carry_scenario':True,'parameter_sweep':False,'new_hypotheses':1,
      'S_budget_consumed':0,'C_budget_consumed':0,'orders':0,'current_shadow_changes':0,'promotion':False,'rows_sha256':rsha,'disposition':state}
    save('SUMMARY.json',summary)
    print('COMPLETE',json.dumps({k:summary[k] for k in ['at_utc','candidate','baseline','child','attribution','paired','cohorts','child_unresolved','disposition']},ensure_ascii=False),flush=True)
if __name__=='__main__':
    try:run()
    except Exception as e:
        if not (S/'FAILURE.json').exists():save('FAILURE.json',{'at_utc':now(),'error_type':type(e).__name__,'error':str(e),'no_blind_retry':True})
        raise

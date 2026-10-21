"""One preregistered H02 comparison on the authenticated saved 365d context/245d DEV."""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
from collections import Counter
import fcntl,gzip,hashlib,io,json,os,sys,math
import pandas as pd
from prior_trend_gate import PriorTrendGate, IDENTITY, h
from backend.research.rebuild import scalp7_source_data_v2 as source, scalp7_rolling_context_v2 as context
sys.path.insert(0,str(h.BASE))
import run_paired as accounting
S=Path(__file__).resolve().parent
CACHE=Path('/home/z/z/runtime/k_winner_handoff_20261021T1230Z')
OWNER='CLOUD_WORK_COORDINATOR_ISSUE1358_V1'

def sha(b):return hashlib.sha256(b).hexdigest()
def blob(v):return (json.dumps(v,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
def save(name,v):
    b=blob(v)
    with (S/name).open('xb') as f:f.write(b)
    return sha(b)
def key(t):return (t['symbol'],int(t['side']),int(t['signal_ts_ms']))
def now():return datetime.now(timezone.utc).isoformat()
def normalized(t):return {k:v for k,v in t.items() if k not in ['management_comparison_identity','control_lineage_identity']}
def compact(rows):
    m=h.k._metrics(rows)
    answer={l:{k:m[l][k] for k in ['T','Net_bps','Gross_bps','Cost_bps','PF','WR_pct','DD_bps','MaxLossStreak','T_per_day']} for l in ['cost1x','cost2x']}
    for mult in (1,2):
        runs=[];current=[];winruns=[];wins=[]
        ordered=sorted(rows,key=lambda t:(t['outcome_available_ts_ms'],t['symbol'],t['entry_ts_ms']))
        for t in ordered:
            v=t['gross_bps']-mult*t['cost_bps']
            if v<0:
                current.append(t)
                if wins:winruns.append(wins);wins=[]
            else:
                if current:runs.append(current);current=[]
                if v>0:wins.append(t)
                elif wins:winruns.append(wins);wins=[]
        if current:runs.append(current)
        if wins:winruns.append(wins)
        worst=min(runs,key=lambda g:sum(t['gross_bps']-mult*t['cost_bps'] for t in g),default=[])
        longest=max(runs,key=lambda g:(len(g),-sum(t['gross_bps']-mult*t['cost_bps'] for t in g)),default=[])
        answer[f'cost{mult}x'].update(worst_loss_run_bps=sum(t['gross_bps']-mult*t['cost_bps'] for t in worst),
            longest_loss_run_bps=sum(t['gross_bps']-mult*t['cost_bps'] for t in longest),
            longest_loss_run_keys=[list(key(t)) for t in longest],
            max_win_run=max(map(len,winruns),default=0),
            median_win_run=float(__import__('statistics').median(map(len,winruns))) if winruns else 0.)
    return answer

def run():
    locks=[]
    for p in [h.BASE/'paired.lock',S/'invocation.lock']:
        f=p.open('a+');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(f)
    if (S/'STARTED.json').exists():raise ValueError('ALREADY_STARTED_NO_BLIND_REPLAY')
    freeze=json.loads((S/'FREEZE.json').read_text())
    if sha((S/'prior_trend_gate.py').read_bytes())!=freeze['code_sha256']:raise ValueError('FROZEN_GATE_CHANGED')
    receipt=json.loads((S/'START_AUTHORITY.json').read_text())
    if receipt['owner']!=OWNER or receipt['candidate']!=IDENTITY or receipt['capacity']!='CLEAR':raise ValueError('AUTHORITY_OR_CAPACITY_NOT_BOUND')
    # Same-identity output-name changes do not circumvent duplicate detection.
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
        try:args=[x.decode(errors='replace') for x in (proc/'cmdline').read_bytes().split(b'\0') if x]
        except OSError:continue
        if any(x.endswith('adapter.py') for x in args) and '--candidate' in args:raise ValueError('OTHER_NATIVE_CANDIDATE_ACTIVE:'+proc.name)
        if any(x.endswith('/run_h02.py') for x in args):raise ValueError('DUPLICATE_H02_PROCESS:'+proc.name)
    save('STARTED.json',{'at_utc':now(),'owner':OWNER,'pid':os.getpid(),'freeze_sha256':sha((S/'FREEZE.json').read_bytes()),'authority':receipt,'new_hypotheses':1,'parameter_sweep':False})
    priorraw=(h.BASE/'CHRONO_ROWS.json').read_bytes();prior_summary=json.loads((h.BASE/'CHRONO_SUMMARY.json').read_text())
    if sha(priorraw)!=prior_summary['chronological_rows_sha256']:raise ValueError('BASELINE_ROWS_HASH')
    prior=json.loads(priorraw);saved=prior['carry_scenario_trades']
    cache=json.loads((CACHE/'INPUT_CACHE.json').read_text());binding=json.loads((h.BASE/'CHRONO_SOURCE_BINDING.json').read_text())
    frames={}
    for symbol in source.SYMBOLS:
        p=cache['symbols'][symbol];raw=(CACHE/p['path']).read_bytes()
        if sha(raw)!=p['sha256']:raise ValueError('SOURCE_CACHE_BYTES_CHANGED')
        f=pd.read_csv(io.BytesIO(raw),compression='gzip',float_precision='round_trip')
        if len(f)!=17519 or sha(f.to_csv(index=False).encode())!=binding[symbol]['full_csv_sha256']:raise ValueError('SOURCE_CONTEXT_PARITY_CHANGED')
        frames[symbol]=f
    windows=json.loads((h.REPO/'research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json').read_text())['windows']
    bound,fits=context.bind_context(frames,context.cross_features(frames),windows)
    fitsha=sha(json.dumps(fits,sort_keys=True,separators=(',',':')).encode())
    if fitsha!=prior_summary['context_fit_sha256']:raise ValueError('ORIGINAL_CONTEXT_FIT_CHANGED')
    snapshot=json.loads((h.REPO/'research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json').read_text());costs=snapshot['costs_bps']
    disabled=PriorTrendGate(False);control=disabled.build()(bound,costs,windows)
    controls=[t for t in control['trades'] if t['partition']=='rolling']
    if controls!=[normalized(t) for t in prior['trades']]:raise ValueError('DISABLED_CONTROL126_NOT_EXACT')
    if [t for t in control['unresolved'] if t['partition']=='rolling']!=prior['unresolved']:raise ValueError('CONTROL_UNRESOLVED_CHANGED')
    save('CONTROL_PARITY.json',{'all126_rows_exact':True,'unresolved_exact':True,'six_full_source_hashes_exact':True,'context_fit_sha256':fitsha})
    print('CONTROL126_EXACT',now(),flush=True)
    enabled=PriorTrendGate(True);child=enabled.build()(bound,costs,windows)
    rows=[t for t in child['trades'] if t['partition']=='rolling'];unresolved=[t for t in child['unresolved'] if t['partition']=='rolling'];boundary=[t for t in child['boundary_excluded'] if t['partition']=='rolling']
    bywindow={w['label']:w for w in windows};prepared={};costed=[]
    for row in rows:
        extra=0.
        if int(row['exit_ts_ms'])-int(row['entry_ts_ms'])>25*h.TF:
            pk=(row['window_label'],row['symbol']);w=bywindow[row['window_label']]
            if pk not in prepared:
                f=bound[row['symbol']];f=f[(f.open_ts_ms>=int(w['start_ms'])-200*h.TF)&(f.close_ts_ms<=int(w['end_ms']))].reset_index(drop=True)
                records,index=h.execution._frame_records(f,30);prepared[pk]=(f,records,index)
            f,records,index=prepared[pk];signal=deepcopy(row['signal']);signal['identity']=h.positive.KELTNER_PARENT;signal['max_hold_bars']=25
            base,opened,_,reason=h.execution._single(signal,f,records,index,costs[row['symbol']],h.positive.exit_update,h.positive.entry_update)
            if base is None or opened or reason:raise ValueError('CARRY_REFERENCE_UNKNOWN')
            extra,detail=accounting.carry_scenario(base,row,snapshot['snapshots'][row['symbol']])
            if extra is None:raise ValueError('CARRY_COST_UNKNOWN')
        t=deepcopy(row);t['cost_bps']+=extra;t['net_bps']=t['gross_bps']-t['cost_bps'];t['management_comparison_identity']=IDENTITY;costed.append(t)
    old={key(t):t for t in saved};new={key(t):t for t in costed}
    if len(old)!=len(saved) or len(new)!=len(costed):raise ValueError('DUPLICATE_TRADE_ID')
    removed=[old[x] for x in sorted(set(old)-set(new))];added=[new[x] for x in sorted(set(new)-set(old))];shared=sorted(set(old)&set(new))
    before,after=compact(saved),compact(costed)
    attr={}
    for mult in (1,2):
        net=lambda t:t['gross_bps']-mult*t['cost_bps']
        common=sum(net(new[x])-net(old[x]) for x in shared)
        delta=sum(map(net,costed))-sum(map(net,saved))
        attribution=common+sum(map(net,added))-sum(map(net,removed))
        if not math.isclose(delta,attribution,abs_tol=1e-7):raise ValueError('DELTA_ATTRIBUTION_MISMATCH')
        attr[f'cost{mult}x']={'net_delta_bps':delta,'removed_losses':sum(net(t)<0 for t in removed),'removed_wins':sum(net(t)>0 for t in removed),
            'avoided_loss_bps':-sum(net(t) for t in removed if net(t)<0),'forgone_winner_bps':sum(net(t) for t in removed if net(t)>0),
            'added_T':len(added),'added_net_bps':sum(map(net,added)),'common_delta_bps':common,'attribution_reconciled':True}
    retention={}
    for label,predicate in [('large_winners',lambda t:t['net_bps']>0 and t['mfe_R']>=2),('ordinary_winners',lambda t:t['net_bps']>0 and t['mfe_R']<2)]:
        keys={key(t) for t in saved if predicate(t)};retention[label]={'baseline_count':len(keys),'retained_count':len(keys&set(new)),
            'baseline_net1x':sum(old[x]['net_bps'] for x in keys),'retained_net1x':sum(new[x]['net_bps'] for x in keys&set(new)),
            'lost_keys':[list(x) for x in sorted(keys-set(new))]}
    validations={}
    for label,result in [('baseline',control),('child',child)]:
        vv=[t for t in result['trades'] if t['partition']=='validation']
        validations[label]={'T':len(vv),'net1x':sum(t['gross_bps']-t['cost_bps'] for t in vv),'net2x':sum(t['gross_bps']-2*t['cost_bps'] for t in vv),
           'unresolved':len([t for t in result['unresolved'] if t['partition']=='validation']),'used_DEV_not_OOS':True}
    serialize=lambda ts:[{'key':list(key(t)),'net1x':t['net_bps'],'net2x':t['gross_bps']-2*t['cost_bps'],'mfe_R':t['mfe_R'],'reason':t['reason']} for t in ts]
    gates=Counter((x['partition'],x['source_gate_reject']) for x in enabled.events)
    declines=[]
    for l in ('cost1x','cost2x'):
        for metric in ('Net_bps','worst_loss_run_bps'):
            if after[l][metric] < before[l][metric]-1e-7:declines.append(l+':'+metric)
        for metric in ('DD_bps','MaxLossStreak'):
            if after[l][metric] > before[l][metric]+1e-7:declines.append(l+':'+metric)
    state='REJECT_NO_JOINT_IMPROVEMENT' if declines else 'RESEARCH_COMPARISON_REQUIRES_INDEPENDENT_VALIDATION'
    result={'at_utc':now(),'candidate':IDENTITY,'baseline_commit':'308bd2deb7acaaacf1adb582206e78262d72c9d1','classification':'ONE_SOURCE_MOTIVATED_USED_DEV_FULL_CHRONOLOGICAL_COMPARISON',
      'source_note_preexisting_20261018_consumed':True,'baseline':before,'child':after,'attribution':attr,'winner_retention':retention,
      'removed':serialize(removed),'added':serialize(added),'child_unresolved':len(unresolved),'boundary_excluded':len(boundary),'validation':validations,
      'source_gate_counts':{str(k):v for k,v in gates.items()},'declines':declines,'disposition':state,'retuned':False,'new_hypotheses':1,
      'new_orders':0,'market_api_calls':0,'protected_files_changed':0,'fresh_OOS':False,'account_NAV_MTM':False,'actual_historical_funding_verified':False,'promotion':False,'S_budget_consumed':0,
      'rows_sha256':save('ROWS.json',{'trades':costed,'unresolved':unresolved,'boundary_excluded':boundary,'gate_events':enabled.events}),
      'control_gate_events_sha256':save('CONTROL_GATE_EVENTS.json',disabled.events)}
    save('SUMMARY.json',result)
    print('COMPLETE',json.dumps({k:result[k] for k in ['at_utc','baseline','child','attribution','winner_retention','disposition']},ensure_ascii=False),flush=True)
if __name__=='__main__':
    try:run()
    except Exception as e:
        if not (S/'FAILURE.json').exists():save('FAILURE.json',{'at_utc':now(),'type':type(e).__name__,'error':str(e),'no_blind_retry':True})
        raise

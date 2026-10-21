"""Execute one frozen new-signal handoff candidate, preserve the successful126T control."""
from copy import deepcopy
from pathlib import Path
from datetime import datetime,timezone
import fcntl,gzip,hashlib,json,os,sys
import handoff_comparison as h
import run_chronological as previous
import run_paired as accounting
from backend.research.rebuild import scalp7_rolling_context_v2 as context
STAGE=Path(__file__).resolve().parent
BASE=h.BASE;REPO=h.REPO

def now():return datetime.now(timezone.utc).isoformat()
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(obj):return (json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def save(name,obj):
    raw=encoded(obj)
    with (STAGE/name).open('xb') as f:f.write(raw)
    return sha(raw)
def key(t):return h.key(t)
def normalized(t):return {k:v for k,v in t.items() if k not in ['management_comparison_identity','control_lineage_identity']}
def compact(rows):
    m=h.k._metrics(rows)
    return {level:{k:m[level][k] for k in ['T','Net_bps','Gross_bps','Cost_bps','PF','WR_pct','DD_bps','MaxLossStreak','T_per_day']} for level in ['cost1x','cost2x']}
def run():
    locks=[]
    for path in [BASE/'paired.lock',STAGE/'economic.lock']:
        f=path.open('a+');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(f)
    if (STAGE/'STARTED.json').exists():raise ValueError('ALREADY_STARTED_NO_DUPLICATE')
    freeze=(STAGE/'FREEZE.json').read_bytes()
    if sha(freeze)!='68e4b995419aea62e6362c01f8a54fd3455c556fde444f8877e8cf9547244b1a':raise ValueError('FREEZE_CHANGED')
    pins=json.loads((STAGE/'CODE_FREEZE.json').read_text())
    for name,pin in pins['sha256'].items():
        if sha((STAGE/name).read_bytes())!=pin:raise ValueError('CODE_CHANGED:'+name)
    base_raw=(BASE/'CHRONO_SUMMARY.json').read_bytes()
    if sha(base_raw)!='beea1d45254694629225755449a09dc7a6efc687b9b402dff9903863f82df9b8':raise ValueError('BASE_SUMMARY_CHANGED')
    base_summary=json.loads(base_raw)
    row_raw=(BASE/'CHRONO_ROWS.json').read_bytes()
    if sha(row_raw)!=base_summary['chronological_rows_sha256']:raise ValueError('BASE_ROWS_CHANGED')
    prior=json.loads(row_raw);saved126=prior['trades'];prior_costed=prior['carry_scenario_trades']
    ctrl=json.loads((BASE/'CONTROL_RESULT.json').read_text());original=ctrl['result']['trade_rows']
    save('STARTED.json',{'utc':now(),'pid':os.getpid(),'owner':'CLOUD_WORK_COORDINATOR_ISSUE1358_V1','new_candidate':1,'S_budget_consumed':0,'rule_sha256':sha(freeze)})
    previous.save=lambda n,v:save('REUSED_'+n,v)
    frames=previous.full_frames()
    old_binding=json.loads((BASE/'CHRONO_SOURCE_BINDING.json').read_text())
    for s,f in frames.items():
        if sha(f.to_csv(index=False).encode())!=old_binding[s]['full_csv_sha256']:raise ValueError('FULL_SOURCE_DRIFT:'+s)
    windows=json.loads((REPO/'research/campaigns/scalp7_20260915/broad_rebuild_v2/CAMPAIGN_PREREGISTERED_V2.json').read_text())['windows']
    bound,fits=context.bind_context(frames,context.cross_features(frames),windows)
    fit_sha=sha(json.dumps(fits,sort_keys=True,separators=(',',':')).encode())
    if fit_sha!=ctrl['context_fit_sha256']:raise ValueError('CONTEXT_FIT_CHANGED')
    save('INPUT_PARITY.json',{'utc':now(),'all6_full_source_hashes_equal':True,'original_context_fit_sha256':fit_sha})
    print('EXACT_SOURCE_AND_CONTEXT_BOUND',now(),flush=True)
    snapshot=json.loads((REPO/'research/campaigns/scalp7_20260915/cost_snapshot_v2/SCALP7_CURRENT_REFERENCE_COST_SNAPSHOT_V2.json').read_text());costs=snapshot['costs_bps']
    disabled=h.Handoff(False);control_function,_=disabled.build();control=control_function(bound,costs,windows)
    control_rows=[t for t in control['trades'] if t['partition']=='rolling']
    if control_rows!=[normalized(t) for t in saved126]:raise ValueError('DISABLED_ADAPTER126_NOT_EXACT')
    if [x for x in control['unresolved'] if x['partition']=='rolling']!=prior['unresolved']:raise ValueError('DISABLED_UNRESOLVED_DRIFT')
    save('CONTROL_PARITY.json',{'utc':now(),'exact126_rows':True,'disabled_handoff_events':len(disabled.events)})
    print('DISABLED126_CONTROL_EXACT',now(),flush=True)
    enabled=h.Handoff(True);child_function,_=enabled.build();result=child_function(bound,costs,windows)
    print('CHILD_CHRONOLOGY_DONE',now(),'HANDOFFS',len(enabled.events),flush=True)
    rows=[t for t in result['trades'] if t['partition']=='rolling']
    unresolved=[t for t in result['unresolved'] if t['partition']=='rolling'];boundary=[t for t in result['boundary_excluded'] if t['partition']=='rolling']
    prepared={};carry_rows=[];carry_trace=[]
    bywindow={w['label']:w for w in windows}
    for row in rows:
        extra=0.;detail={'additional_events':0}
        if int(row['exit_ts_ms'])-int(row['entry_ts_ms'])>25*h.TF:
            w=bywindow[row['window_label']];pk=(row['window_label'],row['symbol'])
            if pk not in prepared:
                f=bound[row['symbol']];f=f[(f.open_ts_ms>=int(w['start_ms'])-200*h.TF)&(f.close_ts_ms<=int(w['end_ms']))].reset_index(drop=True)
                records,index=h.execution._frame_records(f,30);prepared[pk]=(f,records,index)
            f,records,index=prepared[pk];signal=deepcopy(row['signal']);signal['identity']=h.positive.KELTNER_PARENT;signal['max_hold_bars']=25
            base,open_pos,_,reason=h.execution._single(signal,f,records,index,costs[row['symbol']],h.positive.exit_update,h.positive.entry_update)
            if base is None or open_pos is not None or reason is not None:raise ValueError('EXTENDED_ENTRY_REFERENCE_MISSING')
            extra,detail=accounting.carry_scenario(base,row,snapshot['snapshots'][row['symbol']])
            if extra is None:raise ValueError('EXTRA_CARRY_UNKNOWN')
        t=deepcopy(row);t['cost_bps']+=extra;t['net_bps']=t['gross_bps']-t['cost_bps'];carry_rows.append(t)
        if extra or detail.get('additional_events'):carry_trace.append({'key':list(key(t)),'additional_cost_bps':extra,'detail':detail})
    old={key(t):t for t in prior_costed};new={key(t):t for t in carry_rows};original_by={key(t):t for t in original}
    lost=[old[x] for x in sorted(set(old)-set(new))];added=[new[x] for x in sorted(set(new)-set(old))]
    recovered=[new[x] for x in sorted((set(original_by)-set(old))&set(new))]
    cohorts={}
    for label,test in [('original_large35',lambda t:t['mfe_R']>=2),('original_remainder93',lambda t:t['mfe_R']<2)]:
        ids={key(t) for t in original if test(t)}
        cohorts[label]={'baseline_count':len(ids),'prior126_retained_count':len(ids&set(old)),'child_retained_count':len(ids&set(new)),
          'prior126_net1x':accounting.total([old[x] for x in ids&set(old)],1),'child_net1x':accounting.total([new[x] for x in ids&set(new)],1),
          'prior126_net2x':accounting.total([old[x] for x in ids&set(old)],2),'child_net2x':accounting.total([new[x] for x in ids&set(new)],2)}
    shared=sorted(set(old)&set(new));diffs=[]
    for x in shared:
        delta=float(new[x]['net_bps'])-float(old[x]['net_bps'])
        if abs(delta)>1e-9:diffs.append({'key':list(x),'prior_net1x':old[x]['net_bps'],'child_net1x':new[x]['net_bps'],'delta1x':delta,'prior_exit':old[x]['exit_ts_ms'],'child_exit':new[x]['exit_ts_ms']})
    serialize=lambda ts:[{'key':list(key(t)),'net1x':t['net_bps'],'net2x':t['gross_bps']-2*t['cost_bps'],'reason':t['reason']} for t in ts]
    for event in enabled.events:
        nk=tuple(event['new_signal_key'])
        if nk not in new and not any(key(u['position']['signal'])==nk for u in unresolved):raise ValueError('HANDOFF_REPLACEMENT_NOT_ACCOUNTED')
        if nk in new and new[nk]['entry_ts_ms']!=event['old_close_ts_ms']:raise ValueError('HANDOFF_OVERLAP_OR_DELAY')
    rows_sha=save('ROWS.json',{'trades':rows,'carry_scenario_trades':carry_rows,'unresolved':unresolved,'boundary_excluded':boundary,'handoffs':enabled.events})
    summary={'schema':'zel.keltner.winner_fresh_signal_handoff.result.v1','completed_at_utc':now(),'owner':'CLOUD_WORK_COORDINATOR_ISSUE1358_V1',
      'prior_result_commit':'308bd2deb7acaaacf1adb582206e78262d72c9d1','candidate_identity':'scalp7_keltner_extended_fresh_signal_handoff_v1',
      'rule_sha256':sha(freeze),'rows_sha256':rows_sha,'source_hash_parity':True,'context_fit_sha256':fit_sha,'disabled126_exact':True,
      'old128_metrics':compact(original),'prior126_metrics':compact(prior_costed),'child_metrics':compact(carry_rows),
      'child_all_metrics':h.k._metrics(carry_rows),'child_unresolved':len(unresolved),'child_boundary_excluded':len(boundary),
      'net_delta1x':accounting.total(carry_rows,1)-accounting.total(prior_costed,1),'net_delta2x':accounting.total(carry_rows,2)-accounting.total(prior_costed,2),
      'handoff_count':len(enabled.events),'handoffs':enabled.events,'cohorts':cohorts,'lost_vs126':serialize(lost),'added_vs126':serialize(added),
      'recovered_vs128_keys':serialize(recovered),'changed_common_trades':diffs,'additional_carry_trace':carry_trace,
      'attribution_check_delta1x':sum(t['delta1x'] for t in diffs)+accounting.total(added,1)-accounting.total(lost,1),
      'new_candidates_evaluated':1,'S_budget_consumed':0,'parameter_sweep':False,'raw_market_api':0,'paid_api':0,'orders':0,
      'used_dev_not_oos':True,'actual_historical_funding':False,'account_nav_mtm':False,'promotion':False,'current_shadow_changes':0,
      'disposition':'PRESERVE_FOR_INDEPENDENT_REVIEW' if accounting.total(carry_rows,2)>accounting.total(prior_costed,2) and accounting.total(carry_rows,1)>accounting.total(prior_costed,1) else 'REJECT_INCREMENTAL_HANDOFF_KEEP126_WINNER_EXTENSION'}
    if abs(summary['attribution_check_delta1x']-summary['net_delta1x'])>1e-7:raise ValueError('ATTRIBUTION_MISMATCH')
    digest=save('SUMMARY.json',summary)
    print('COMPLETE',now(),'SUMMARY_SHA256',digest,flush=True)
    print(json.dumps({x:summary[x] for x in ['prior126_metrics','child_metrics','net_delta1x','net_delta2x','handoff_count','recovered_vs128_keys','lost_vs126','added_vs126','child_unresolved','cohorts','disposition']},ensure_ascii=False),flush=True)
if __name__=='__main__':
    try:run()
    except Exception as exc:
        if not (STAGE/'FAILURE.json').exists():save('FAILURE.json',{'utc':now(),'error':type(exc).__name__,'message':str(exc)})
        raise

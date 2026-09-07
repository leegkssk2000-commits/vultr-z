"""Two frozen user hypotheses, serial execution, sealed parents and exact replay."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import gzip
import json
import os
from pathlib import Path
import time
from backend.research.rebuild import parallel_exit_dev_v1 as account
from backend.research.rebuild import keltner_m2_study_v1 as m2study
from backend.research.rebuild import keltner_kr1_v1 as kr
from backend.research.rebuild import q0_qf1_v1 as qf
from backend.research.rebuild import top5_sprint_metrics_v1 as metrics

old, ROOT = account.old, account.ROOT
OUTPUT = 'research/development_evidence/TOP5_PERFORMANCE_SPRINT_20260907_V1'
SPEC = OUTPUT+'/SPEC.json'
CODE = ['backend/research/rebuild/'+s+'_v1.py' for s in (
    'keltner_kr1','q0_qf1','top5_sprint_metrics','top5_performance_sprint','test_top5_performance_sprint')]
RULES = {
    'KR1': 'PR1200 M2; i=signal,H=12,t=i+H. After prior D/M2 exit checks at completed t-1, if alive and close>actual_entry and close>EMA20>EMA50, allow one additional H. Otherwise original t CLOSE timeout. From t, close<=EMA20 queues next observed open strictly before end. D then allowed M2 then runner priority. SUPPRESSED never rearms. Final i+24 CLOSE timeout strictly before end; pending/censored otherwise. Original M entry/upper-half/EMA seed/D causal reservations unchanged. Actual slot admits only original M2 eligible signal whose close is strictly after actual exit timestamp; same-time signals blocked, later close after an exit-open is free. No future exit price enters admission. Fixed=M2 independent paths, may overlap; FULL actual-slot replay is primary.',
    'QF1': 'Q0 A preparation=true, no B. Original generator UP only: confirmation_close>daily[anchor_daily_index].close. Equal/lower reject that UP; no restart/state mutation. DOWN/SL/gap/next-open/cancel/occupancy unchanged. Fixed=original Q0 admitted UP opportunities and all DOWN; FULL=all original signals after one admission test. No D reference transplanted.',
    'cost': account.RULES['cost'], 'evidence': account.RULES['evidence'],
    'new_design_assumptions': 'USER_SPRINT_PROPOSAL: one additional H cap and strict positive confirmation progress; not optimized facts or formal gates.',
}
OWNERS = {'KR1':'backend.research.rebuild.parallel_exit_metrics_v1.compare',
          'QF1':'backend.research.rebuild.keltner_cumulative_entry_metrics_v1.compare'}
GOALS = {'KR1':metrics.exits.GOAL,'QF1':metrics.entries.GOAL}
AUTH = {**account.AUTH, 'execution_authority':'NONE', 'promotion_authority':False,
        'selection_authority':False,'automatic_workcopy_replacement':False,
        'prior32_preserved':True, 'formal_credit':0}


def log(phase, **kw):
    print(json.dumps({'phase':phase,'utc':datetime.now(timezone.utc).isoformat(),
        'pid':os.getpid(),'github_run_id':os.environ.get('GITHUB_RUN_ID'),**kw}),flush=True)


def authorize():
    c=old.read(SPEC); old.probe.verify_seal(c,'SPRINT_SPEC')
    if (c['rules']!=RULES or c['decision_owners']!=OWNERS or c['goals']!=GOALS
            or c['calendars']!=account.CALENDARS or c['outcomes_seen_at_freeze'] is not False
            or c['budget']!={'prior_candidates':32,'new_maximum':2,'per_candidate':1,'automatic_extension':False}
            or set(c['code_files_sha256'])!=set(CODE)):
        raise RuntimeError('SPRINT_FROZEN_SCOPE_DRIFT')
    for k,v in AUTH.items():
        if c.get(k)!=v: raise RuntimeError('SPRINT_AUTHORITY:'+k)
    for path,sha in {**c['code_files_sha256'],**c['preserved_files_sha256'],**c['ci_files_sha256'],**c['design_files_sha256']}.items():
        if old.file_sha(ROOT/path)!=sha: raise RuntimeError('SPRINT_FROZEN_BYTES:'+path)
    for k in ('symbols','cost_sha256','data_sha256','period_data_sha256'):
        if c[k]!=old.read(m2study.SPEC)[k]: raise RuntimeError('SPRINT_PARENT_INPUT:'+k)
    for path,seal in c['parent_receipts'].items():
        r=old.read(path); old.probe.verify_seal(r,'SPRINT_PARENT')
        if r['receipt_sha256']!=seal: raise RuntimeError('SPRINT_PARENT_SEAL:'+path)
    return c


def read_artifact(receipt_path, key):
    r=old.read(receipt_path); old.probe.verify_seal(r,'SPRINT_STORED')
    a=r['artifacts'][key]; path=ROOT/a['path']
    if old.file_sha(path)!=a['file_sha256']: raise RuntimeError('SPRINT_STORED_ARTIFACT:'+key)
    return json.loads(gzip.decompress(path.read_bytes()))


def parents(kind,period):
    if kind=='KR1':
        a=read_artifact(m2study.OUTPUT+'/receipt.json',period)
        b=read_artifact(m2study.m.OUTPUT+'/receipt.json',period)
        return {'M':b['views']['M'],'M2':a['M2_full']}, {'M':a['record']['stages']['M'],'M2':a['record']['stages']['M2']}
    if period=='SEEN2026':
        p=read_artifact(account.seen_run.OUTPUT+'/receipt.json','unit_execution')
    else:
        r=old.read(account.source.OUTPUT+'/receipt.json')
        p=account.seen_run.original.load_parent(r)
    return {'Q0':p}, {}


def artifact(kind,name,value,verify):
    path=ROOT/OUTPUT/kind/name; raw=old.probe.canonical(value)
    payload=path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
    if gzip.decompress(payload)!=raw: raise RuntimeError('SPRINT_EXACT_REPLAY_DRIFT:'+str(path))
    old.probe.write_immutable(path,payload,verify_only=verify)
    return {'path':str(path.relative_to(ROOT)),'file_sha256':old.file_sha(path)}


def replay(kind,rows_by,bundles,policy,costs,start,end,*,fixed=None):
    result={k:[] for k in ('trades','open_observations','events','trace')}
    result.update(admission={},reference_states={},reference_events=[],reference_opportunities=[])
    for symbol,rows in sorted(rows_by.items()):
        indices=None if fixed is None else fixed[symbol]
        if kind=='KR1':
            raw=kr.replay(rows,bundles[symbol],eval_start_ms=start,eval_end_ms=end,fixed_signal_indices=indices)
            result['reference_states'][symbol]=raw['reference_checkpoint']
            for key in ('reference_events','reference_opportunities'):
                result[key].extend(dict(t,symbol=symbol) for t in raw[key])
        else:
            daily,bundle=bundles[symbol]
            raw=qf.replay(rows,daily,bundle,eval_start_ms=start,eval_end_ms=end,fixed_signal_indices=indices)
        v=account.charge_result(raw,symbol,'keltner_trend_main' if kind=='KR1' else account.source.LANE,
            kind,policy,costs,rows)
        for key,seal in (('trades','trade_sha256'),('open_observations','observation_sha256')):
            for t in v[key]:
                t.pop(seal,None);t.update(candidate_id=kr.RULE_ID if kind=='KR1' else qf.RULE_ID,
                    comparison_type='EXIT_CHANGE' if kind=='KR1' else 'ENTRY_FILTER',
                    evidence_type='REUSED_DEV_TOP5_PERFORMANCE_SPRINT')
                t[seal]=old.digest(t)
        for key in ('trades','open_observations','events','trace'): result[key].extend(v[key])
        result['admission'][symbol]=raw['audit']
    return result


def verify_relationships(kind,parent,fixed,full):
    p,f,c=map(metrics.index,(parent,fixed,full))
    if kind=='KR1':
        if p.keys()!=f.keys() or not c.keys()<=p.keys(): raise RuntimeError('KR1_M2_ORIGIN_SET_DRIFT')
        if parent['reference_states']!=full['reference_states']: raise RuntimeError('KR1_D_CLOCK_DRIFT')
        for origin in c:
            for k in ('entry_ts','entry_price','signal_index'):
                if c[origin][1][k]!=p[origin][1][k]: raise RuntimeError('KR1_M2_ENTRY_DRIFT:'+k)
        for symbol in full['admission']:
            positions=sorted([item for item in c.values() if item[1]['symbol']==symbol],key=lambda item:item[1]['entry_ts'])
            for a,b in zip(positions,positions[1:]):
                if a[0]!='C' or a[1]['exit_ts']>=b[1]['signal_ts']: raise RuntimeError('KR1_ACTUAL_SLOT_OVERLAP')
    else:
        if not f.keys()<=p.keys(): raise RuntimeError('QF1_FIXED_NEW_ORIGIN')
        for origin in f:
            a,b=p[origin],f[origin]
            if a[0]!=b[0]: raise RuntimeError('QF1_FIXED_STATUS_DRIFT')
            for k in ('entry_ts','entry_price','hold_ms','exit_ts','exit_price','mark_ts','mark_price'):
                if a[1].get(k)!=b[1].get(k): raise RuntimeError('QF1_FIXED_Q0_PATH_DRIFT:'+k)
            for k in metrics.exits.VALUE_FIELDS:
                metrics.bridge._same(metrics.bridge._values(a)[k],metrics.bridge._values(b)[k],'QF1_FIXED_COST_PARITY:'+k)


def report(r):
    lines=['# '+r['candidate']+' frozen DEV economics','',
        'Equal nominal trade-bps; terminal includes hypothetical full-cost open marks. Neither account returns nor independent validation. FULL is primary; FIXED is a diagnostic. Parent ledgers reused, Q0 daily marks revalued exactly without replaying its signals.','']
    for period,doc in r['results'].items():
        names=list(doc['values'])
        lines+=['## '+period,'','| Metric | '+' | '.join(names)+' |','|---|'+'---:|'*len(names)]
        for key in doc['values'][names[0]]:
            fmt=lambda x:'NA' if x is None else f'{x:.6f}'
            lines.append('| '+key+' | '+' | '.join(fmt(doc['values'][n][key]) for n in names)+' |')
        lines+=['','Decisions: '+json.dumps({k:v['decision'] for k,v in doc['decisions'].items()}),
            '', 'Full attribution, winner damage, fixed/full occupancy bridge, concentration and unchanged uncertainty:',
            '','```json',json.dumps({k:doc[k] for k in ('effects','occupancy_bridge_summary','uncertainty','concentration','partial_assets')},indent=2),'```']
    lines+=['','No automatic adoption or further candidate is authorized. Old verdicts, Q0 observer, G5B and prior budgets are preserved.']
    return ('\n'.join(lines)+'\n').encode()


def run(kind,data_dir,verify=False):
    c=authorize(); out=ROOT/OUTPUT/kind; out.mkdir(parents=True,exist_ok=True)
    receipt=out/'receipt.json'; attempt=out/'ATTEMPT.json'
    if not verify and (receipt.exists() or attempt.exists()): raise RuntimeError('SPRINT_ALREADY_ATTEMPTED_RECOVER_DO_NOT_REPEAT')
    if verify and not receipt.exists(): raise RuntimeError('SPRINT_NO_RECEIPT_FOR_REPRODUCTION')
    base_policy,costs,period_rows,access=account.load_inputs(Path(data_dir),c)
    stored={p:parents(kind,p) for p in ('DEV2025','SEEN2026')}
    tick=time.monotonic()
    if not verify:
        prior=[old.read(str(p.relative_to(ROOT))) for p in (ROOT/OUTPUT).glob('*/ATTEMPT.json')]
        if len(prior)>=2: raise RuntimeError('SPRINT_TWO_CANDIDATE_BUDGET_EXHAUSTED')
        ordinal=33+len(prior)
        marker=old.seal({**AUTH,'candidate':kind,'ordinal':ordinal,'spec_seal':c['receipt_sha256'],
            'utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),
            'github_run_id':os.environ.get('GITHUB_RUN_ID'),'started_before_first_candidate_market_path':True,
            'failed_execution_also_consumes_trial':True})
        old.probe.write_immutable(attempt,old.probe.canonical(marker))
    else:
        marker=old.read(str(attempt.relative_to(ROOT))); old.probe.verify_seal(marker,'SPRINT_ATTEMPT')
        if marker['spec_seal']!=c['receipt_sha256'] or marker['candidate']!=kind: raise RuntimeError('SPRINT_ATTEMPT_BINDING')
        ordinal=marker['ordinal']
    log('EXACT_REPRODUCTION_START' if verify else 'NEW_CANDIDATE_START',candidate=kind,ordinal=ordinal,spec=c['receipt_sha256'])
    results, artifacts = {}, {}
    for period,source_rows in period_rows.items():
        start,end=c['calendars']['KELTNER' if kind=='KR1' else 'Q0'][period]
        rows={s:[r for r in rr if r['bar_close_ts']<=end] for s,rr in source_rows.items()}
        policy={**base_policy,'batch_id':Path(OUTPUT).name,'receipt_sha256':c['receipt_sha256'],
            'code_files_sha256':c['code_files_sha256'],'development_interval_ms':[start,end],
            'combined_data_sha256':c['period_data_sha256'][period]}
        views,stages=deepcopy(stored[period]); parent_name='M2' if kind=='KR1' else 'Q0'; parent=views[parent_name]
        with old.probe.io_boundary([],out):
            log('PERIOD_START',candidate=kind,period=period)
            bundles={s:kr.parent.build_bundle(rr,kr.d.PARENT_SPEC,eval_start_ms=start,eval_end_ms=end)
                if kind=='KR1' else qf.build_bundle(rr,start,end) for s,rr in rows.items()}
            origins={s:[t['signal_index'] for k in ('trades','open_observations') for t in parent[k] if t['symbol']==s] for s in rows}
            full=replay(kind,rows,bundles,policy,costs,start,end)
            fixed=replay(kind,rows,bundles,policy,costs,start,end,fixed=origins)
            verify_relationships(kind,parent,fixed,full)
            views.update({kind+'_FIXED':fixed,kind+'_FULL':full})
            for name,view in views.items():
                if name not in stages:
                    stages[name]=metrics.exits.build_stage(view['trades'],view['open_observations'],view['events'],rows,costs,policy,c['symbols'],start,end)
            comparisons={name:metrics.compare(kind,stages[parent_name],stages[name],parent,views[name],rows,costs,start,end)
                for name in (kind+'_FIXED',kind+'_FULL')}
            if kind=='KR1': comparisons['KR1_FULL_vs_M']=metrics.compare(kind,stages['M'],stages[kind+'_FULL'],views['M'],full,rows,costs,start,end)
            effect={name:metrics.effects(view,full) for name,view in views.items() if name in ('M','M2','Q0')}
            occupancy=metrics.fixed_full_bridge(parent,fixed,full)
            values={name:metrics.stage_values(s) for name,s in stages.items()}
        # Retain every row in compressed artifact; concise receipt omits per-origin rows only.
        doc={'period':period,'candidate':kind,'views':views,'stages':stages,'comparisons':comparisons,
             'effects':effect,'fixed_full_bridge':occupancy,'values':values,'relationship_parity':'PASS'}
        artifacts[period]=artifact(kind,period+'.json.gz',doc,verify)
        compact=deepcopy(effect)
        for e in compact.values():e.pop('per_origin')
        delta=occupancy['terminal']['net_bps']['full_total_effect']
        child_values=values[kind+'_FULL']
        results[period]={'values':values,'decisions':{n:v['decision'] for n,v in comparisons.items()},
            'effects':compact,'occupancy_bridge_summary':occupancy['terminal'],
            'uncertainty':{n:v['uncertainty'] for n,v in comparisons.items()},
            'concentration':{n:{'profit':s['metrics']['concentration'],
                'market_event_weekly_clusters':s['diagnostics']['weekly_clusters'],
                'same_time_close_cohorts':s['closed_loss_cohorts']} for n,s in stages.items()},
            'partial_assets':{'full_terminal_increment_positive':delta>0,'full_terminal_base_positive':child_values['terminal_net_bps_hypothetical']>0,
                'full_terminal_cost2_positive':child_values['terminal_cost2x_net_bps_hypothetical']>0,
                'preserve_branch_as_development_evidence':True,'formal_or_operating_adoption':False},
            'admission':full['admission']}
        log('PERIOD_COMPLETE',candidate=kind,period=period,values=values,decision=results[period]['decisions'],elapsed_seconds=round(time.monotonic()-tick,2))
    r=old.seal({**AUTH,'schema':'top5.performance.sprint.result.v1','candidate':kind,'candidate_ordinal':ordinal,
        'spec_seal':c['receipt_sha256'],'new_candidates_measured':1,'candidate_period_applications':2,
        'parent_receipts':c['parent_receipts'],'results':results,'artifacts':artifacts,'source_access':access,
        'decoded_after_20260905_00UTC':0,'prior_independent':'0/1_NOT_RUN','prior_seen':'1/1_PRESERVED',
        'qualification_additional':'0/1_PRESERVED','same_result_reproduction_is_new_candidate':False})
    old.probe.write_immutable(receipt,old.probe.canonical(r),verify_only=verify)
    old.probe.write_immutable(out/'RESULTS.md',report(r),verify_only=verify)
    log('COMPLETE',candidate=kind,result_seal=r['receipt_sha256'],elapsed_seconds=round(time.monotonic()-tick,2))
    return r


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--candidate',choices=['KR1','QF1']);parser.add_argument('--data-dir')
    parser.add_argument('--verify-only',action='store_true');args=parser.parse_args()
    if args.check_only:
        c=authorize();log('PASS_FREEZE',spec=c['receipt_sha256']);return
    if not args.candidate or not args.data_dir: parser.error('--candidate and --data-dir required')
    # One local writer across both candidates. CI verifies serially on its own checkout.
    lock=Path('/tmp')/('top5-performance-'+old.digest(str(ROOT))+'.lock')
    with lock.open('w') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try: run(args.candidate,args.data_dir,args.verify_only)
        except Exception as exc:
            log('FAILED',candidate=args.candidate,error=repr(exc))
            out=ROOT/OUTPUT/args.candidate
            if not args.verify_only and (out/'ATTEMPT.json').exists():
                old.probe.write_immutable(out/'FAILURE.json',old.probe.canonical({'candidate':args.candidate,
                    'error':repr(exc),'utc':datetime.now(timezone.utc).isoformat(),'trial_consumed':True}))
            raise


if __name__=='__main__': main()

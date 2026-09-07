"""A bundle: frozen KR2/SR1/BR1, sole serial writer and immutable receipts."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import gzip
import json
import os
from pathlib import Path
import time
from backend.research.rebuild import top5_performance_sprint_v1 as prior
from backend.research.rebuild import keltner_kr2_v1 as kr2
from backend.research.rebuild import top5_finite_runner_4h_v1 as finite

account, metrics, old, ROOT = prior.account, prior.metrics, prior.old, prior.ROOT
OUTPUT = 'research/development_evidence/TOP5_MECHANISM_A_20260907_V1'
SPEC = OUTPUT+'/SPEC.json'
ORDER = ['KR2','SR1','BR1']
CODE = ['backend/research/rebuild/'+n+'_v1.py' for n in
        ('keltner_kr2','top5_finite_runner_4h','top5_mechanism_a','test_top5_mechanism_a')]
AUTH = {**prior.AUTH, 'prior34_preserved':True, 'G5_DEV_NO_CREDIT':True}
RULES = {
 'KR2':'Exact PR1201 KR1_FULL. At original allowed extension decision t-1 freeze that completed low once. Only j>=original t, close<anchor schedules next open. Original D then M2 then KR1 runner priorities and native/final close cap unchanged; anchor last. Same D causal reference and actual slot; FIXED=KR1 origins, FULL admits causal eligible signals, never stored future exits.',
 'SR1':'Exact supertrend_replacement_highvol_mom_long_4h_h12_v2 DSL, long next open. H12, native exit=i+H CLOSE. At t-1 close>actual entry and close>EMA20>EMA50 extends exactly H once. In extension close<=EMA20 or EMA20<=EMA50 schedules next open. Native final cap before new close orders, strict-end, native exit-bar ownership. No SL/TP in parent; none added.',
 'BR1':'Exact break_replacement_breakout50_long_4h_h6_v2 DSL, long next open. Same SR1 procedure with native H6. Preserve breakout50 and volume1.1. Separate V2 research, not Q0 replacement/reset. No SL/TP in parent; none added.',
 'accounting':account.RULES['cost'], 'data':account.RULES['evidence'],
 'decision':'Reuse parallel_exit_metrics_v1.compare and GOAL unchanged, descriptive absolute/increment/risk/evidence separate. No formal adoption. Same two reused calendars; cross-lane reuse independent=false.'}


def log(phase, **kw):
    print(json.dumps({'phase':phase,'utc':datetime.now(timezone.utc).isoformat(),
        'pid':os.getpid(),'github_run_id':os.environ.get('GITHUB_RUN_ID'),**kw}),flush=True)


def authorize():
    prior.authorize()
    c=old.read(SPEC); old.probe.verify_seal(c,'MECHANISM_A_SPEC')
    if (c['rules']!=RULES or c['goals']!=metrics.exits.GOAL or c['order']!=ORDER
        or c['budget']!={'prior':34,'A_max':3,'B_reserved':2,'total_max':5}
        or set(c['code_files_sha256'])!=set(CODE)
        or c['new_outcomes_seen_at_freeze'] is not False
        or c['calendars']!=account.CALENDARS['KELTNER']):
        raise RuntimeError('MECHANISM_SCOPE_DRIFT')
    for k,v in AUTH.items():
        if c.get(k)!=v: raise RuntimeError('MECHANISM_AUTHORITY:'+k)
    for path,sha in {**c['code_files_sha256'],**c['preserved_files_sha256'],**c['ci_files_sha256']}.items():
        if old.file_sha(ROOT/path)!=sha: raise RuntimeError('MECHANISM_FROZEN_BYTES:'+path)
    return c


def parents(period):
    doc=prior.read_artifact(prior.OUTPUT+'/KR1/receipt.json',period)
    return ({n:doc['views'][n] for n in ('M','M2','KR1_FULL')},
            {n:doc['stages'][n] for n in ('M','M2','KR1_FULL')})


def replay(kind,rows_by,bundles,policy,costs,start,end,enabled=True,fixed=None):
    result={k:[] for k in ('trades','open_observations','events','trace')}
    result.update(admission={},reference_states={})
    lane='keltner_trend_main' if kind=='KR2' else {'SR1':'supertrend_pullback_main','BR1':'break_and_continue_main'}[kind]
    for symbol,rows in sorted(rows_by.items()):
        kw={'eval_start_ms':start,'eval_end_ms':end,
            'fixed_signal_indices':None if fixed is None else fixed[symbol], 'enabled':enabled}
        raw=kr2.replay(rows,bundles[symbol],**kw) if kind=='KR2' else finite.replay(rows,bundles[symbol],kind=kind,**kw)
        view=account.charge_result(raw,symbol,lane,kind if enabled else 'P',policy,costs,rows)
        for key in ('trades','open_observations','events','trace'): result[key].extend(view[key])
        result['admission'][symbol]=raw['audit']
        if kind=='KR2': result['reference_states'][symbol]=raw['reference_checkpoint']
    return result


def parity(kind,period,parent,fixed,full):
    p,f,c=map(metrics.index,(parent,fixed,full))
    if p.keys()!=f.keys(): raise RuntimeError('FIXED_PARENT_ORIGINS_DRIFT')
    for origin in p:
        for key in ('entry_ts','entry_price','signal_index','side'):
            if p[origin][1][key]!=f[origin][1][key]: raise RuntimeError('FIXED_ENTRY_DRIFT:'+key)
    if kind=='KR2' and parent['reference_states']!=full['reference_states']:
        raise RuntimeError('KR2_D_REFERENCE_DRIFT')
    if kind!='KR2' and period=='DEV2025':
        lane=finite.specification(kind)['lane_id']
        saved=[t for t in account.source.inputs.read_lines(ROOT/old.OUTPUT/'baseline/trades.jsonl.gz') if t['lane_id']==lane]
        key=lambda t:(t['symbol'],t['signal_ts'],t['side'])
        a,b=({key(t):t for t in rows} for rows in (parent['trades'],saved))
        if a.keys()!=b.keys(): raise RuntimeError('V2_STORED_PARENT_ORIGINS')
        for origin in a:
            for field in ('entry_ts','exit_ts','entry_price','exit_price','net_bps','gross_bps','cost_bps','funding_bps','hold_ms'):
                if a[origin][field]!=b[origin][field]: raise RuntimeError('V2_STORED_PARENT_PARITY:'+field)
    for symbol in full['admission']:
        ordered=sorted([x for x in c.values() if x[1]['symbol']==symbol],key=lambda x:x[1]['entry_ts'])
        for a,b in zip(ordered,ordered[1:]):
            if a[0]!='C' or a[1]['exit_ts']>=b[1]['signal_ts']: raise RuntimeError('FULL_ACTUAL_OVERLAP')
    return 'PASS_FIXED_ENTRY_STORED_PARENT_AND_FULL_OCCUPANCY'


def artifact(kind,period,doc,verify):
    path=ROOT/OUTPUT/kind/(period+'.json.gz'); raw=old.probe.canonical(doc)
    payload=path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
    if gzip.decompress(payload)!=raw: raise RuntimeError('MECHANISM_EXACT_DRIFT:'+kind+period)
    old.probe.write_immutable(path,payload,verify_only=verify)
    return {'path':str(path.relative_to(ROOT)),'file_sha256':old.file_sha(path)}


def run(kind,data_dir,verify=False):
    c=authorize(); out=ROOT/OUTPUT/kind; out.mkdir(parents=True,exist_ok=True)
    rp=out/'receipt.json'; ap=out/'ATTEMPT.json'
    if not verify and (rp.exists() or ap.exists()):
        log('DUPLICATE_NO_OP',candidate=kind); return None
    if verify and not rp.exists(): raise RuntimeError('NO_COMMITTED_RECEIPT')
    base_policy,costs,periods,access=account.load_inputs(Path(data_dir),c)
    stored={p:parents(p) for p in periods} if kind=='KR2' else {}
    if not verify:
        attempted=[k for k in ORDER if (ROOT/OUTPUT/k/'ATTEMPT.json').exists()]
        if kind!=ORDER[len(attempted)]: raise RuntimeError('SERIAL_FROZEN_ORDER')
        marker=old.seal({'candidate':kind,'ordinal':35+len(attempted),'spec_seal':c['receipt_sha256'],
            'utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),
            'github_run_id':os.environ.get('GITHUB_RUN_ID'),'before_first_market_path':True,
            'failed_execution_consumes_trial':True})
        old.probe.write_immutable(ap,old.probe.canonical(marker))
    else:
        marker=old.read(str(ap.relative_to(ROOT)));old.probe.verify_seal(marker,'ATTEMPT')
        if marker['spec_seal']!=c['receipt_sha256']: raise RuntimeError('ATTEMPT_FREEZE_DRIFT')
    log('EXACT_REPRODUCTION_START' if verify else 'NEW_CANDIDATE_START',candidate=kind,ordinal=marker['ordinal'])
    results={}; artifacts={}; tick=time.monotonic()
    for period,rows in periods.items():
        start,end=c['calendars'][period]
        policy={**base_policy,'batch_id':Path(OUTPUT).name,'receipt_sha256':c['receipt_sha256'],
                'code_files_sha256':c['code_files_sha256'],'development_interval_ms':[start,end],
                'combined_data_sha256':c['period_data_sha256'][period]}
        bundles={s:kr2.parent.build_bundle(rr,kr2.d.PARENT_SPEC,eval_start_ms=start,eval_end_ms=end)
                 if kind=='KR2' else finite.build_bundle(rr,finite.specification(kind)['executable_spec'],start,end)
                 for s,rr in rows.items()}
        views,stages=deepcopy(stored[period]) if kind=='KR2' else ({}, {})
        pname='KR1_FULL' if kind=='KR2' else 'P'
        if kind!='KR2': views['P']=replay(kind,rows,bundles,policy,costs,start,end,enabled=False)
        parent=views[pname]
        origins={s:[t['signal_index'] for k in ('trades','open_observations') for t in parent[k] if t['symbol']==s] for s in rows}
        with old.probe.io_boundary([],out):
            fixed=replay(kind,rows,bundles,policy,costs,start,end,fixed=origins)
            full=replay(kind,rows,bundles,policy,costs,start,end)
            views.update(FIXED=fixed,FULL=full)
        relationship=parity(kind,period,parent,fixed,full)
        for name,view in views.items():
            if name not in stages:
                stages[name]=metrics.exits.build_stage(view['trades'],view['open_observations'],view['events'],rows,costs,policy,c['symbols'],start,end)
        comparisons={name:metrics.exits.compare(stages[pname],stages[name],parent['trades'],parent['open_observations'],
                     views[name]['trades'],views[name]['open_observations'],rows,costs,start,end) for name in ('FIXED','FULL')}
        effects={name:metrics.effects(view,full) for name,view in views.items() if name not in ('FIXED','FULL')}
        bridge=metrics.fixed_full_bridge(parent,fixed,full)
        values={name:metrics.stage_values(s) for name,s in stages.items()}
        doc={'candidate':kind,'period':period,'views':views,'stages':stages,'comparisons':comparisons,
             'effects':effects,'fixed_full_bridge':bridge,'values':values,'relationship_parity':relationship}
        artifacts[period]=artifact(kind,period,doc,verify)
        compact=deepcopy(effects)
        for v in compact.values():v.pop('per_origin')
        results[period]={'values':values,'decisions':{n:v['decision'] for n,v in comparisons.items()},
            'effects':compact,'occupancy_bridge_summary':bridge['terminal'],
            'uncertainty':{n:v['uncertainty'] for n,v in comparisons.items()},
            'concentration':{n:{'profit':s['metrics']['concentration'],'market_event_weekly_clusters':s['diagnostics']['weekly_clusters'],
               'same_time_close_cohorts':s['closed_loss_cohorts']} for n,s in stages.items()},
            'partial_assets':{'preserve_development_evidence':True,'formal_or_operating_adoption':False},
            'admission':full['admission'],'relationship_parity':relationship}
        log('PERIOD_COMPLETE',candidate=kind,period=period,values=values,decisions=results[period]['decisions'],elapsed_seconds=round(time.monotonic()-tick,2))
    receipt=old.seal({**AUTH,'schema':'top5.mechanism.a.result.v1','candidate':kind,
        'candidate_ordinal':marker['ordinal'],'spec_seal':c['receipt_sha256'],'results':results,'artifacts':artifacts,
        'parent_id':'KR1_FULL' if kind=='KR2' else finite.PARENTS[kind],
        'source_access':access,'decoded_after_20260905_00UTC':0,'same_result_reproduction_is_new_candidate':False,
        'execution_inventory':{'periods':list(periods),'new_parent_baselines':0 if kind=='KR2' else 2,
                               'candidate_FIXED':2,'candidate_FULL':2,'old_experiments_rerun':0}})
    old.probe.write_immutable(rp,old.probe.canonical(receipt),verify_only=verify)
    report=prior.report(receipt).replace(b'Parent ledgers reused, Q0 daily marks revalued exactly without replaying its signals.', b'KR1/M/M2 ledgers reused. SR1/BR1 V2 baselines computed only for these authorized comparisons. Q0 is preserved without replay or replacement.')
    old.probe.write_immutable(out/'RESULTS.md',report,verify_only=verify)
    log('COMPLETE',candidate=kind,result_seal=receipt['receipt_sha256'])
    return receipt


def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',choices=ORDER);p.add_argument('--data-dir')
    p.add_argument('--check-only',action='store_true');p.add_argument('--verify-only',action='store_true');a=p.parse_args()
    if a.check_only: log('FREEZE_PASS',seal=authorize()['receipt_sha256']);return
    if not a.candidate or not a.data_dir:p.error('candidate and data-dir required')
    with Path('/tmp/top5-mechanism-sole-writer.lock').open('w') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:run(a.candidate,a.data_dir,a.verify_only)
        except Exception as exc:
            log('FAILED',candidate=a.candidate,error=repr(exc))
            raise


if __name__=='__main__':main()

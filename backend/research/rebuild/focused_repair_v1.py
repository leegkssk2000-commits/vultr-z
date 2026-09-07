"""Two preregistered focused DEV repairs; stored parents and one serial writer."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import fcntl
import gzip
import json
import os
from pathlib import Path
from backend.research.rebuild import top5_mechanism_a_v1 as a
from backend.research.rebuild import top5_mechanism_b_v1 as b
from backend.research.rebuild import keltner_kr3_v1 as kr
from backend.research.rebuild import break_br2_v1 as br

old,account,metrics,ROOT=a.old,a.account,a.metrics,a.ROOT
OUTPUT='research/development_evidence/FOCUSED_REPAIR_20260907_V1'
SPEC=OUTPUT+'/SPEC.json'
ORDER=['KR3','BR2']
CODE=['backend/research/rebuild/'+x+'_v1.py' for x in
      ('keltner_kr3','break_br2','focused_repair','test_focused_repair','focused_repair_diagnosis')]
RULES={
 'KR3':'Exact KR1_FULL. At the original t-1 extension decision only, veto extension if the already observed M2 first-breach state is LOW_EXIT_SUPPRESSED_FOR_THIS_POSITION. All other KR1 eligibility, M2 and trend exits, next-open timing, native/final close caps, causal D reservations and actual slot remain unchanged. No later state or final outcome input.',
 'BR2':'Exact BR1 FULL. Only after the actual extended final-cap close at original signal index+12 is filled, admit an existing eligible signal on that completed bar at the next actual open. Never displace a live position; never reset the old hold cap. Native unextended and early-exit bar ownership remains unchanged. Each new position pays its own full costs and has its own original H6 / at-most-one H6 extension. FIXED paths remain exactly BR1.',
 'comparison':'Stored M/M2/KR1/KR2 and V2/BR1 parents; candidate FIXED on preserved workcopy origins and FULL on native signal tape. FIXED overlap is diagnostic only. Existing metrics owner and goals unchanged, periods separate.',
 'data':a.RULES['data'],'accounting':a.RULES['accounting'],
 'bridge':'Stored historical16/30 aggregation and code/source/ownership comparison only; same historical raw/warmup tape missing => no market replay. No new TrendRider policy or formal credit.',
 'scope':'Prior39 immutable; only conditional KR3 then BR2, ordinals40/41 at first actual market path. Supertrend stored diagnosis only; Q0 no qualification or replay. No new data, operations, live sizing, paid AI or promotion.'}


def authorize():
    c=old.read(SPEC);old.probe.verify_seal(c,'FOCUSED_SPEC')
    if c['rules']!=RULES or c['goals']!=metrics.exits.GOAL or c['order']!=ORDER:
        raise RuntimeError('FOCUSED_SCOPE_DRIFT')
    if c['budget']!={'prior':39,'KR3_max':1,'BR2_max':1,'total_max':2}:
        raise RuntimeError('FOCUSED_BUDGET_DRIFT')
    for path,sha in {**c['code_files_sha256'],**c['preserved_files_sha256'],**c['ci_files_sha256']}.items():
        if old.file_sha(ROOT/path)!=sha:raise RuntimeError('FOCUSED_BYTES:'+path)
    if c['calendars']!=account.CALENDARS['KELTNER'] or c['new_outcomes_seen_at_freeze']:
        raise RuntimeError('FOCUSED_BOUNDARY_DRIFT')
    return c


def parents(kind,period):
    d=a.prior.read_artifact(a.OUTPUT+('/KR2/' if kind=='KR3' else '/BR1/')+'receipt.json',period)
    mapping={'M':'M','M2':'M2','KR1_FULL':'KR1_FULL','KR2_FULL':'FULL'} if kind=='KR3' else {'V2':'P','BR1_FULL':'FULL'}
    return ({n:deepcopy(d['views'][o]) for n,o in mapping.items()},
            {n:deepcopy(d['stages'][o]) for n,o in mapping.items()})


def replay(kind,rows_by,bundles,policy,costs,start,end,fixed=None):
    out={k:[] for k in ('trades','open_observations','events','trace')};out.update(admission={},reference_states={})
    for symbol,rows in sorted(rows_by.items()):
        raw=(kr if kind=='KR3' else br).replay(rows,bundles[symbol],
            eval_start_ms=start,eval_end_ms=end,fixed_signal_indices=None if fixed is None else fixed[symbol])
        view=account.charge_result(raw,symbol,'keltner_trend_main' if kind=='KR3' else 'break_and_continue_main',kind,policy,costs,rows)
        for key in ('trades','open_observations','events','trace'):out[key].extend(view[key])
        out['admission'][symbol]=raw['audit']
        if kind=='KR3':out['reference_states'][symbol]=raw['reference_checkpoint']
    return out


def parity(kind,parent,fixed,full):
    p,f,c=map(metrics.index,(parent,fixed,full))
    if p.keys()!=f.keys():raise RuntimeError('FIXED_ORIGIN_DRIFT')
    for origin in p:
        for key in ('entry_ts','entry_price','signal_index','side'):
            if p[origin][1][key]!=f[origin][1][key]:raise RuntimeError('FIXED_ENTRY_DRIFT')
        if kind=='BR2':
            if p[origin][0]!=f[origin][0]:raise RuntimeError('BR2_FIXED_STATUS_DRIFT')
            for key in ('exit_ts','mark_ts','exit_price','mark_price','net_bps','gross_bps','cost_bps','hypothetical_terminal_net_bps'):
                if p[origin][1].get(key)!=f[origin][1].get(key):raise RuntimeError('BR2_FIXED_PATH_DRIFT:'+key)
    if kind=='KR3' and parent['reference_states']!=full['reference_states']:
        raise RuntimeError('KR3_REFERENCE_DRIFT')
    for symbol in full['admission']:
        items=sorted([v for v in c.values() if v[1]['symbol']==symbol],key=lambda v:v[1]['entry_ts'])
        for x,y in zip(items,items[1:]):
            if x[0]!='C' or x[1]['exit_ts']>y[1]['entry_ts']:raise RuntimeError('ACTUAL_OVERLAP')
            if y[1]['signal_ts']<=x[1]['exit_ts']:
                if kind!='BR2' or not br.release_after_cap(x[1],y[1]):raise RuntimeError('UNAUTHORIZED_EXIT_BAR_RELEASE')
    return 'PASS_FIXED_ENTRY_REFERENCE_AND_ACTUAL_SLOT'


def artifact(kind,period,doc,verify):
    path=ROOT/OUTPUT/kind/(period+'.json.gz');raw=old.probe.canonical(doc)
    payload=path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
    if gzip.decompress(payload)!=raw:raise RuntimeError('FOCUSED_EXACT_DRIFT:'+kind+period)
    old.probe.write_immutable(path,payload,verify_only=verify)
    return {'path':str(path.relative_to(ROOT)),'file_sha256':old.file_sha(path)}


def run(kind,data_dir,verify=False,frozen_commit=None):
    c=authorize();out=ROOT/OUTPUT/kind;rp=out/'receipt.json';ap=out/'ATTEMPT.json'
    if not verify and (rp.exists() or ap.exists()):a.log('DUPLICATE_NO_OP',candidate=kind);return
    if verify and not rp.exists():raise RuntimeError('NO_RECEIPT')
    policy0,costs,periods,access=account.load_inputs(Path(data_dir),c)
    stored={p:parents(kind,p) for p in periods}
    out.mkdir(parents=True,exist_ok=True)
    if not verify:
        attempted=[k for k in ORDER if (ROOT/OUTPUT/k/'ATTEMPT.json').exists()]
        if kind!=ORDER[len(attempted)] or not frozen_commit:raise RuntimeError('SERIAL_OR_FREEZE_MISSING')
        marker=old.seal({'candidate':kind,'ordinal':40+len(attempted),'spec_seal':c['receipt_sha256'],
          'frozen_commit':frozen_commit,'utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),
          'github_run_id':os.environ.get('GITHUB_RUN_ID'),'before_first_market_path':True,'failed_execution_consumes_trial':True})
        old.probe.write_immutable(ap,old.probe.canonical(marker))
    else:
        marker=json.loads(ap.read_text());old.probe.verify_seal(marker,'ATTEMPT')
        if marker['spec_seal']!=c['receipt_sha256']:raise RuntimeError('ATTEMPT_FREEZE_DRIFT')
    a.log('EXACT_REPRODUCTION_START' if verify else 'NEW_CANDIDATE_START',candidate=kind,ordinal=marker['ordinal'])
    results={};artifacts={}
    for period,rows in periods.items():
        start,end=c['calendars'][period]
        policy={**policy0,'batch_id':Path(OUTPUT).name,'receipt_sha256':c['receipt_sha256'],
          'code_files_sha256':c['code_files_sha256'],'development_interval_ms':[start,end],
          'combined_data_sha256':c['period_data_sha256'][period]}
        bundles={s:kr.parent.build_bundle(rr,kr.d.PARENT_SPEC,eval_start_ms=start,eval_end_ms=end)
            if kind=='KR3' else br.br.build_bundle(rr,br.br.specification('BR1')['executable_spec'],start,end) for s,rr in rows.items()}
        views,stages=stored[period];pname='KR1_FULL' if kind=='KR3' else 'BR1_FULL';parent=views[pname]
        origins={s:[t['signal_index'] for key in ('trades','open_observations') for t in parent[key] if t['symbol']==s] for s in rows}
        with old.probe.io_boundary([],out):
            fixed=replay(kind,rows,bundles,policy,costs,start,end,origins)
            full=replay(kind,rows,bundles,policy,costs,start,end)
        relationship=parity(kind,parent,fixed,full);views.update(FIXED=fixed,FULL=full)
        for n in ('FIXED','FULL'):
            v=views[n];stages[n]=metrics.exits.build_stage(v['trades'],v['open_observations'],v['events'],rows,costs,policy,c['symbols'],start,end)
        comparisons={n:metrics.exits.compare(stages[pname],stages[n],parent['trades'],parent['open_observations'],views[n]['trades'],views[n]['open_observations'],rows,costs,start,end) for n in ('FIXED','FULL')}
        effects={n:metrics.effects(v,full) for n,v in views.items() if n not in ('FIXED','FULL')}
        bridge=metrics.fixed_full_bridge(parent,fixed,full);values={n:metrics.stage_values(s) for n,s in stages.items()}
        doc={'candidate':kind,'period':period,'views':views,'stages':stages,'comparisons':comparisons,
             'effects':effects,'fixed_full_bridge':bridge,'values':values,'relationship_parity':relationship}
        artifacts[period]=artifact(kind,period,doc,verify)
        compact=deepcopy(effects)
        for v in compact.values():v.pop('per_origin')
        results[period]={'values':values,'decisions':{n:v['decision'] for n,v in comparisons.items()},
          'effects':compact,'occupancy_bridge_summary':bridge['terminal'],
          'uncertainty':{n:v['uncertainty'] for n,v in comparisons.items()},'admission':full['admission'],
          'relationship_parity':relationship}
        a.log('PERIOD_COMPLETE',candidate=kind,period=period,values=values,decisions=results[period]['decisions'])
    receipt=old.seal({**a.AUTH,'prior39_preserved':True,'schema':'focused.repair.result.v1','candidate':kind,
      'candidate_ordinal':marker['ordinal'],'spec_seal':c['receipt_sha256'],'frozen_commit':marker['frozen_commit'],
      'results':results,'artifacts':artifacts,'source_access':access,
      'execution_inventory':{'new_parent_baselines':0,'candidate_FIXED':2,'candidate_FULL':2,
       'old_candidate_replays':0,'historical_native_market_bridge_replays':0,'outcome_exposure':1 if not verify else 'AUTHORIZED_EXACT_REPRODUCTION'}})
    # Reproduction differs only in invocation intent, never in receipt bytes.
    receipt['execution_inventory']['outcome_exposure']=1
    receipt.pop('receipt_sha256',None);receipt=old.seal(receipt)
    old.probe.write_immutable(rp,old.probe.canonical(receipt),verify_only=verify)
    a.log('COMPLETE',candidate=kind,result_seal=receipt['receipt_sha256']);return receipt


def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',choices=ORDER);p.add_argument('--data-dir')
    p.add_argument('--check-only',action='store_true');p.add_argument('--verify-only',action='store_true');p.add_argument('--frozen-commit');args=p.parse_args()
    if args.check_only:a.log('FREEZE_PASS',seal=authorize()['receipt_sha256']);return
    if not args.candidate or not args.data_dir:p.error('candidate and data-dir required')
    with Path('/tmp/top5-mechanism-sole-writer.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run(args.candidate,args.data_dir,args.verify_only,args.frozen_commit)


if __name__=='__main__':main()

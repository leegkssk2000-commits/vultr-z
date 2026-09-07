"""One scoped native Primary entry quality trial, stored parents, exact reproduction."""
import argparse
from copy import deepcopy
import fcntl
import gzip
import json
import os
from pathlib import Path
from backend.research.rebuild import top5_mechanism_b_v1 as b
from backend.research.rebuild import primary_entry_quality_v1 as tr
from backend.research.rebuild.lifecycle_task_v1 import Registry,utc,digest,GateError

SCOPE='TOP5_AFTER_PR1206_WINRATE_FIRST_AI_V1'
ROOT,old,metrics,n=b.ROOT,b.old,b.metrics,b.n
PRIOR='research/development_evidence/TOP5_AFTER_PR1205_CUMULATIVE_DEV_G5_SUBAGENTS_V1'
OUTPUT='research/development_evidence/'+SCOPE
SPEC=OUTPUT+'/SPEC.json'
def authorize():
    c=old.read(SPEC);old.probe.verify_seal(c,'CUMULATIVE_SPEC')
    if c['scope_key']!=SCOPE or c['rule']!=tr.RULE or c['goals']!=metrics.entries.GOAL or c['new_outcomes_seen_at_freeze']:
        raise GateError('FROZEN_SCOPE_RULE_DRIFT')
    if c['budget']!={'prior':43,'TPQ1_max':1,'Supertrend_max':1,'total_max':2}:raise GateError('BUDGET_DRIFT')
    for path,sha in {**c['code_files_sha256'],**c['preserved_files_sha256'],**c['ci_files_sha256']}.items():
        if old.file_sha(ROOT/path)!=sha:raise GateError('FROZEN_BYTES:'+path)
    return c

def charge(raw,symbol,policy,costs,rows):
    out=b.a.account.charge_result(raw,symbol,n.LANES['TPR1'],'TPQ1',policy,costs,rows)
    for key,seal in [('trades','trade_sha256'),('open_observations','observation_sha256')]:
        for t in out[key]:
            t.pop(seal,None);t.update(native_interval_ms=n.HOUR,candidate_id='TPQ1_ADVERSE_SIGNAL_BODY_DEV_V1',evidence_type='REUSED_NATIVE1H_DEV_ENTRY_FILTER')
            t[seal]=old.digest(t)
    return out

def replay(rows,bundles,policy,costs,fixed=None):
    out={k:[] for k in ('trades','open_observations','events','trace')};out['admission']={}
    for symbol,rr in sorted(rows.items()):
        cache,tape,_=bundles[symbol]
        raw=tr.replay(rr,tape,cache,costs[symbol])
        v=charge(raw,symbol,policy,costs,rr)
        for k in ('trades','open_observations','events','trace'):out[k].extend(v[k])
        out['admission'][symbol]=raw['audit']
    return out

def fixed_subset(parent,rows):
    out=deepcopy(parent)
    keep=lambda t:tr.eligible(rows[t['symbol']],t)
    for k in ('trades','open_observations'):out[k]=[t for t in out[k] if keep(t)]
    keys={(t['symbol'],t['signal_index']) for k in ('trades','open_observations') for t in out[k]}
    out['trace']=[t for t in out['trace'] if (t['symbol'],t['signal_index']) in keys]
    for e in out['events']:
        if not keep(e):e.update(admission=False,status='VETOED',exclusion_reason=tr.VETO_REASON)
    out['admission']={'mode':'STORED_PARENT_SUBSET_ONLY','executable_portfolio':False}
    return out

def unchanged_common_paths(parent,full):
    p,c=metrics.index(parent),metrics.index(full)
    # Economic and native path state may not change on a shared entry origin.
    ignore={'candidate_id','evidence_type','trade_sha256','observation_sha256','receipt_sha256','code_files_sha256','batch_id','config_sha256','combined_data_sha256','admission_sha256','event_sha256'}
    fields=set()
    for origin in sorted(p.keys() & c.keys()):
        a,b=p[origin],c[origin]
        if a[0]!=b[0]:raise GateError('COMMON_STATUS_DRIFT:'+origin)
        keys={k for k in a[1].keys() & b[1].keys() if k not in ignore and any(x in k for x in ('entry','exit','mark','sl','tp','hold','gross','net_bps','cost','fee','funding','protection','runner'))}
        for k in keys:
            if a[1][k]!=b[1][k]:raise GateError('COMMON_PATH_DRIFT:'+origin+':'+k)
        fields.update(keys)
    return {'status':'PASS','common_origins':len(p.keys() & c.keys()),'fields':sorted(fields),'initial_sl_tp_exit_protection_unchanged':True}

def run(*,verify=False,frozen_commit=None):
    c=authorize();out=ROOT/OUTPUT/'TPQ1';rp=out/'receipt.json';ap=out/'ATTEMPT.json'
    registry=Registry(ROOT/OUTPUT/'TASK.json')
    task=old.read(OUTPUT+'/TASK.json')['tasks'][SCOPE] if verify else registry.get(SCOPE)
    if not verify and (task['task_status']!='RUNNING' or task['report_only']):raise GateError('SCOPE_CLOSED')
    if not verify and (rp.exists() or ap.exists()):raise GateError('EXISTING_ATTEMPT_NO_DUPLICATE')
    if verify and not rp.exists():raise GateError('RECEIPT_REQUIRED')
    oldspec=old.read(b.SPEC);p,costs,rows=b.load_inputs(oldspec);start,end=c['calendar']
    stored=b.a.prior.read_artifact(PRIOR+'/TPC1/receipt.json','DEV2025')
    parent=deepcopy(stored['views']['FULL'])
    views={k:deepcopy(stored['views'][k]) for k in ('P','TPR1_FULL','TPP1_FULL')}
    stages={k:deepcopy(stored['stages'][k]) for k in ('P','TPR1_FULL','TPP1_FULL')}
    views['TPC1_FULL']=parent;stages['TPC1_FULL']=deepcopy(stored['stages']['FULL'])
    policy={**p,'batch_id':SCOPE,'receipt_sha256':c['receipt_sha256'],'code_files_sha256':c['code_files_sha256'],
        'combined_data_sha256':c['native_data_sha256'],'development_interval_ms':[start,end]}
    bundles={s:n.prepare(rr,s,'TPR1',start,end,c['native_policy_sha256']['TPR1']) for s,rr in rows.items()}
    # This captures signals only; no old economic path is run.
    tape=lambda seq:sorted([{f:e[f] for f in n.FIELDS} for e in seq],key=lambda e:(e['symbol'],e['signal_index']))
    if tape(parent['events'])!=tape([e for _,events,_ in bundles.values() for e in events]):raise GateError('RAW_SIGNAL_DRIFT')
    origins={s:[t['signal_index'] for key in ('trades','open_observations') for t in parent[key] if t['symbol']==s] for s in rows}
    out.mkdir(parents=True,exist_ok=True)
    if not verify:
        if not frozen_commit:raise GateError('REMOTE_FREEZE_REQUIRED')
        if task['candidate_budget_used']>=1:raise GateError('V5_PRIMARY_BUDGET_EXHAUSTED')
        inherited=old.read(PRIOR+'/TRIAL_LEDGER.json')
        ledger=old.read(OUTPUT+'/TRIAL_LEDGER.json')
        if ledger['inherited_ledger_sha256']!=old.file_sha(ROOT/PRIOR/'TRIAL_LEDGER.json') or ledger['cumulative_actual']!=inherited['cumulative_actual'] or ledger['new_used']!=0:raise GateError('COMMON_LEDGER_DRIFT')
        ordinal=ledger['cumulative_actual']+1
        key=registry.reserve(SCOPE,'W3','economic',{'candidate':'TPQ1','rule':tr.RULE,'data':c['native_data_sha256']},command='python -m backend.research.rebuild.top5_winrate_v1 --run')
        marker=old.seal({'candidate':'TPQ1','ordinal':ordinal,'spec_seal':c['receipt_sha256'],'frozen_commit':frozen_commit,
            'utc':utc(),'pid':os.getpid(),'task_id':task['task_id'],'attempt_key':key,'before_first_market_path':True,'failed_attempt_consumes_budget':True})
        old.probe.write_immutable(ap,old.probe.canonical(marker))
        ledger.update(cumulative_actual=ordinal,new_used=1,trials=[{'ordinal':ordinal,'candidate':'TPQ1','attempt':str(ap.relative_to(ROOT)),'status':'STARTED'}])
        (ROOT/OUTPUT/'TRIAL_LEDGER.json').write_text(json.dumps(ledger,indent=2)+'\n')
    else:marker=json.loads(ap.read_text())
    b.a.log('EXACT_REPRODUCTION_START' if verify else 'NEW_CANDIDATE_START',candidate='TPQ1',ordinal=marker['ordinal'])
    with old.probe.io_boundary([],out):
        fixed=fixed_subset(parent,rows);full=replay(rows,bundles,policy,costs)
    invariants=unchanged_common_paths(parent,full)
    if not metrics.index(fixed).keys() <= metrics.index(parent).keys():raise GateError('FIXED_SUBSET')
    views.update(FIXED=fixed,FULL=full)
    with n.reporting():
        for name in ('FIXED','FULL'):
            v=views[name];stages[name]=metrics.exits.build_stage(v['trades'],v['open_observations'],v['events'],rows,costs,policy,c['symbols'],start,end)
        comparisons={name:metrics.entries.compare(stages['TPC1_FULL'],stages[name],parent['trades'],parent['open_observations'],views[name]['trades'],views[name]['open_observations'],rows,costs,start,end) for name in ('FIXED','FULL')}
    effects={name:metrics.effects(v,full) for name,v in views.items() if name in ('P','TPR1_FULL','TPP1_FULL','TPC1_FULL')}
    bridge=metrics.fixed_full_bridge(parent,fixed,full);values={name:metrics.stage_values(v) for name,v in stages.items()}
    doc={'candidate':'TPQ1','period':'DEV2025','views':views,'stages':stages,'comparisons':comparisons,'effects':effects,'fixed_full_bridge':bridge,'common_path_invariants':invariants,'values':values}
    path=out/'DEV2025.json.gz';raw=old.probe.canonical(doc);payload=path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
    if gzip.decompress(payload)!=raw:raise GateError('EXACT_REPRODUCTION_DRIFT')
    old.probe.write_immutable(path,payload,verify_only=verify)
    compact=deepcopy(effects)
    for v in compact.values():v.pop('per_origin')
    receipt=old.seal({'scope_key':SCOPE,'candidate':'TPQ1','candidate_ordinal':marker['ordinal'],'spec_seal':c['receipt_sha256'],'frozen_commit':marker['frozen_commit'],
        'results':{'DEV2025':{'values':values,'decisions':{k:v['decision'] for k,v in comparisons.items()},'effects':compact,'occupancy_bridge_summary':bridge['terminal'],
            'uncertainty':{k:v['uncertainty'] for k,v in comparisons.items()},'admission':full['admission']}},
        'artifacts':{'DEV2025':{'path':str(path.relative_to(ROOT)),'file_sha256':old.file_sha(path)}},
        'SEEN2026':{'status':'NOT_RUN','reason':'NO_QUALIFIED_REUSED_NATIVE1H_SOURCE'},
        'common_path_invariants':invariants,
        'execution_inventory':{'old_parent_economic_reruns':0,'candidate_FIXED_market_replays':0,'candidate_FIXED_stored_subset':1,'candidate_FULL':1,'raw_intent_capture_only':2},
        'formal_credit':0,'operating_adoption':False,'execution_authority':'NONE','order':'BLOCKED','paid_ai_contribution':None,'external_ai_status':'API_RUNTIME_BLOCKED'})
    old.probe.write_immutable(rp,old.probe.canonical(receipt),verify_only=verify)
    if not verify:
        registry.finish_attempt(SCOPE,marker['attempt_key'],'DONE',evidence={'receipt':str(rp.relative_to(ROOT)),'sha':receipt['receipt_sha256']})
        registry.mark(SCOPE,'W3','DONE',{'receipt':str(rp.relative_to(ROOT)),'2026':'NOT_RUN_NATIVE1H_SOURCE_UNAVAILABLE'})
    b.a.log('COMPLETE',candidate='TPQ1',values=values,decisions=receipt['results']['DEV2025']['decisions']);return receipt

def main():
    p=argparse.ArgumentParser();p.add_argument('--check-only',action='store_true');p.add_argument('--verify-only',action='store_true');p.add_argument('--run',action='store_true');p.add_argument('--frozen-commit');args=p.parse_args()
    if args.check_only:print(json.dumps({'freeze':'PASS','seal':authorize()['receipt_sha256']}));return
    if not args.verify_only and not args.run:p.error('--run or --verify-only required')
    with Path('/tmp/top5-mechanism-sole-writer.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run(verify=args.verify_only,frozen_commit=args.frozen_commit)

if __name__=='__main__':main()

"""One scoped native Primary protection trial, stored parents, exact reproduction."""
import argparse
from copy import deepcopy
import fcntl
import gzip
import json
import os
from pathlib import Path
from backend.research.rebuild import top5_mechanism_b_v1 as b
from backend.research.rebuild import trend_primary_combined_v1 as tr
from backend.research.rebuild.lifecycle_task_v1 import Registry,utc,digest,GateError

SCOPE='TOP5_AFTER_PR1205_CUMULATIVE_DEV_G5_SUBAGENTS_V1'
ROOT,old,metrics,n=b.ROOT,b.old,b.metrics,b.n
PRIOR='research/development_evidence/TOP5_LIFECYCLE_AI_G5_AFTER_PR1204'
OUTPUT='research/development_evidence/'+SCOPE
SPEC=OUTPUT+'/SPEC.json'
def authorize():
    c=old.read(SPEC);old.probe.verify_seal(c,'CUMULATIVE_SPEC')
    if c['scope_key']!=SCOPE or c['rule']!=tr.RULE or c['goals']!=metrics.exits.GOAL or c['new_outcomes_seen_at_freeze']:
        raise GateError('FROZEN_SCOPE_RULE_DRIFT')
    if c['budget']!={'prior':42,'TPC1_max':1,'total_max':1}:raise GateError('BUDGET_DRIFT')
    for path,sha in {**c['code_files_sha256'],**c['preserved_files_sha256'],**c['ci_files_sha256']}.items():
        if old.file_sha(ROOT/path)!=sha:raise GateError('FROZEN_BYTES:'+path)
    return c

def factorial(views):
    names=('P','TPR1_FULL','TPP1_FIXED','FIXED')
    idx={k:metrics.index(views[k]) for k in names}
    common=set.intersection(*(set(x) for x in idx.values()))
    rows=[]
    for origin in sorted(common):
        vals={k:idx[k][origin] for k in names}
        # No missing counterfactual replay: use only four already stored closed states.
        if any(v[0]!='C' for v in vals.values()):continue
        net={k:float(v[1]['net_bps']) for k,v in vals.items()}
        rows.append({'origin':origin,'net_bps':net,'extension':net['TPR1_FULL']-net['P'],
            'protection':net['TPP1_FIXED']-net['P'],
            'interaction':net['FIXED']-net['TPR1_FULL']-net['TPP1_FIXED']+net['P']})
    return {'scope':'COMMON_ORIGIN_STORED_CLOSED_STATES_ONLY','rows':rows,'count':len(rows),
        'totals':{k:sum(r[k] for r in rows) for k in ('extension','protection','interaction')},
        'full_delta_is_additive':False,'missing_path_replays':0}

def charge(raw,symbol,policy,costs,rows):
    out=b.a.account.charge_result(raw,symbol,n.LANES['TPR1'],'TPC1',policy,costs,rows)
    for key,seal in [('trades','trade_sha256'),('open_observations','observation_sha256')]:
        for t in out[key]:
            t.pop(seal,None);t.update(native_interval_ms=n.HOUR,candidate_id='TPC1_EXTENSION_AND_LINE_PROTECTION_DEV_V1',evidence_type='REUSED_NATIVE1H_DEV_COMBINED_EXIT')
            t[seal]=old.digest(t)
    return out

def replay(rows,bundles,policy,costs,fixed=None):
    out={k:[] for k in ('trades','open_observations','events','trace')};out['admission']={}
    for symbol,rr in sorted(rows.items()):
        cache,tape,_=bundles[symbol]
        raw=tr.replay(rr,tape,cache,costs[symbol],fixed_indices=None if fixed is None else fixed[symbol])
        v=charge(raw,symbol,policy,costs,rr)
        for k in ('trades','open_observations','events','trace'):out[k].extend(v[k])
        out['admission'][symbol]=raw['audit']
    return out

def run(*,verify=False,frozen_commit=None):
    c=authorize();out=ROOT/OUTPUT/'TPC1';rp=out/'receipt.json';ap=out/'ATTEMPT.json'
    registry=Registry(ROOT/OUTPUT/'TASK.json')
    task=old.read(OUTPUT+'/TASK.json')['tasks'][SCOPE] if verify else registry.get(SCOPE)
    if not verify and (task['task_status']!='RUNNING' or task['report_only']):raise GateError('SCOPE_CLOSED')
    if not verify and (rp.exists() or ap.exists()):raise GateError('EXISTING_ATTEMPT_NO_DUPLICATE')
    if verify and not rp.exists():raise GateError('RECEIPT_REQUIRED')
    oldspec=old.read(b.SPEC);p,costs,rows=b.load_inputs(oldspec);start,end=c['calendar']
    stored=b.a.prior.read_artifact(b.OUTPUT+'/TPR1/receipt.json','DEV2025')
    protection=b.a.prior.read_artifact(PRIOR+'/TPP1/receipt.json','DEV2025')
    parent=deepcopy(stored['views']['FULL'])
    views={'P':deepcopy(stored['views']['P']),'TPR1_FULL':parent,'TPP1_FIXED':deepcopy(protection['views']['FIXED']),'TPP1_FULL':deepcopy(protection['views']['FULL'])}
    stages={'P':deepcopy(stored['stages']['P']),'TPR1_FULL':deepcopy(stored['stages']['FULL']),'TPP1_FIXED':deepcopy(protection['stages']['FIXED']),'TPP1_FULL':deepcopy(protection['stages']['FULL'])}
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
        if task['candidate_budget_used']>=1:raise GateError('V4_SINGLE_CANDIDATE_EXHAUSTED')
        inherited=old.read(PRIOR+'/TRIAL_LEDGER.json')
        ledger=old.read(OUTPUT+'/TRIAL_LEDGER.json')
        if ledger['inherited_ledger_sha256']!=old.file_sha(ROOT/PRIOR/'TRIAL_LEDGER.json') or ledger['cumulative_actual']!=inherited['cumulative_actual'] or ledger['new_used']!=0:raise GateError('COMMON_LEDGER_DRIFT')
        ordinal=ledger['cumulative_actual']+1
        key=registry.reserve(SCOPE,'W3','economic',{'candidate':'TPC1','rule':tr.RULE,'data':c['native_data_sha256']},command='python -m backend.research.rebuild.top5_cumulative_v1 --run')
        marker=old.seal({'candidate':'TPC1','ordinal':ordinal,'spec_seal':c['receipt_sha256'],'frozen_commit':frozen_commit,
            'utc':utc(),'pid':os.getpid(),'task_id':task['task_id'],'attempt_key':key,'before_first_market_path':True,'failed_attempt_consumes_budget':True})
        old.probe.write_immutable(ap,old.probe.canonical(marker))
        ledger.update(cumulative_actual=ordinal,new_used=1,trials=[{'ordinal':ordinal,'candidate':'TPC1','attempt':str(ap.relative_to(ROOT)),'status':'STARTED'}])
        (ROOT/OUTPUT/'TRIAL_LEDGER.json').write_text(json.dumps(ledger,indent=2)+'\n')
    else:marker=json.loads(ap.read_text())
    b.a.log('EXACT_REPRODUCTION_START' if verify else 'NEW_CANDIDATE_START',candidate='TPC1',ordinal=marker['ordinal'])
    with old.probe.io_boundary([],out):
        fixed=replay(rows,bundles,policy,costs,origins);full=replay(rows,bundles,policy,costs)
    if metrics.index(parent).keys()!=metrics.index(fixed).keys():raise GateError('FIXED_ORIGINS')
    views.update(FIXED=fixed,FULL=full)
    with n.reporting():
        for name in ('FIXED','FULL'):
            v=views[name];stages[name]=metrics.exits.build_stage(v['trades'],v['open_observations'],v['events'],rows,costs,policy,c['symbols'],start,end)
        comparisons={name:metrics.exits.compare(stages['TPR1_FULL'],stages[name],parent['trades'],parent['open_observations'],views[name]['trades'],views[name]['open_observations'],rows,costs,start,end) for name in ('FIXED','FULL')}
    effects={name:metrics.effects(v,full) for name,v in views.items() if name in ('P','TPR1_FULL','TPP1_FULL')}
    bridge=metrics.fixed_full_bridge(parent,fixed,full);values={name:metrics.stage_values(v) for name,v in stages.items()}
    doc={'candidate':'TPC1','period':'DEV2025','views':views,'stages':stages,'comparisons':comparisons,'effects':effects,'fixed_full_bridge':bridge,'factorial':factorial(views),'values':values}
    path=out/'DEV2025.json.gz';raw=old.probe.canonical(doc);payload=path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
    if gzip.decompress(payload)!=raw:raise GateError('EXACT_REPRODUCTION_DRIFT')
    old.probe.write_immutable(path,payload,verify_only=verify)
    compact=deepcopy(effects)
    for v in compact.values():v.pop('per_origin')
    receipt=old.seal({'scope_key':SCOPE,'candidate':'TPC1','candidate_ordinal':marker['ordinal'],'spec_seal':c['receipt_sha256'],'frozen_commit':marker['frozen_commit'],
        'results':{'DEV2025':{'values':values,'decisions':{k:v['decision'] for k,v in comparisons.items()},'effects':compact,'occupancy_bridge_summary':bridge['terminal'],
            'uncertainty':{k:v['uncertainty'] for k,v in comparisons.items()},'admission':full['admission']}},
        'artifacts':{'DEV2025':{'path':str(path.relative_to(ROOT)),'file_sha256':old.file_sha(path)}},
        'SEEN2026':{'status':'NOT_RUN','reason':'NO_QUALIFIED_REUSED_NATIVE1H_SOURCE'},
        'factorial_summary':{k:v for k,v in doc['factorial'].items() if k!='rows'},
        'execution_inventory':{'old_parent_economic_reruns':0,'candidate_FIXED':1,'candidate_FULL':1,'raw_intent_capture_only':2},
        'formal_credit':0,'operating_adoption':False,'execution_authority':'NONE','order':'BLOCKED','paid_ai_contribution':None})
    old.probe.write_immutable(rp,old.probe.canonical(receipt),verify_only=verify)
    if not verify:
        registry.finish_attempt(SCOPE,marker['attempt_key'],'DONE',evidence={'receipt':str(rp.relative_to(ROOT)),'sha':receipt['receipt_sha256']})
        registry.mark(SCOPE,'W3','DONE',{'receipt':str(rp.relative_to(ROOT)),'2026':'NOT_RUN_NATIVE1H_SOURCE_UNAVAILABLE'})
    b.a.log('COMPLETE',candidate='TPC1',values=values,decisions=receipt['results']['DEV2025']['decisions']);return receipt

def main():
    p=argparse.ArgumentParser();p.add_argument('--check-only',action='store_true');p.add_argument('--verify-only',action='store_true');p.add_argument('--run',action='store_true');p.add_argument('--frozen-commit');args=p.parse_args()
    if args.check_only:print(json.dumps({'freeze':'PASS','seal':authorize()['receipt_sha256']}));return
    if not args.verify_only and not args.run:p.error('--run or --verify-only required')
    with Path('/tmp/top5-mechanism-sole-writer.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run(verify=args.verify_only,frozen_commit=args.frozen_commit)

if __name__=='__main__':main()

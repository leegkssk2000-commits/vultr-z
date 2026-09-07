"""One scoped native Primary protection trial, stored parents, exact reproduction."""
import argparse
from copy import deepcopy
import fcntl
import gzip
import json
import os
from pathlib import Path
from backend.research.rebuild import top5_mechanism_b_v1 as b
from backend.research.rebuild import trend_primary_protection_v1 as tr
from backend.research.rebuild.lifecycle_task_v1 import Registry,SCOPE,utc,digest,GateError

ROOT,old,metrics,n=b.ROOT,b.old,b.metrics,b.n
OUTPUT='research/development_evidence/'+SCOPE
SPEC=OUTPUT+'/SPEC.json'
CODE=['backend/research/rebuild/'+x+'_v1.py' for x in ('lifecycle_task','g5_exit_ai_pilot','trend_primary_protection','top5_lifecycle','test_lifecycle_task')]

def validate_contract(contract):
    from backend.research.rebuild.g5b_operational_terminal_v1 import BOUNDARY_KEYS,ECONOMIC_REPORTS
    assert contract['schema']=='kr3.formal.application.draft.v1'
    assert contract['status']=='DRAFT_NOT_FORMAL_ADMISSION' and contract['formal_credit']==0
    assert contract['formal_boundary'] is None and contract['promotion_authority'] is False
    assert set(contract['boundary_identity_draft'])==set(BOUNDARY_KEYS)
    assert set(contract['required_economic_reports'])==set(ECONOMIC_REPORTS)
    for v in contract['unresolved'].values():
        assert v['value'] is None and v['status']=='UNRESOLVED' and v['owner_file'] and v['required_authority'] and v['evidence_required']
    assert contract['native']['initial_protective_sl'] is None and contract['native']['maximum_hold_hours']==96
    for path,sha in contract['development_binding']['files_sha256'].items():
        assert old.file_sha(ROOT/path)==sha, path
    return {'draft_structure':'PASS','hash_binding':'PASS','formal_admission':'NOT_ESTABLISHED','unresolved_count':len(contract['unresolved'])}

def authorize():
    c=old.read(SPEC);old.probe.verify_seal(c,'LIFECYCLE_SPEC')
    if c['scope_key']!=SCOPE or c['rule']!=tr.RULE or c['goals']!=metrics.exits.GOAL or c['new_outcomes_seen_at_freeze']:
        raise GateError('FROZEN_SCOPE_RULE_DRIFT')
    if c['budget']!={'prior':41,'primary_max':1,'supertrend_max':1,'total_max':2}:raise GateError('BUDGET_DRIFT')
    for path,sha in {**c['code_files_sha256'],**c['preserved_files_sha256'],**c['ci_files_sha256']}.items():
        if old.file_sha(ROOT/path)!=sha:raise GateError('FROZEN_BYTES:'+path)
    validate_contract(old.read(OUTPUT+'/KR3_FORMAL_APPLICATION_DRAFT.json'))
    return c

def charge(raw,symbol,policy,costs,rows):
    out=b.a.account.charge_result(raw,symbol,n.LANES['TPR1'],'TPP1',policy,costs,rows)
    for key,seal in [('trades','trade_sha256'),('open_observations','observation_sha256')]:
        for t in out[key]:
            t.pop(seal,None);t.update(native_interval_ms=n.HOUR,candidate_id='TPP1_NATIVE_LINE_PROTECTION_DEV_V1',evidence_type='REUSED_NATIVE1H_DEV_PROTECTION_ONLY')
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
    c=authorize();out=ROOT/OUTPUT/'TPP1';rp=out/'receipt.json';ap=out/'ATTEMPT.json'
    registry=Registry(ROOT/OUTPUT/'TASK.json')
    task=registry.get(SCOPE)
    if task['task_status']!='RUNNING' or task['report_only']:raise GateError('SCOPE_CLOSED')
    if not verify and (rp.exists() or ap.exists()):raise GateError('EXISTING_ATTEMPT_NO_DUPLICATE')
    if verify and not rp.exists():raise GateError('RECEIPT_REQUIRED')
    oldspec=old.read(b.SPEC);p,costs,rows=b.load_inputs(oldspec);start,end=c['calendar']
    stored=b.a.prior.read_artifact(b.OUTPUT+'/TPR1/receipt.json','DEV2025')
    parent=deepcopy(stored['views']['P'])
    views={'P':parent,'TPR1_FULL':deepcopy(stored['views']['FULL'])}
    stages={'P':deepcopy(stored['stages']['P']),'TPR1_FULL':deepcopy(stored['stages']['FULL'])}
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
        key=registry.reserve(SCOPE,'W3','economic',{'candidate':'TPP1','rule':tr.RULE,'data':c['native_data_sha256']},command='python -m backend.research.rebuild.top5_lifecycle_v1 --run')
        marker=old.seal({'candidate':'TPP1','ordinal':42,'spec_seal':c['receipt_sha256'],'frozen_commit':frozen_commit,
            'utc':utc(),'pid':os.getpid(),'task_id':task['task_id'],'attempt_key':key,'before_first_market_path':True,'failed_attempt_consumes_budget':True})
        old.probe.write_immutable(ap,old.probe.canonical(marker))
    else:marker=json.loads(ap.read_text())
    b.a.log('EXACT_REPRODUCTION_START' if verify else 'NEW_CANDIDATE_START',candidate='TPP1',ordinal=42)
    with old.probe.io_boundary([],out):
        fixed=replay(rows,bundles,policy,costs,origins);full=replay(rows,bundles,policy,costs)
    if metrics.index(parent).keys()!=metrics.index(fixed).keys():raise GateError('FIXED_ORIGINS')
    views.update(FIXED=fixed,FULL=full)
    with n.reporting():
        for name in ('FIXED','FULL'):
            v=views[name];stages[name]=metrics.exits.build_stage(v['trades'],v['open_observations'],v['events'],rows,costs,policy,c['symbols'],start,end)
        comparisons={name:metrics.exits.compare(stages['P'],stages[name],parent['trades'],parent['open_observations'],views[name]['trades'],views[name]['open_observations'],rows,costs,start,end) for name in ('FIXED','FULL')}
    effects={name:metrics.effects(v,full) for name,v in views.items() if name in ('P','TPR1_FULL')}
    bridge=metrics.fixed_full_bridge(parent,fixed,full);values={name:metrics.stage_values(v) for name,v in stages.items()}
    doc={'candidate':'TPP1','period':'DEV2025','views':views,'stages':stages,'comparisons':comparisons,'effects':effects,'fixed_full_bridge':bridge,'values':values}
    path=out/'DEV2025.json.gz';raw=old.probe.canonical(doc);payload=path.read_bytes() if path.exists() else gzip.compress(raw,mtime=0)
    if gzip.decompress(payload)!=raw:raise GateError('EXACT_REPRODUCTION_DRIFT')
    old.probe.write_immutable(path,payload,verify_only=verify)
    compact=deepcopy(effects)
    for v in compact.values():v.pop('per_origin')
    receipt=old.seal({'scope_key':SCOPE,'candidate':'TPP1','candidate_ordinal':42,'spec_seal':c['receipt_sha256'],'frozen_commit':marker['frozen_commit'],
        'results':{'DEV2025':{'values':values,'decisions':{k:v['decision'] for k,v in comparisons.items()},'effects':compact,'occupancy_bridge_summary':bridge['terminal'],
            'uncertainty':{k:v['uncertainty'] for k,v in comparisons.items()},'admission':full['admission']}},
        'artifacts':{'DEV2025':{'path':str(path.relative_to(ROOT)),'file_sha256':old.file_sha(path)}},
        'SEEN2026':{'status':'NOT_RUN','reason':'NO_QUALIFIED_REUSED_NATIVE1H_SOURCE'},
        'execution_inventory':{'old_parent_economic_reruns':0,'candidate_FIXED':1,'candidate_FULL':1,'raw_intent_capture_only':2},
        'formal_credit':0,'operating_adoption':False,'execution_authority':'NONE','order':'BLOCKED','paid_ai_contribution':None})
    old.probe.write_immutable(rp,old.probe.canonical(receipt),verify_only=verify)
    if not verify:
        registry.finish_attempt(SCOPE,marker['attempt_key'],'DONE',evidence={'receipt':str(rp.relative_to(ROOT)),'sha':receipt['receipt_sha256']})
        registry.mark(SCOPE,'W3','DONE',{'receipt':str(rp.relative_to(ROOT)),'2026':'NOT_RUN_NATIVE1H_SOURCE_UNAVAILABLE'})
    b.a.log('COMPLETE',candidate='TPP1',values=values,decisions=receipt['results']['DEV2025']['decisions']);return receipt

def main():
    p=argparse.ArgumentParser();p.add_argument('--check-only',action='store_true');p.add_argument('--verify-only',action='store_true');p.add_argument('--run',action='store_true');p.add_argument('--frozen-commit');args=p.parse_args()
    if args.check_only:print(json.dumps({'freeze':'PASS','seal':authorize()['receipt_sha256']}));return
    if not args.verify_only and not args.run:p.error('--run or --verify-only required')
    with Path('/tmp/top5-mechanism-sole-writer.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run(verify=args.verify_only,frozen_commit=args.frozen_commit)

if __name__=='__main__':main()

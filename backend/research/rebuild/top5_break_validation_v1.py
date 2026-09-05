"""Exact PR1180 Break child, one separately authorized validation comparison.

No formal Alpha Proof guard is bypassed: this collects validation evidence and
cannot return economic PASS, read purged OOS, or create a prospective boundary.
Other-lane development modules never import this module or its outputs.
"""
import argparse,gzip,json
from pathlib import Path
from backend.research.rebuild import top5_development_repair_v1 as core
from backend.research.rebuild.top5_external_metrics_v1 import attribution,diagnostics

CONTRACT='backend/research/contracts/top5_break_validation_v1.json'
OUTPUT='research/development_evidence/BREAK_VALIDATION_20260905_V1'
PLAN=core.OUTPUT+'/next_validation_plan.json'
LANE='break_and_continue_main'
INTERVAL=14400000


def authorize():
    p=core.read(core.POLICY);cfg=core.read(CONTRACT);plan=core.read(PLAN)
    for name,value in [('BREAK_VALIDATION',cfg),('PR1180_PLAN',plan)]:core.probe.verify_seal(value,name)
    if (cfg['authorization']!='EXPLICIT_USER_CONTINUE_EXACT_BREAK_VALIDATION' or cfg['comparison_budget']!=1
            or cfg['outcomes_observed_at_freeze'] is not False or cfg['OOS_authorized'] is not False):raise RuntimeError('VALIDATION_AUTHORITY')
    if plan['receipt_sha256']!=cfg['prior_plan_sha256'] or cfg['candidate']!=plan['candidate']:raise RuntimeError('BREAK_CHILD_IMMUTABLE')
    for path,sha in {**p['code_files_sha256'],**p['immutable_files_sha256'],**cfg['code_files_sha256'],**cfg['sealed_before_validation_files']}.items():
        if core.file_sha(core.ROOT/path)!=sha:raise RuntimeError('VALIDATION_IDENTITY:'+path)
    for key,value in core.probe.DEV_AUTH.items():
        if cfg.get(key)!=value:raise RuntimeError('VALIDATION_FORMAL_AUTHORITY_FORBIDDEN')
    if cfg['stage_review']['P0']!='UNCONFIRMED':raise RuntimeError('P0_FALSE_CREDIT')
    prior=core.read(core.OUTPUT+'/comparison/receipt.json')
    if prior['receipt_sha256']!=cfg['prior_development_receipt_sha256'] or prior['lanes'][LANE]['comparison']['decision']!='DEV_PROMISING':raise RuntimeError('BREAK_DEVELOPMENT_GATE')
    dev=core.require_development(core.read(core.probe.STAGE),core.ROOT)
    if dev['receipt_sha256']!=p['cost_binding_sha256']:raise RuntimeError('VALIDATION_COST_IDENTITY')
    return p,cfg,plan,dev


def validation_prefix(path,start,end,original_start):
    # Stop decoding exactly at validation end; opaque full-file SHA is separate.
    count=(end-original_start)//INTERVAL
    rows=core.probe.prefix_rows(path,count)
    core.common.evaluate_development_events(rows,[],split_start_ms=original_start,split_end_ms=end,interval_ms=INTERVAL,hold_bars=1)
    offset=(start-original_start)//INTERVAL
    if rows[offset]['bar_open_ts']!=start or rows[-1]['bar_close_ts']!=end:raise RuntimeError('VALIDATION_COVERAGE')
    return rows,offset


def simulate(rows,offset,symbol,spec,p,costs,scenario,predicate):
    validation=rows[offset:];start,end=p['development_interval_ms']
    _,engine=core.dsl._features([dict(row,ts=row['bar_open_ts']) for row in rows],spec)
    signals=[];events=[]
    for i in range(max(239,offset),len(rows)):
        if not bool(engine.eval(spec['entry_rule'],i)):continue
        features=core.geometry(rows,i);allowed=features[predicate] if predicate else True
        e=dict(lane_id=LANE,scenario=scenario,symbol=symbol,signal_index=i-offset,signal_ts=rows[i]['bar_close_ts'],features=features,admission=allowed,split='VALIDATION_EVIDENCE_ONLY',formal_credit=0)
        events.append(e)
        if allowed:signals.append(i-offset)
    raw=core.common.evaluate_development_events(validation,signals,split_start_ms=start,split_end_ms=end,interval_ms=INTERVAL,hold_bars=spec['max_hold_bars'])
    trades=[]
    for item in raw['trades']:
        t=core.charge(item,symbol,LANE,scenario,p,costs,validation,INTERVAL)
        t.update(split='VALIDATION_EVIDENCE_ONLY',source_prefix_index_offset=offset)
        t.pop('trade_sha256');t['trade_sha256']=core.digest(t);trades.append(t)
    completed={t['signal_index'] for t in trades};excluded={e['signal_index']:e['reason'] for e in raw['exclusions']}
    for e in events:
        i=e['signal_index'];e['status']='COMPLETED' if i in completed else 'EXCLUDED'
        e['exclusion_reason']=None if i in completed else ('CHILD_ENTRY_VETO' if not e['admission'] else excluded[i])
    return trades,events


def run(data_dir,verify_only=False):
    p,cfg,plan,dev=authorize();probe_policy=core.read(core.probe.POLICY)
    spec=next(c['executable_spec'] for c in core.read(core.FREEZE)['children'] if c['lane_id']==LANE)
    gate=core.read('backend/research/contracts/a1_top5_entry_transplant_replay_v1.json')['selection_rule']
    manifest=json.loads((data_dir/'development_manifest.json').read_text())
    out=core.ROOT/OUTPUT
    if not verify_only:out.mkdir(parents=True,exist_ok=True)
    allowed=[data_dir/'development_manifest.json']+[data_dir/x for x in manifest['dataset_files']]+[data_dir/x['path'] for x in manifest['cost_snapshots'].values()]
    populations={'base':[],'child':[]};events={'base':[],'child':[]};access={}
    original_start=p['development_interval_ms'][0]
    p={**p,'batch_id':'BREAK_VALIDATION_20260905_V1','development_interval_ms':plan['splits']['validation'],'receipt_sha256':cfg['receipt_sha256'],'code_files_sha256':{**p['code_files_sha256'],**cfg['code_files_sha256']}}
    start,end=p['development_interval_ms']
    with core.probe.io_boundary(allowed,out):
        # Existing strict development loader verifies complete input bytes and bound costs.
        core.probe.load_development(data_dir,probe_policy,dev)
        for symbol in p['symbols']:
            rows,offset=validation_prefix(data_dir/'ohlcv'/(symbol+'.json'),start,end,original_start)
            access[symbol]={'prefix_rows_decoded':len(rows),'validation_rows_decoded':len(rows)-offset,'past_warmup_rows':offset,'purged_OOS_rows_decoded':0,'first_validation_open':start,'last_validation_close':end,'prefix_sha256':core.digest(rows)}
            for scenario,predicate in [('base',None),('child',plan['candidate']['predicate'])]:
                t,e=simulate(rows,offset,symbol,spec,p,dev['cost_by_symbol'],scenario,predicate)
                populations[scenario].extend(t);events[scenario].extend(e)
        metrics={k:core.metrics(v,events[k],p,p['symbols']) for k,v in populations.items()}
        control=sorted(populations['base'],key=lambda t:core.digest(['fixed_seed_1179',t['identity']]))[:len(populations['child'])]
        u=core.probe.cluster_uncertainty({**populations,'matched_hash_control':control},p)
        comp=core.compare(populations['base'],populations['child'],control,metrics['base'],metrics['child'],u,gate)
        # Map the unchanged numeric comparison without mislabelling it as development or formal PASS.
        decision={'DEV_REJECT':'VALIDATION_REJECT','INSUFFICIENT':'VALIDATION_INSUFFICIENT','DEV_PROMISING':'VALIDATION_PROMISING_P0_UNCONFIRMED'}[comp['decision']]
        comp={**comp,'decision':decision,'validation':'MEASURED','OOS':'NOT_RUN'}
        artifacts={}
        for name,values in [('trades',sum(populations.values(),[])),('events',sum(events.values(),[]))]:
            plain=b''.join(core.probe.canonical(x) for x in sorted(values,key=lambda x:(x['scenario'],x['symbol'],x['signal_ts'])))
            path=out/(name+'.jsonl.gz');data=path.read_bytes() if path.exists() else gzip.compress(plain,mtime=0)
            if gzip.decompress(data)!=plain:raise RuntimeError('VALIDATION_REPRODUCTION_DRIFT')
            core.probe.write_immutable(path,data,verify_only=verify_only)
            artifacts[name]={'path':str(path.relative_to(core.ROOT)),'file_sha256':core.file_sha(path),'rows':len(values)}
        value=core.seal({'batch_id':p['batch_id'],'contract_sha256':cfg['receipt_sha256'],'candidate':plan['candidate']['child_id'],'candidate_frozen_config_sha256':cfg['candidate_frozen_config_sha256'],'source_access':access,'metrics':metrics,'matched_hash_control':core.metrics(control,[],p,p['symbols']),'uncertainty':u,'comparison':comp,'decision':decision,'attribution':attribution(populations['base'],populations['child']),'diagnostics':{k:diagnostics(v,start,end)[0] for k,v in populations.items()},'artifacts':artifacts,'comparison_budget_consumed':1,'OOS_budget_consumed':0,'P0':'UNCONFIRMED','formal_economic_PASS':False,'new_G5B_T':0,'G6_authorized':False,'production_cost_credit':0,'cost_scope':'RESEARCH_ONLY_DEVELOPMENT_COST_MODEL_REUSED_FOR_VALIDATION','other_lane_context_receives_validation':False,**core.probe.DEV_AUTH})
        core.probe.write_immutable(out/'receipt.json',core.probe.canonical(value),verify_only=verify_only)
    return value

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    value=run(a.data_dir.resolve(),a.verify_only)
    print(json.dumps({'receipt_sha256':value['receipt_sha256'],'decision':value['decision'],'comparison':value['comparison'],'metrics':{k:v['base_cost'] for k,v in value['metrics'].items()}},indent=2))

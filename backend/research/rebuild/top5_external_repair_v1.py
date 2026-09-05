"""One sealed four-lane DEV round over PR1180's inputs and native evaluator."""
from __future__ import annotations
import argparse
import gzip
import json
from pathlib import Path
from unittest.mock import patch

from backend.research.rebuild import top5_development_repair_v1 as old
from backend.research.rebuild.top5_external_features_v1 import Features
from backend.research.rebuild.top5_external_metrics_v1 import diagnostics, attribution
from backend.research.architecture_factory.g5a_source_admission_v1 import ROOT, read, seal, file_sha, require_development

OUTPUT = 'research/development_evidence/TOP5_EXTERNAL_20260905_V1'
CONTRACT = 'backend/research/contracts/top5_external_children_v1.json'
LANES = [old.LANES[i] for i in [0,1,3,4]]


def read_lines(path):
    return [json.loads(x) for x in gzip.decompress(path.read_bytes()).splitlines()]


def load_inputs(data_dir):
    p = read(old.POLICY); dev = require_development(read(old.probe.STAGE),ROOT)
    probe_policy=read(old.probe.POLICY)
    nr = ROOT/old.OUTPUT/'native_1h'; manifest = json.loads((nr/'manifest.json').read_text())
    old.probe.verify_seal(manifest,'NATIVE_MANIFEST')
    if file_sha(nr/'manifest.json')!=p['native_manifest_file_sha256']:raise RuntimeError('NATIVE_MANIFEST_IDENTITY')
    if dev['receipt_sha256']!=p['cost_binding_sha256']:raise RuntimeError('COST_IDENTITY')
    dataset_manifest=json.loads((data_dir/'development_manifest.json').read_text())
    allowed=[data_dir/'development_manifest.json']+[data_dir/x for x in dataset_manifest['dataset_files']]
    allowed += [data_dir/x['path'] for x in dataset_manifest['cost_snapshots'].values()]
    allowed += [nr/(s+'.json.gz') for s in p['native_symbols']]
    rows1 = {}
    with old.probe.io_boundary(allowed,ROOT/OUTPUT/'input_no_writes'):
        rows4, access = old.probe.load_development(data_dir,probe_policy,dev)
        for s in p['native_symbols']:
            path = nr/(s+'.json.gz')
            if file_sha(path)!=manifest['symbols'][s]['file_sha256']: raise RuntimeError('NATIVE_DATA_IDENTITY')
            rows1[s] = json.loads(gzip.decompress(path.read_bytes()))
            old.native.validate_native(rows1[s],*p['development_interval_ms'])
    return p,dev,rows4,rows1,access


def verify_previous():
    p = read(old.POLICY)
    for path, value in {**p['code_files_sha256'],**p['immutable_files_sha256']}.items():
        if file_sha(ROOT/path)!=value: raise RuntimeError('PR1180_IDENTITY:'+path)
    for stage in ['baseline','comparison']:
        r = read(str(Path(old.OUTPUT)/stage/'receipt.json'));old.probe.verify_seal(r,stage)
        for a in r['artifacts'].values():
            if file_sha(ROOT/a['path'])!=a['file_sha256']:raise RuntimeError('PR1180_LEDGER_IDENTITY')


def predicate_values(f):
    return {**f, 'exhausted_direction_veto_pass': not (
        f['prior_DMI14_direction_aligned'] and not f['ADX14_rising'])}


def run(data_dir, verify_only=False):
    contract = read(CONTRACT);old.probe.verify_seal(contract,'EXTERNAL_CHILDREN')
    for path,value in contract['code_files_sha256'].items():
        if file_sha(ROOT/path)!=value:raise RuntimeError('EXTERNAL_CODE_IDENTITY:'+path)
    verify_previous()
    for path,value in contract['evidence_files_sha256'].items():
        if file_sha(ROOT/path)!=value:raise RuntimeError('EVIDENCE_IDENTITY:'+path)
    p,dev,rows4,rows1,access = load_inputs(data_dir)
    p.update(batch_id=contract['batch_id'],receipt_sha256=contract['receipt_sha256'],
             code_files_sha256={**p['code_files_sha256'],**contract['code_files_sha256']})
    parent_rows=read_lines(ROOT/old.OUTPUT/'baseline/trades.jsonl.gz')
    parent_events=read_lines(ROOT/old.OUTPUT/'baseline/events.jsonl.gz')
    previous_rows=read_lines(ROOT/old.OUTPUT/'comparison/trades.jsonl.gz')
    frozen=read(old.FREEZE)['children'];gate=read('backend/research/contracts/a1_top5_entry_transplant_replay_v1.json')['selection_rule']
    prior_baseline=read(str(Path(old.OUTPUT)/'baseline/receipt.json'))
    result={};all_trades=[];all_events=[]
    out=ROOT/OUTPUT/'comparison'
    if not verify_only:out.mkdir(parents=True,exist_ok=True)
    allowed=[data_dir/'development_manifest.json']
    manifest=json.loads((data_dir/'development_manifest.json').read_text())
    allowed += [data_dir/x for x in manifest['dataset_files']]+[data_dir/x['path'] for x in manifest['cost_snapshots'].values()]
    allowed += [ROOT/old.OUTPUT/'native_1h'/(s+'.json.gz') for s in p['native_symbols']]
    with old.probe.io_boundary(allowed,out):
        for lane in LANES:
            cfg=contract['lanes'][lane];native=lane in old.LANES[:2]
            symbols=p['native_symbols'] if native else p['symbols'];data=rows1 if native else rows4
            base=[t for t in parent_rows if t['lane_id']==lane]
            events=[e for e in parent_events if e['lane_id']==lane]
            child=[];child_events=[]
            for symbol in symbols:
                rows=data[symbol];features=Features(rows,3_600_000 if native else 14_400_000)
                geometry=old.geometry
                def extended(rs,i,side='long'):
                    return {**geometry(rs,i,side),**predicate_values(features.at(i,side))}
                with patch.object(old,'geometry',extended):
                    if native:t,e=old.one_hour(rows,symbol,lane,p,dev['cost_by_symbol'],'child',cfg['predicate'])
                    else:
                        spec=next(x for x in frozen if x['lane_id']==lane)
                        t,e=old.four_hour(rows,symbol,spec,p,dev['cost_by_symbol'],'child',cfg['predicate'])
                child.extend(t);child_events.extend(e)
            pm=old.metrics(base,events,p,symbols);cm=old.metrics(child,child_events,p,symbols)
            control=sorted(base,key=lambda t:old.digest(['fixed_seed_1179',t['identity']]))[:len(child)]
            # Explicit constant-risk, same calendar, count-matched parent comparator.
            populations={'base':base,'child':child,'matched_hash_control':control}
            uncertainty=old.probe.cluster_uncertainty(populations,p)
            verdict=old.compare(base,child,control,pm,cm,uncertainty,gate)
            previous=[t for t in previous_rows if t['lane_id']==lane and t['scenario']=='child']
            baseline_metrics=prior_baseline['lanes'][lane]['metrics']['base']
            if pm!=baseline_metrics:raise RuntimeError('BASELINE_METRIC_PARITY')
            diag_base,_=diagnostics(base,*p['development_interval_ms']);diag_child,_=diagnostics(child,*p['development_interval_ms'])
            result[lane]={'parent_id':cfg['parent_id'],'child_id':cfg['child_id'],'source_ids':cfg['source_ids'],
                          'mechanism':cfg['mechanism'],'failure_signature':cfg['failure_signature'],
                          'metrics':{'base':pm,'child':cm,'matched_hash_control':old.metrics(control,[],p,symbols)},
                          'prior_failed_child_attribution':attribution(base,previous),
                          'attribution':attribution(base,child),'diagnostics':{'base':diag_base,'child':diag_child},
                          'uncertainty':uncertainty,'comparison':verdict,'P0':'UNCONFIRMED',
                          'validation':'NOT_RUN','OOS':'NOT_RUN','formal_pass':False}
            all_trades.extend(base+child);all_events.extend(events+child_events)
        artifacts={}
        for name,values in [('trades',all_trades),('events',all_events)]:
            plain=b''.join(old.probe.canonical(x) for x in sorted(values,key=lambda x:(x['lane_id'],x['scenario'],x['symbol'],x['signal_ts'])))
            path=out/(name+'.jsonl.gz');data=path.read_bytes() if path.exists() else gzip.compress(plain,mtime=0)
            if gzip.decompress(data)!=plain:raise RuntimeError('REPRODUCTION_DRIFT:'+name)
            old.probe.write_immutable(path,data,verify_only=verify_only)
            artifacts[name]={'path':str(path.relative_to(ROOT)),'rows':len(values),'file_sha256':old.file_sha(path)}
        receipt=seal({'batch_id':contract['batch_id'],'contract_sha256':contract['receipt_sha256'],
                      'source_access':access,'validation_rows_decoded':0,'OOS_rows_decoded':0,
                      'data_sha256':p['combined_data_sha256'],'cost_sha256':p['cost_binding_sha256'],
                      'code_sha256':old.digest(p['code_files_sha256']),'lanes':result,'artifacts':artifacts,
                      'unique_mechanism_hypotheses':3,'lane_comparisons':4,
                      'Primary_Broad_share_hypothesis_and_trades_not_independent':True,
                      'new_G5B_T':0,'actual_fills':False,**old.probe.DEV_AUTH})
        old.probe.write_immutable(out/'receipt.json',old.probe.canonical(receipt),verify_only=verify_only)
    return receipt


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data-dir',type=Path,required=True);ap.add_argument('--verify-only',action='store_true');a=ap.parse_args()
    r=run(a.data_dir.resolve(),a.verify_only)
    print(json.dumps({'receipt_sha256':r['receipt_sha256'],'lanes':{l:{'E':v['metrics']['child']['base_cost']['expectancy_bps_per_trade'],'comparison':v['comparison']} for l,v in r['lanes'].items()}},indent=2))

if __name__=='__main__':main()

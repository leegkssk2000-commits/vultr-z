"""Finite STEP7 integration and one public-source dispatch; no economic replay."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import urllib.request
from backend.research.rebuild.lifecycle_task_v1 import digest
from backend.research.rebuild import step7_candidate_contract_v1 as candidate

ROOT=Path(__file__).resolve().parents[3]
SCOPE='ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR'
OUT=ROOT/'research/development_evidence'/SCOPE
SPEC=OUT/'SPEC.json'

def read(path):return json.loads(Path(path).read_text())
def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify():
    spec=read(SPEC)
    assert spec['receipt_sha256']==digest({k:v for k,v in spec.items() if k!='receipt_sha256'}), 'SPEC_SEAL'
    for path,sha in spec['files_sha256'].items():
        assert file_sha(ROOT/path)==sha, 'FROZEN_INPUT_CHANGED:'+path
    selection=read(OUT/'SELECTION.json');application=read(OUT/'CONTRACT/APPLICATION.json')
    assert selection['receipt_sha256']==application['selection_sha256'], 'SELECTION_APPLICATION'
    assert application['candidate']['candidate_id']==selection['candidate_id'] and application['candidate']['native']['initial_protective_sl'] is None, 'NATIVE_IDENTITY'
    assert application['formal_admission'] is False and application['G5A_qualified'] is False, 'NO_FALSE_ADMISSION'
    b=read(OUT/'BUDGET.json')
    prior=ROOT/b['inherited_candidate_ledger']
    assert file_sha(prior)==b['inherited_candidate_ledger_sha256'], 'CANDIDATE_LEDGER_DRIFT'
    assert read(prior)['cumulative_actual']==b['cumulative_actual']==44 and b['new_candidate_runs']==0, 'CANDIDATE_BUDGET'
    assert b['independent_validation']['used']==b['independent_validation_bundle_used']==0, 'UNAPPROVED_VALIDATION_ACCESS'
    return {'state':'STEP7_IMPLEMENTATION_REPRODUCED','selection':selection['candidate_id'],
            'application_sha':application['receipt_sha256'],'formal_credit':0,'market_replays':0,
            'independent_accesses':0,'source_collection_proven':False}

def source_dispatch_allowed(context, budget, runs):
    """First immutable push run only. Rerun/new filename never resets allocation."""
    assert context['event']=='push' and context['ref']=='refs/heads/master' and context['attempt']==1, 'ONE_MASTER_FIRST_ATTEMPT'
    reservation=budget['source_reservation']
    assert reservation['status']=='RESERVED' and reservation['max_bundles']==1, 'SOURCE_RESERVATION_REQUIRED'
    assert context['message'].splitlines()[0]==reservation['merge_commit_title'], 'EXACT_AUTHORIZED_MERGE_MESSAGE'
    assert context['selection_sha256']==reservation['selection_sha256'], 'SOURCE_SELECTION_DRIFT'
    same=[r for r in runs if r['head_sha']==context['sha'] and r['event']=='push' and r['path']=='.github/workflows/step7-parent-survivor-v1.yml']
    assert same and min(r['id'] for r in same)==context['run_id'], 'NOT_FIRST_FIXED_SHA_RUN'
    return True

def collect_source(output):
    verify()
    event=read(os.environ['GITHUB_EVENT_PATH'])
    context={'event':os.environ['GITHUB_EVENT_NAME'],'ref':os.environ['GITHUB_REF'],
        'attempt':int(os.environ['GITHUB_RUN_ATTEMPT']),'message':event['head_commit']['message'],
        'sha':os.environ['GITHUB_SHA'],'run_id':int(os.environ['GITHUB_RUN_ID']),
        'selection_sha256':read(OUT/'SELECTION.json')['receipt_sha256']}
    repo=os.environ['GITHUB_REPOSITORY']
    assert repo=='leegkssk2000-commits/vultr-z','REPOSITORY_BINDING'
    url=f'https://api.github.com/repos/{repo}/actions/workflows/step7-parent-survivor-v1.yml/runs?head_sha={context["sha"]}&event=push&per_page=100'
    request=urllib.request.Request(url,headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'],'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=10) as response:runs=json.load(response)['workflow_runs']
    source_dispatch_allowed(context,read(OUT/'BUDGET.json'),runs)
    from backend.research.rebuild import step7_source_bridge_v1 as source
    result=source.capture(Path(output),f'STEP7-{context["run_id"]}-{context["sha"]}',1)
    cursor=read(Path(output)/'cursor.json') if (Path(output)/'cursor.json').exists() else {'streams':{}}
    receipts=[]
    for p in sorted((Path(output)/'receipts').glob('*.json')):
        r=read(p);v=r['parsed'];receipts.append({
          'stream':r['stream'],'symbol':r.get('symbol'),'source_sha256':r['source_sha256'],'requested_at_ms':r['requested_at_ms'],
          'received_at_ms':r['received_at_ms'],'exchange_event_ts_ms':v['exchange_event_ts_ms'],
          'available_at_ms':v['available_at_ms'],'last_cursor':v['last_cursor'],
          'duplicate_rows':v['duplicate_rows'],'missing_intervals':v['missing_intervals'],
          'row_count':len(v.get('rows',[])),'state':v['state'],
          'online_offline_parse_equal':r['online_offline_parse_equal'],'raw_uri':r['raw_uri']})
    summary={'scope_key':SCOPE,'source_state':result['state'],'run_id':context['run_id'],
       'head_sha':context['sha'],'requests':result['requests'],'cursor':cursor,'receipts':receipts,
       'formal_credit':0,'new_formal_T':0,'strategy_decision_parity':'NOT_EXECUTED_PENDING_AUTHORITY',
       'coverage':result['coverage'],'full_candidate_source_ready':False,
       'retention_days':90,'paid_API_requests':0,'process_continues_after_return':False,
       'artifact_name':'step7-source-'+str(context['run_id'])}
    source.save(Path(output)/'PUBLIC_METADATA.json',summary)
    print('STEP7_SOURCE_METADATA='+json.dumps(summary,sort_keys=True))
    return summary

def main():
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');p.add_argument('--collect-source');a=p.parse_args()
    if a.collect_source:collect_source(a.collect_source)
    elif a.verify:print(json.dumps(verify(),sort_keys=True))
    else:p.error('--verify or --collect-source required')
if __name__=='__main__':main()

"""Scoped STEP7 continuation dispatch and exact implementation reproduction.

This gate authorizes only the explicitly allocated non-order source connection.
It is not a formal approval authority or a sealed economic input reader.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
SCOPE = 'ZEL_PARENT_CLOSURE_TO_G5_SURVIVOR'
CAMPAIGN = ROOT / 'research/development_evidence' / SCOPE
OUT = CAMPAIGN / 'EXECUTION_PATH'
ALLOCATION = 'STEP7_PR1209_EXECUTION_PATH_SOURCE_V1'
MERGE_TITLE = 'Merge STEP7 execution path task-c28e09b57c612762'
WORKFLOW = '.github/workflows/step7-parent-survivor-v1.yml'


def read(path):
    return json.loads(Path(path).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def verify():
    spec = read(OUT / 'SPEC.json')
    if spec['receipt_sha256'] != digest({k:v for k,v in spec.items() if k != 'receipt_sha256'}):
        raise ValueError('CONTINUATION_SPEC_SEAL')
    for path, expected in spec['files_sha256'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != expected:
            raise ValueError('CONTINUATION_FROZEN_INPUT_CHANGED:' + path)
    selection = read(CAMPAIGN/'SELECTION.json')
    if selection['receipt_sha256'] != spec['selection_sha256']:
        raise ValueError('CANDIDATE_RESELECTION_FORBIDDEN')
    budget = read(CAMPAIGN/'BUDGET.json')
    if budget['cumulative_actual'] != 44 or budget['new_candidate_runs'] != 0:
        raise ValueError('NO_NEW_STRATEGY_ALLOCATION')
    if budget['source_bundle_used'] != 1 or budget['independent_validation']['used'] != 0:
        raise ValueError('INHERITED_ALLOCATION_DRIFT')
    if spec['formal_numeric_approval'] or spec['independent_access_approval']:
        raise ValueError('IMPLEMENTATION_APPROVAL_IS_NOT_FORMAL_APPROVAL')
    return {'state':'STEP7_EXECUTION_PATH_REPRODUCED', 'formal_credit':0,
            'independent_economic_executions':0, 'new_strategy_candidates':0,
            'selection_sha256':selection['receipt_sha256'], 'spec_sha256':spec['receipt_sha256']}


def verify_fixture(directory):
    expected = read(OUT/'PRODUCER/INTEGRATION_RECEIPT.json')
    raw = (Path(directory)/'BUNDLE.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected['bundle_sha256']:
        raise ValueError('FROZEN_SYNTHETIC_BUNDLE_REPRODUCTION_MISMATCH')
    value = json.loads(raw)
    if value['evidence_kind'] != 'SYNTHETIC_INTEGRATION_ONLY' or value['formal_credit'] != 0:
        raise ValueError('SYNTHETIC_IS_NOT_INDEPENDENT_ECONOMICS')
    if value['consumer']['produced_count'] != 9:
        raise ValueError('NINE_PRODUCERS_NOT_EXECUTED')
    for name, expected_sha in expected['reports_sha256'].items():
        if hashlib.sha256((Path(directory)/(name+'.json')).read_bytes()).hexdigest() != expected_sha:
            raise ValueError('REPORT_REPRODUCTION_MISMATCH:'+name)
    return {'state':'NATIVE_NINE_SYNTHETIC_REPORTS_REPRODUCED', 'bundle_sha256':expected['bundle_sha256'],
            'produced_reports':value['consumer']['produced_reports'], 'formal_credit':0}


def source_dispatch_allowed(context, budget, runs):
    allocations = [a for a in budget.get('additional_source_allocations', []) if a.get('allocation_id') == ALLOCATION]
    if len(allocations) != 1:
        raise ValueError('EXPLICIT_ADDITIONAL_ALLOCATION_REQUIRED')
    a = allocations[0]
    if budget.get('source_bundle_used') != 1:
        raise ValueError('ORIGINAL_ALLOCATION_MUST_REMAIN_CONSUMED')
    if (a.get('status') != 'RESERVED' or a.get('used_batches') != 0 or a.get('max_batches') != 1
            or not 0 < a.get('maximum_seconds', 0) <= 86400 or not 0 < a.get('http_max', 0) <= 2000
            or not 0 < a.get('new_raw_bytes_max', 0) <= 1073741824):
        raise ValueError('ADDITIONAL_ALLOCATION_CLOSED_OR_EXCESSIVE')
    if (context.get('event') != 'push' or context.get('ref') != 'refs/heads/master'
            or context.get('attempt') != 1 or context.get('message', '').splitlines()[0:1] != [MERGE_TITLE]
            or a.get('merge_commit_title') != MERGE_TITLE):
        raise ValueError('EXACT_CONTINUATION_MERGE_FIRST_ATTEMPT_ONLY')
    same = [r for r in runs if r.get('event') == 'push' and r.get('head_sha') == context['sha'] and r.get('path') == WORKFLOW]
    if not same or min(r['id'] for r in same) != context['run_id']:
        raise ValueError('FIRST_FIXED_MERGE_PUSH_RUN_ONLY')
    return a


def collect_source(output):
    verify()
    event = read(os.environ['GITHUB_EVENT_PATH'])
    context = {'event':os.environ['GITHUB_EVENT_NAME'], 'ref':os.environ['GITHUB_REF'],
               'attempt':int(os.environ['GITHUB_RUN_ATTEMPT']), 'message':event['head_commit']['message'],
               'sha':os.environ['GITHUB_SHA'], 'run_id':int(os.environ['GITHUB_RUN_ID'])}
    repo = os.environ['GITHUB_REPOSITORY']
    if repo != 'leegkssk2000-commits/vultr-z':
        raise ValueError('EXACT_REPOSITORY_REQUIRED')
    # One metadata GET, separate from the35 market-source GETs; total budget36.
    url = f'https://api.github.com/repos/{repo}/actions/workflows/step7-parent-survivor-v1.yml/runs?head_sha={context["sha"]}&event=push&per_page=100'
    request = urllib.request.Request(url, headers={'Authorization':'Bearer '+os.environ['GITHUB_TOKEN'], 'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=10) as response:
        runs = json.load(response)['workflow_runs']
    allocation = source_dispatch_allowed(context, read(CAMPAIGN/'BUDGET.json'), runs)
    from backend.research.rebuild.step7_source_sequence_v1 import capture
    from backend.research.rebuild.step7_source_bridge_v1 import save
    result = capture(Path(output), allocation, f'STEP7-PATH-{context["run_id"]}-{context["sha"]}')
    result.update(github_run_id=context['run_id'], merge_sha=context['sha'],
                  scope_key=SCOPE, metadata_http_requests=1,
                  batch_total_http_requests=1+len(result.get('requests', [])),
                  raw_artifact_name='step7-path-source-'+str(context['run_id']),
                  old_source_allocation_used=1, formal_credit=0, independent_economic_executions=0)
    save(Path(output)/'PUBLIC_METADATA.json', result)
    print('STEP7_PATH_SOURCE_METADATA='+json.dumps(result, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--verify', action='store_true')
    mode.add_argument('--verify-fixture', type=Path)
    mode.add_argument('--collect-source', type=Path)
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(), sort_keys=True))
    elif args.verify_fixture:
        print(json.dumps(verify_fixture(args.verify_fixture), sort_keys=True))
    else:
        collect_source(args.collect_source)


if __name__ == '__main__':
    main()

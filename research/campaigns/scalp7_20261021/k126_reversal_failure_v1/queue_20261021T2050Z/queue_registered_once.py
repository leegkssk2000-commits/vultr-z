"""Execute the already frozen comparison only while THIS GitHub run owns the shared queue.
One invocation, no dispatch credentials, no cancellation, no trading-rule changes.
"""
from pathlib import Path
import base64, fcntl, hashlib, json, os, subprocess, sys, urllib.parse
import guard_exact_allocation_once as reads
import owner_record
S = Path(__file__).resolve().parent
O = reads.original
BRANCH = 'research/parallel-benchmark-20261017'
WORKFLOW = '.github/workflows/kp-github-access-diagnosis-20261004.yml'
PEER_GROUP = 'a1-strategy25-improvement-league-refs/heads/master'

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def dump_new(name, value):
    with (S / name).open('x') as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)

def check_members(name, data, run_id):
    members = data.get('group_members')
    if data.get('group_name', '').casefold() != name.casefold() or not isinstance(members, list) or data.get('total_count') != len(members):
        raise ValueError('INCOMPLETE_LIVE_GROUP')
    if name == O.GROUP:
        own = [m for m in members if int(m['run_id']) == run_id and m['status'] == 'in_progress']
        if len(own) != 1:
            raise ValueError('CALLER_DOES_NOT_OWN_SHARED_SLOT')
    # Pending members are behind the active assigned run, not simultaneous replays.
    return [m for m in members if int(m['run_id']) != run_id and m['status'] == 'in_progress']

def run(run_id):
    lock = (S / 'guard.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (S / 'SUMMARY.json').exists():
        print('ALREADY_COMPLETE_NO_REPLAY', flush=True)
        return
    if (S / 'STARTED.json').exists() or (S / 'START_AUTHORITY.json').exists():
        raise ValueError('EXISTING_START_REQUIRES_RESULT_REVIEW')
    binding = json.loads((S / 'QUEUE_BINDING.json').read_text())
    if digest((S / 'FREEZE.json').read_bytes()) != binding['freeze_sha256']:
        raise ValueError('FROZEN_RULE_CHANGED')
    if digest(Path(__file__).read_bytes()) != binding['runner_sha256']:
        raise ValueError('QUEUE_RUNNER_CHANGED')
    caller = reads.live_request('/actions/runs/' + str(run_id))
    if caller['status'] != 'in_progress' or caller['event'] != 'push' or caller['head_branch'] != BRANCH or caller['path'].split('@')[0] != WORKFLOW:
        raise ValueError('UNAUTHORIZED_QUEUE_CALLER')
    if caller.get('actor', {}).get('id') != 232057951:
        raise ValueError('UNEXPECTED_QUEUE_ACTOR')
    for path, expected in [(WORKFLOW, binding['workflow_sha256']), (binding['request_path'], binding['request_sha256'])]:
        body = reads.live_request('/contents/' + path + '?ref=' + caller['head_sha'])
        if body.get('encoding') != 'base64' or digest(base64.b64decode(body['content'])) != expected:
            raise ValueError('QUEUED_SOURCE_NOT_EXACT:' + path)
    listing = reads.live_request('/actions/concurrency_groups?per_page=100')
    groups = listing.get('concurrency_groups')
    if not isinstance(groups, list) or listing.get('total_count') != len(groups):
        raise ValueError('INCOMPLETE_GROUP_LIST')
    byname = {g['group_name']: g for g in groups}
    if O.GROUP not in byname:
        raise ValueError('SHARED_QUEUE_ASSIGNMENT_MISSING')
    evidence = [{'caller': {k: caller[k] for k in ('id', 'head_sha', 'head_branch', 'path', 'status', 'event')}}]
    busy = []
    for name in [O.GROUP, PEER_GROUP]:
        if name not in byname:
            continue
        group = reads.live_request('/actions/concurrency_groups/' + urllib.parse.quote(name, safe=''))
        busy.extend(check_members(name, group, run_id))
        evidence.append({'group': group, 'checked_at_utc': O.now()})
    local = O.local_busy()
    if busy or local:
        raise ValueError('OTHER_ACTUAL_ECONOMIC_EXECUTION:' + json.dumps({'github': busy, 'local': local}))
    receipt = owner_record.update('ACTIVE', {'github_run_id': run_id, 'phase_detail': 'ASSIGNED_SHARED_QUEUE_FROZEN_POSTENTRY_COMPARISON', 'economic_started': False})
    auth = {'at_utc': O.now(), 'owner': owner_record.OWNER, 'candidate': owner_record.CANDIDATE, 'capacity': 'CLEAR',
            'actual_assigned_github_run': run_id, 'github_runs': evidence, 'local_economic_processes': local,
            'owner_commit': receipt['commit'], 'prepared_commit': '34df33538653d14fea12c56473782eb776068b22',
            'new_hypothesis_cap': 1, 'S_budget_consumed': 0, 'C_budget_consumed': 0,
            'user_instruction': 'Proceed with improving the preserved K126 baseline by the already frozen post-entry loss comparison.'}
    dump_new('START_AUTHORITY.json', auth)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')
    with (S / 'EXECUTION.log').open('x') as log:
        child = subprocess.Popen([O.PY, '-u', '-B', str(S / 'run_compare.py')], cwd=S, env=env, stdout=log, stderr=subprocess.STDOUT)
        O.emit('ASSIGNED_QUEUE_COMPARISON_STARTED', github_run_id=run_id, child_pid=child.pid, economic_started=True)
        try:
            code = child.wait(timeout=600)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait()
            raise RuntimeError('OWN_COMPARISON_TIMEOUT_NO_RETRY')
    if code:
        raise RuntimeError('COMPARISON_EXIT_' + str(code))
    O.emit('COMPARISON_COMPLETE_AUDITING', github_run_id=run_id, economic_started=True)
    subprocess.run([O.PY, '-u', '-B', str(S / 'audit_and_store.py')], cwd=S, env=env, timeout=240, check=True)
    O.emit('RESULT_STORED_OWNER_RELEASED', github_run_id=run_id, economic_started=True)
    print((S / 'RESULT.md').read_text(), flush=True)

if __name__ == '__main__':
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        raise SystemExit('EXACT_GITHUB_RUN_ID_REQUIRED')
    try:
        run(int(sys.argv[1]))
    except Exception as exc:
        O.emit('QUEUED_EXECUTION_STOP_NO_BLIND_RETRY', github_run_id=int(sys.argv[1]), error_type=type(exc).__name__, error=str(exc), economic_started=(S / 'STARTED.json').exists())
        raise

"""Small file-backed dispatch gate for research scopes, never an operating owner."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

SCOPE = 'TOP5_LIFECYCLE_AI_G5_AFTER_PR1204'
WORK = tuple('W'+str(i) for i in range(1, 8))
TERMINAL = {'DONE', 'NOT_RUN', 'N/A'}

def utc():
    return datetime.now(timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()

class GateError(RuntimeError):
    pass

class Registry:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            data = json.loads(self.path.read_text()) if self.path.exists() else {'schema': 'research.scope.v1', 'tasks': {}}
            yield data
            tmp = self.path.with_suffix('.tmp')
            with tmp.open('w') as f:
                json.dump(data, f, sort_keys=True, indent=2, allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.path)

    def get(self, scope):
        with self.transaction() as data:
            return deepcopy(data['tasks'][scope])

    def register(self, scope, approval, *, parent='PR1204', document=None, requested_id=None, resume=False):
        if not approval: raise GateError('EXPLICIT_SCOPE_APPROVAL_REQUIRED')
        with self.transaction() as data:
            if scope not in data['tasks']:
                now = utc()
                data['tasks'][scope] = {
                    'scope_key': scope, 'task_id': 'task-'+digest(scope)[:16],
                    'scope_hash': digest({'scope': scope, 'candidate_max': 2, 'gemini_max': 1, 'openai_max': 1, 'usd_max': 5}),
                    'approval_ref': approval, 'parent_task_ref': parent, 'task_status': 'RUNNING',
                    'execution_started_at': now, 'last_real_progress_at': now, 'execution_finished_at': None,
                    'work': {w: {'status': 'PENDING'} for w in WORK}, 'attempts': {},
                    'candidate_budget_used': 0, 'paid_requests': {'gemini': 0, 'openai': 0},
                    'settled_cost': 0., 'outstanding_reserved_cost': 0., 'billing_status': 'NOT_CALLED',
                    'final_head': None, 'merge_sha': None, 'required_run_ids': [],
                    'owned_running_jobs': [], 'protected_background_jobs': ['Q0', 'G5B', 'existing_collectors', 'other_work'],
                    'remaining_execution': list(WORK), 'unresolved_items': [],
                    'report_only': False, 'further_dispatch_allowed': True,
                    'platform_ui_state': 'UNKNOWN', 'account_charge': 'UNKNOWN'}
            task = data['tasks'][scope]
            if resume and task['task_status'] == 'CHECKPOINTED':
                task.update(task_status='RUNNING', report_only=False, further_dispatch_allowed=True)
            return deepcopy(task)

    @staticmethod
    def _active(task):
        if task['task_status'] != 'RUNNING' or not task['further_dispatch_allowed']:
            raise GateError('SCOPE_DISPATCH_CLOSED')

    def reserve(self, scope, work, kind, identity, *, provider=None, reserve_usd=0., command=None):
        with self.transaction() as data:
            t = data['tasks'][scope]; self._active(t)
            if t['work'][work]['status'] in TERMINAL: raise GateError('WORK_ALREADY_HANDLED')
            key = digest({'kind': kind, 'identity': identity})
            # Scope/filename changes cannot duplicate identical market or paid requests.
            for other in data['tasks'].values():
                if key in other['attempts']: raise GateError('IDENTITY_ALREADY_RESERVED_OR_EXECUTED')
            if kind == 'economic':
                if t['candidate_budget_used'] >= 2: raise GateError('CANDIDATE_BUDGET')
                t['candidate_budget_used'] += 1
            if kind == 'api':
                if provider not in ('gemini', 'openai') or t['paid_requests'][provider] >= 1: raise GateError('PROVIDER_BUDGET')
                if t['billing_status'] == 'UNKNOWN': raise GateError('UNRECONCILED_BILLING')
                if not 0 < reserve_usd <= 5 or t['settled_cost'] + t['outstanding_reserved_cost'] + reserve_usd > 5:
                    raise GateError('USD_RESERVATION_LIMIT')
                t['paid_requests'][provider] += 1; t['outstanding_reserved_cost'] += reserve_usd
                t['billing_status'] = 'RESERVED'
            t['attempts'][key] = {'kind': kind, 'work': work, 'identity': identity, 'status': 'RESERVED',
                'provider': provider, 'reserved_usd': reserve_usd, 'settled_usd': None, 'utc': utc(),
                'command': command, 'pid': os.getpid()}
            t['work'][work]['status'] = 'RUNNING'; t['last_real_progress_at'] = utc()
            return key

    def finish_attempt(self, scope, key, status, *, evidence=None, settled_usd=None):
        with self.transaction() as data:
            t = data['tasks'][scope]; a = t['attempts'][key]
            if a['status'] != 'RESERVED': raise GateError('ATTEMPT_ALREADY_FINISHED')
            a.update(status=status, evidence=evidence, ended_at=utc())
            if a['kind'] == 'api':
                if settled_usd is None:
                    t['billing_status'] = 'UNKNOWN'
                else:
                    if not 0 <= settled_usd <= a['reserved_usd']: raise GateError('SETTLEMENT_OUTSIDE_RESERVATION')
                    a['settled_usd'] = settled_usd
                    t['settled_cost'] += settled_usd; t['outstanding_reserved_cost'] -= a['reserved_usd']
                    t['billing_status'] = 'SETTLED'
            t['last_real_progress_at'] = utc()

    def mark(self, scope, work, status, evidence):
        if status not in TERMINAL | {'PENDING', 'RUNNING', 'BLOCKED'} or not evidence: raise GateError('WORK_EVIDENCE_REQUIRED')
        with self.transaction() as data:
            t = data['tasks'][scope]; self._active(t)
            if work == 'W6' and status == 'DONE': raise GateError('USE_BOUND_MERGE_PROOF')
            if t['work'][work]['status'] in TERMINAL:
                if t['work'][work] == {'status': status, 'evidence': evidence}: return
                raise GateError('TERMINAL_WORK_IMMUTABLE')
            t['work'][work] = {'status': status, 'evidence': evidence}
            t['remaining_execution'] = [w for w in WORK if t['work'][w]['status'] not in TERMINAL]
            t['last_real_progress_at'] = utc()

    def bind_merge(self, scope, *, final_head, merge_sha, ci, reproduction):
        with self.transaction() as data:
            t = data['tasks'][scope]; self._active(t)
            for r, sha in ((ci, final_head), (reproduction, merge_sha)):
                if r.get('scope_key') != scope or r.get('head_sha') != sha or r.get('conclusion') != 'success' or not r.get('run_id'):
                    raise GateError('EXACT_SCOPE_HEAD_RUN_PROOF_REQUIRED')
            if ci.get('kind') != 'final_ci' or reproduction.get('kind') != 'merge_reproduction': raise GateError('WRONG_PROOF_KIND')
            t.update(final_head=final_head, merge_sha=merge_sha, required_run_ids=[ci['run_id'], reproduction['run_id']])
            t['work']['W6'] = {'status': 'DONE', 'evidence': [ci, reproduction]}
            t['remaining_execution'] = [w for w in WORK if t['work'][w]['status'] not in TERMINAL]

    def close(self, scope, *, checkpoint=False, jobs=None, unresolved=()):
        with self.transaction() as data:
            t = data['tasks'][scope]
            if t['task_status'] == 'COMPLETED':
                if checkpoint: raise GateError('COMPLETED_SCOPE_IMMUTABLE')
                return deepcopy(t)
            remaining = [w for w in WORK if t['work'][w]['status'] not in TERMINAL]
            jobs = t['owned_running_jobs'] if jobs is None else jobs
            owned = [j for j in jobs if j.get('scope_key') == scope and not j.get('protected')]
            active = [k for k,a in t['attempts'].items() if a['status'] in ('RESERVED', 'UNKNOWN')]
            if not checkpoint and (remaining or owned or active): raise GateError('REMAINING_REQUIRED_OR_UNKNOWN_EXECUTION')
            t.update(task_status='CHECKPOINTED' if checkpoint else 'COMPLETED', report_only=True,
                further_dispatch_allowed=False, remaining_execution=remaining,
                owned_running_jobs=owned, unresolved_items=list(unresolved)+active,
                execution_finished_at=None if checkpoint else utc())
            return deepcopy(t)

    def run_command(self, scope, work, identity, command, *, timeout_seconds, cwd=None):
        if not 0 < timeout_seconds <= 2700: raise GateError('FINITE_TIMEOUT_REQUIRED')
        key = self.reserve(scope, work, 'command', identity, command=command)
        try:
            result = subprocess.run(command, cwd=cwd, timeout=timeout_seconds, capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            self.finish_attempt(scope, key, 'UNKNOWN', evidence='LOCAL_TIMEOUT; external descendants not presumed cancelled')
            self.close(scope, checkpoint=True, unresolved=['command timeout: '+key]); raise
        self.finish_attempt(scope, key, 'DONE' if result.returncode == 0 else 'FAILED', evidence={'returncode': result.returncode})
        return result

def bounded_wait(poll, *, timeout_seconds, max_polls, clock=time.monotonic, pause=time.sleep):
    if not 0 < timeout_seconds <= 60 or not 1 <= max_polls <= 60: raise GateError('FINITE_POLL_REQUIRED')
    end = clock()+timeout_seconds
    for _ in range(max_polls):
        result = poll()
        if result.get('status') == 'completed': return result
        if clock() >= end: break
        pause(min(1., max(0., end-clock())))
    return {'status': 'UNKNOWN', 'last_observation': result}

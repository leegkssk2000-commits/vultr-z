"""Bounded repair of the existing one-shot waiter; respects GitHub rate limits.
No credentials, endpoint switching, economic-rule changes, or new scheduling.
"""
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl, hashlib, json, os, subprocess, sys, time, urllib.error, urllib.request
import guarded_once as g
S = Path(__file__).resolve().parent
ORIGINAL_GUARD_SHA = 'a86934fed27bde13c94cf6bc11cdfca1169b6a024fa0048f2c4b68e4700dfb27'
INITIAL_NOT_BEFORE = 1792589267 + 3  # Actual X-RateLimit-Reset, plus safety margin.
POLL_SECONDS = 180
MAX_REQUESTS = 45
class RateWait(Exception):
    def __init__(self, until):
        self.until = float(until)
        super().__init__('RATE_LIMIT_WAIT_UNTIL_' + str(until))
def retry_time(headers, body, code, wall_now):
    h = {k.lower(): str(v) for k, v in headers.items()}
    if code not in (403, 429):
        return None
    limited = code == 429 or h.get('x-ratelimit-remaining') == '0' or 'rate limit' in body.lower() or 'retry-after' in h
    if not limited:
        return None
    times = [wall_now + 60]
    if h.get('retry-after'):
        try:
            times.append(wall_now + float(h['retry-after']))
        except ValueError:
            times.append(parsedate_to_datetime(h['retry-after']).timestamp())
    if h.get('x-ratelimit-remaining') == '0' and h.get('x-ratelimit-reset'):
        times.append(float(h['x-ratelimit-reset']) + 3)
    return max(times)
def main():
    if g.sha((S/'guarded_once.py').read_bytes()) != ORIGINAL_GUARD_SHA:
        raise ValueError('ORIGINAL_EXECUTION_ENVELOPE_CHANGED')
    lock = (S/'invocation.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (S/'SUMMARY.json').exists():
        g.emit('ALREADY_COMPLETE_NO_REPLAY'); return
    if (S/'STARTED.json').exists():
        raise RuntimeError('PARTIAL_ALREADY_STARTED_REVIEW_NOT_RETRY')
    deadline = time.monotonic() + 2400
    not_before = INITIAL_NOT_BEFORE
    requests = 0
    rate_hits = 0
    specs = {}
    def request(url):
        nonlocal requests
        immutable_spec = '/contents/' in url and '?ref=' in url
        if immutable_spec and url in specs:
            return specs[url]
        if requests >= MAX_REQUESTS:
            raise RuntimeError('BOUNDED_REQUEST_BUDGET_EXHAUSTED_NO_BYPASS')
        requests += 1
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'zel-existing-coordinator-rate-aware-gate'}), timeout=15) as r:
                value = json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read(4096).decode(errors='replace')
            until = retry_time(e.headers, body, e.code, time.time())
            if until is None:
                raise
            raise RateWait(until) from e
        if immutable_spec:
            specs[url] = value
        return value
    g.request = request
    known_holders = [39600071418]
    while time.monotonic() < deadline:
        if time.time() < not_before:
            remaining = not_before - time.time()
            g.emit('WAIT_RATE_LIMIT_RESET', next_allowed_utc=datetime.fromtimestamp(not_before, timezone.utc).isoformat(), economic_started=False, request_count=requests)
            if remaining >= deadline-time.monotonic():
                g.emit('WAIT_BOUND_BEFORE_RATE_RESET', economic_started=False); return
            time.sleep(remaining)
        try:
            still_busy = []
            for run_id in known_holders:
                row = request(g.API + '/actions/runs/' + str(run_id))
                if row['status'] != 'completed':
                    still_busy.append({'id':run_id, 'name':row.get('name'), 'status':row['status']})
            if still_busy:
                g.emit('WAITING_SHARED_HEAVY', holders=still_busy, economic_started=False, request_count=requests)
                time.sleep(min(POLL_SECONDS, max(0, deadline-time.monotonic())))
                continue
            busy, observations = g.busy_runs()
            if busy:
                known_holders = [r['id'] for r in busy]
                g.emit('WAITING_SHARED_HEAVY', holders=busy, economic_started=False, request_count=requests)
                time.sleep(min(POLL_SECONDS, max(0, deadline-time.monotonic())))
                continue
        except RateWait as e:
            rate_hits += 1
            if rate_hits > 2:
                g.emit('RATE_LIMIT_RETRY_BOUND_REACHED', next_allowed_epoch=e.until, economic_started=False); return
            not_before = e.until
            continue
        g.emit('CAPACITY_CLEAR_START_ONCE', observed_runs=observations, economic_started=False, request_count=requests)
        with (S/'EXECUTION.log').open('x') as log:
            rc = subprocess.run([g.PY, '-u', '-B', str(S/'guarded_once.py'), 'execute-cached'], stdout=log, stderr=subprocess.STDOUT, timeout=600,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1')).returncode
        if rc:
            g.emit('EXECUTION_FAILED_NO_BLIND_RETRY', exit_code=rc); return
        g.emit('ECONOMIC_COMPARISON_COMPLETE', summary_sha256=g.sha((S/'SUMMARY.json').read_bytes()), economic_started=True)
        g.report(); g.emit('COMPLETE_STORED', economic_started=True); return
    g.emit('WAIT_BOUND_REACHED_NO_ECONOMIC_START', economic_started=False)
if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        g.emit('HOLD', error=type(exc).__name__, message=str(exc), no_automatic_retry=True)
        raise

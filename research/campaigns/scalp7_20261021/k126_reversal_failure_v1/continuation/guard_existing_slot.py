"""Bounded existing-owner continuation, not a daemon, scheduler or alternate slot."""
from pathlib import Path
from datetime import datetime,timezone
import base64,fcntl,json,os,subprocess,sys,time,urllib.request,urllib.error
import owner_record
S=Path(__file__).resolve().parent
API='https://api.github.com/repos/leegkssk2000-commits/vultr-z'
GROUP='a1-global-heavy-economic-evaluator-v1'
PY='/home/z/z/venv/bin/python'
REQUESTS=0;CACHE={};DEADLINE=0
def now():return datetime.now(timezone.utc).isoformat()
def emit(state,**extra):
    v={'at_utc':now(),'state':state,'guard_pid':os.getpid(),'public_requests':REQUESTS,**extra}
    with (S/'GUARD_EVENTS.jsonl').open('a') as f:f.write(json.dumps(v)+'\n')
    (S/'GUARD_STATUS.tmp').write_text(json.dumps(v,indent=2)+'\n');os.replace(S/'GUARD_STATUS.tmp',S/'GUARD_STATUS.json')
    print(json.dumps(v),flush=True)
def request(path):
    global REQUESTS
    if REQUESTS>=35:raise RuntimeError('PUBLIC_REQUEST_BUDGET_REACHED')
    REQUESTS+=1
    req=urllib.request.Request(API+path,headers={'User-Agent':'zel-existing-owner-bounded-replay'})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code not in (403,429) or not (e.headers.get('X-RateLimit-Remaining')=='0' or e.headers.get('Retry-After')):raise
        reset=max(time.time()+int(e.headers.get('Retry-After','0')),int(e.headers.get('X-RateLimit-Reset','0'))+3)
        delay=max(reset-time.time(),1)
        emit('RATE_LIMIT_OBSERVED_NO_BYPASS',http_status=e.code,reset_utc=datetime.fromtimestamp(reset,timezone.utc).isoformat(),economic_started=False)
        if time.monotonic()+delay>=DEADLINE:raise RuntimeError('RATE_RESET_BEYOND_BOUNDED_WAIT')
        time.sleep(delay)
        raise RuntimeError('RATE_LIMIT_WAITED_REQUIRES_REVIEW_NO_BLIND_REPEAT')
def capacity():
    seen={};observations=[];busy=[]
    for status in ('in_progress','pending','waiting','queued'):
        result=request('/actions/runs?status='+status+'&per_page=100')
        if result['total_count']>len(result['workflow_runs']):raise RuntimeError('INCOMPLETE_CAPACITY_PAGE')
        for row in result['workflow_runs']:
            if row['id'] in seen:continue
            seen[row['id']]=True
            path=row['path'].split('@')[0];k=(path,row['head_sha'])
            if k not in CACHE:
                data=request('/contents/'+path+'?ref='+row['head_sha'])
                CACHE[k]=base64.b64decode(data['content']).decode()
            item={k:row[k] for k in ('id','name','status','head_sha')};item['global_heavy']=GROUP in CACHE[k]
            observations.append(item)
            if item['global_heavy']:busy.append(item)
    return busy,observations
def local_busy():
    busy=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name)==os.getpid():continue
        try:args=[x.decode(errors='replace') for x in (p/'cmdline').read_bytes().split(b'\0') if x]
        except OSError:continue
        if not args or 'python' not in Path(args[0]).name:continue
        if any(a.endswith('/run_compare.py') or a.endswith('/run_h02.py') or a.endswith('/run_handoff.py') or a.endswith('/run_chronological.py') for a in args) or ('--candidate' in args and any(a.endswith('adapter.py') for a in args)):
            busy.append({'pid':int(p.name),'argv':args})
    return busy
def main():
    global DEADLINE
    lock=(S/'guard.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if (S/'SUMMARY.json').exists():emit('COMPLETE_EXISTS_NO_REPLAY');return
    if (S/'STARTED.json').exists():raise RuntimeError('STARTED_EXISTS_NO_BLIND_REPLAY')
    DEADLINE=time.monotonic()+2700
    holder=39646263948
    emit('WAITING_EXISTING_SHARED_HEAVY',holder=holder,wait_seconds_limit=2700,economic_started=False)
    while time.monotonic()<DEADLINE:
        row=request('/actions/runs/'+str(holder)) if holder else None
        if row is not None and row['status']!='completed':
            emit('WAITING_EXISTING_SHARED_HEAVY',holder=holder,holder_status=row['status'],economic_started=False)
            time.sleep(180);continue
        busy,observed=capacity();local=local_busy()
        if busy or local:
            emit('WAITING_CAPACITY',heavy_runs=busy,local=local,economic_started=False)
            holder=busy[0]['id'] if busy else None
            time.sleep(180);continue
        if time.monotonic()>=DEADLINE:break
        receipt=owner_record.update('ACTIVE',{'capacity_checked_at_utc':now(),'phase_detail':'ONE_FROZEN_POSTENTRY_COMPARISON','economic_started':False})
        auth={'at_utc':now(),'owner':owner_record.OWNER,'candidate':owner_record.CANDIDATE,'capacity':'CLEAR','github_runs':observed,'local_economic_processes':local,
            'prepared_commit':'34df33538653d14fea12c56473782eb776068b22','owner_commit':receipt['commit'],'new_hypothesis_cap':1,'S_budget_consumed':0,'C_budget_consumed':0,
            'user_instruction':'Preserve incumbent and verify losses unnecessarily incurred after observed failure; broaden external primary research if insufficient.'}
        with (S/'START_AUTHORITY.json').open('x') as f:json.dump(auth,f,indent=2)
        with (S/'EXECUTION.log').open('x') as log:
            process=subprocess.Popen([PY,'-u','-B',str(S/'run_compare.py')],cwd=S,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
            emit('ACTUAL_COMPARISON_PROCESS_STARTED',economic_started=True,child_pid=process.pid,timeout_seconds=600)
            try:rc=process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                emit('OWN_COMPARISON_TIMEOUT_PRESERVED_NO_RETRY',economic_started=True);return
        if rc:
            emit('COMPARISON_FAILED_PRESERVED_NO_RETRY',exit_code=rc,economic_started=True);return
        emit('COMPARISON_COMPLETE_AUDITING',economic_started=True)
        rc=subprocess.run([PY,'-u','-B',str(S/'audit_and_store.py')],cwd=S,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),timeout=240).returncode
        emit('RESULT_STORED_OWNER_RELEASED' if rc==0 else 'RESULT_COMPLETE_AUDIT_OR_STORAGE_FAILED_DO_NOT_REPLAY',exit_code=rc,economic_started=True)
        return
    emit('WAIT_LIMIT_REACHED_NO_ECONOMIC_START',economic_started=False)
if __name__=='__main__':
    try:main()
    except Exception as e:
        emit('HOLD_REVIEW_REQUIRED',error_type=type(e).__name__,error=str(e),economic_started=(S/'STARTED.json').exists())
        raise

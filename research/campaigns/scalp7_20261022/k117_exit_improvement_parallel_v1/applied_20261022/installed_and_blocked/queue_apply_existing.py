"""One invocation of existing C/D observers only when this run owns the shared slot."""
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
import sys,os,json,subprocess,hashlib,fcntl,importlib.util,base64
S=Path(__file__).resolve().parent
sys.path.insert(0,str(S));import owner_claim
sys.path.insert(0,'/home/z/z/runtime/k126_reversal_bar_failure_20261021_v1')
import guard_exact_allocation_once as cap
cap.S=S;cap.original.S=S
OWNER=owner_claim.OWNER
WF='.github/workflows/kp-github-access-diagnosis-20261004.yml'
BRANCH='research/parallel-benchmark-20261017'
GROUP='a1-global-heavy-economic-evaluator-v1'
BASE=Path('/home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1')
CROOT=Path('/home/z/worktrees/zel-work-c-k117-exit-observer-v1')
DROOT=Path('/home/z/worktrees/zel-work-d-k117-be-observer-v1')
REL='research/campaigns/scalp7_20261022/k117_exit_improvement_parallel_v1/'
COUT=Path('/home/z/z/runtime/k117_passive_exit_observer_c_20261022_v1')
DOUT=Path('/home/z/k117_be_observer_d_once_20261022_v1')
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def put(name,v):
    with (S/name).open('x') as f:json.dump(v,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
def assigned(run):
    busy,evidence=cap.live_capacity()
    mine=[x for x in busy if int(x['id'])==run and x['group']==GROUP and x['status']=='in_progress']
    other=[x for x in busy if int(x['id'])!=run and (x['status']=='in_progress' or x['group']!=GROUP)]
    local=cap.original.local_busy()
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name)==os.getpid():continue
        try:a=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
        except OSError:continue
        if ('run_owner_exit_observer.py --' in a or 'run_owner_be_observer.py --' in a) and a.startswith(('/home/z/z/venv/bin/python','python')):local.append({'pid':int(p.name),'cmd':a})
    if len(mine)!=1 or other or local:raise RuntimeError('ASSIGNED_CAPACITY_REQUIRED:'+json.dumps({'mine':mine,'other':other,'local':local}))
    with (S/'ASSIGNMENT_CHECKS.jsonl').open('a') as f:f.write(json.dumps({'at_utc':now(),'run':run,'evidence':evidence,'local':local})+'\n')
    return evidence

def verify_caller(run):
    b=json.loads((S/'QUEUE_BINDING.json').read_bytes())
    if sha(Path(__file__).read_bytes())!=b['runner_sha256']:raise ValueError('RUNNER_CHANGED')
    r=cap.live_request('/actions/runs/'+str(run))
    if r['event']!='push' or r['head_branch']!=BRANCH or r['path'].split('@')[0]!=WF or r['status']!='in_progress' or r['actor']['id']!=232057951:raise ValueError('WRONG_CALLER')
    for p,pin in [(WF,b['workflow_sha256']),(b['request_path'],b['request_sha256'])]:
        d=cap.live_request('/contents/'+p+'?ref='+r['head_sha'])
        if d.get('encoding')!='base64' or sha(base64.b64decode(d['content']))!=pin:raise ValueError('CALLER_SOURCE_MISMATCH')
    assigned(run)
    return r

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

def child(run,which):
    assigned(run)
    if which=='C':
        h=module('_owner_exact_k117_c',CROOT/REL/'work_c/run_owner_exit_observer.py')
        original=h.bind_runtime
        def assigned_bind(path):
            parts=original(path)
            parts[0].require_capacity=lambda unused:assigned(run)
            return parts
        h.bind_runtime=assigned_bind
        h.run(SimpleNamespace(bind_only=False,run_once=True,owner_ack=OWNER,baseline_input_dir=BASE,output_dir=COUT))
    elif which=='D':
        h=module('_owner_exact_k117_d',DROOT/REL/'work_d/run_owner_be_observer.py')
        h.run(SimpleNamespace(run_once=True,owner_ack=OWNER,baseline_dir=BASE,output_dir=DOUT))
    else:raise ValueError('BAD_PHASE')

def run_once(run):
    with (S/'apply_once.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        caller=verify_caller(run)
        put('QUEUE_INVOKED.json',{'at_utc':now(),'run':run,'head_sha':caller['head_sha'],'native_policy_changed':False,'new_policy_comparisons':0})
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
        for which,out,receipt in [('C',COUT,'PASSIVE_EXIT_OBSERVER_RECEIPT.json'),('D',DOUT,'OBSERVER_RECEIPT.json')]:
            if out.exists():raise ValueError('PRIOR_OUTPUT_INSPECT_NO_REPLAY:'+str(out))
            assigned(run)
            owner_claim.update('ACTIVE_'+which,{'phase_detail':'EXACT_SHARED_ASSIGNED_PASSIVE_'+which,'github_run_id':run,'new_policy_comparisons':0,'native_policy_changed':False})
            cmd=['/home/z/z/venv/bin/python','-u','-B',str(Path(__file__)),str(run),which]
            with (S/(which+'_EXECUTION.log')).open('x') as log:
                p=subprocess.Popen(cmd,cwd=S,env=env,stdout=log,stderr=subprocess.STDOUT)
                put('PROCESS_'+which+'.json',{'at_utc':now(),'pid':p.pid,'command':cmd,'output':str(out)})
                print('NATIVE_OBSERVER_STARTED',which,p.pid,flush=True)
                try:code=p.wait(timeout=900)
                except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=20);raise RuntimeError('OWN_OBSERVER_TIME_LIMIT_NO_RETRY')
            put('EXIT_'+which+'.json',{'at_utc':now(),'exit_code':code,'receipt_exists':(out/receipt).exists()})
            if code or not (out/receipt).exists():raise RuntimeError('OBSERVER_FAILED:'+which+':'+(S/(which+'_EXECUTION.log')).read_text()[-5000:])
            print('OBSERVER_COMPLETE',which,flush=True)
        subprocess.run(['/home/z/z/venv/bin/python','-B',str(S/'report_traces.py')],cwd=S,env=env,check=True,timeout=120)
        print('BOTH_APPLIED_FINDINGS_READY',flush=True)
if __name__=='__main__':
    if len(sys.argv) not in (2,3) or not sys.argv[1].isdigit():raise SystemExit('EXACT_RUN_REQUIRED')
    try:
        if len(sys.argv)==3:child(int(sys.argv[1]),sys.argv[2])
        else:run_once(int(sys.argv[1]))
    except Exception as e:
        if len(sys.argv)==2 and not (S/'QUEUE_FAILURE.json').exists():put('QUEUE_FAILURE.json',{'at_utc':now(),'error':str(e),'no_blind_retry':True})
        raise

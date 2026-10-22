"""Apply one delivered observer once, through existing owner and shared capacity."""
from pathlib import Path
from datetime import datetime, timezone
import os,sys,json,subprocess,hashlib,fcntl
S=Path(__file__).resolve().parent
sys.path.insert(0,str(S));import owner_claim
sys.path.insert(0,'/home/z/z/runtime/k126_reversal_bar_failure_20261021_v1')
import guard_exact_allocation_once as capacity
BASE='/home/z/z/runtime/k126_veto_objective_lifetime_20261022_v1'
REL='research/campaigns/scalp7_20261022/k117_exit_improvement_parallel_v1/'
PACKAGES={
'C':{'root':'/home/z/worktrees/zel-work-c-k117-exit-observer-v1','commit':'48570b3e55b23cc40c69fd9d6e89fd3614dc476c','script':REL+'work_c/run_owner_exit_observer.py','baseline_flag':'--baseline-input-dir','output':'/home/z/z/runtime/k117_passive_exit_observer_c_20261022_v1','receipt':'PASSIVE_EXIT_OBSERVER_RECEIPT.json'},
'D':{'root':'/home/z/worktrees/zel-work-d-k117-be-observer-v1','commit':'af9451b4ad7efc2111bf88a1901df2d9a8a71a49','script':REL+'work_d/run_owner_be_observer.py','baseline_flag':'--baseline-dir','output':'/home/z/k117_be_observer_d_once_20261022_v1','receipt':'OBSERVER_RECEIPT.json'}}
def now():return datetime.now(timezone.utc).isoformat()
def put(name,value):
    with (S/name).open('x') as f:json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
def run(which):
    p=PACKAGES[which];out=Path(p['output'])
    if out.exists(): raise ValueError('OUTPUT_EXISTS_INSPECT_NO_BLIND_RERUN:'+str(out))
    head=subprocess.check_output(['git','-C',p['root'],'rev-parse','HEAD']).decode().strip()
    if head!=p['commit']:raise ValueError('DELIVERY_COMMIT_CHANGED')
    subprocess.run(['git','-C',p['root'],'diff','--exit-code','HEAD','--',REL],check=True)
    with (S/'apply_once.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        capacity.S=S;capacity.original.S=S
        busy,evidence=capacity.live_capacity();local=capacity.original.local_busy()
        pre={'at_utc':now(),'which':which,'busy':busy,'local':local,'evidence':evidence,'native_started':False}
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        put('PREFLIGHT_'+which+'_'+stamp+'.json',pre)
        if busy or local:
            print('CAPACITY_BUSY_NO_NATIVE_START',json.dumps(pre,ensure_ascii=False),flush=True);return 3
        authority=owner_claim.update('ACTIVE_'+which,{'phase_detail':'APPLY_EXACT_'+which+'_PASSIVE_NATIVE_OBSERVER','capacity_checked_at_utc':pre['at_utc'],'policy_changed':False,'new_policy_comparisons':0})
        busy,evidence=capacity.live_capacity();local=capacity.original.local_busy()
        if busy or local:
            put('CAPACITY_CHANGED_'+which+'_'+stamp+'.json',{'at_utc':now(),'busy':busy,'local':local,'native_started':False})
            print('CAPACITY_CHANGED_BEFORE_NATIVE_START',flush=True);return 3
        cmd=['/home/z/z/venv/bin/python','-u','-B',str(Path(p['root'])/p['script']),'--owner-ack',owner_claim.OWNER,'--run-once',p['baseline_flag'],BASE,'--output-dir',str(out)]
        put('INVOKE_'+which+'.json',{'at_utc':now(),'command':cmd,'delivery_commit':head,'script_sha256':hashlib.sha256((Path(p['root'])/p['script']).read_bytes()).hexdigest(),'owner_commit':authority['commit'],'no_new_policy':True})
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
        with (S/(which+'_EXECUTION.log')).open('x') as log:
            proc=subprocess.Popen(cmd,cwd=p['root'],env=env,stdout=log,stderr=subprocess.STDOUT)
            put('PROCESS_'+which+'.json',{'at_utc':now(),'pid':proc.pid,'command':cmd,'output':str(out)})
            print('NATIVE_OBSERVER_STARTED',which,proc.pid,flush=True)
            try:code=proc.wait(timeout=1200)
            except subprocess.TimeoutExpired:
                proc.terminate();code=proc.wait(timeout=30)
                put('TIME_LIMIT_'+which+'.json',{'at_utc':now(),'pid':proc.pid,'no_blind_retry':True})
        receipt=out/p['receipt']
        put('EXIT_'+which+'.json',{'at_utc':now(),'exit_code':code,'receipt_exists':receipt.exists(),'no_blind_retry':True})
        print('NATIVE_OBSERVER_EXIT',which,code,'RECEIPT',receipt.exists(),flush=True)
        if code or not receipt.exists():print((S/(which+'_EXECUTION.log')).read_text()[-6000:],flush=True);return 1
        print(receipt.read_text(),flush=True)
        return 0
if __name__=='__main__':sys.exit(run(sys.argv[1]))

"""Single immediate consumption of C's exact-incumbent observer, no waiting service."""
from pathlib import Path
from datetime import datetime,timezone
import sys,os,json,fcntl,subprocess,hashlib
S=Path(__file__).resolve().parent
sys.path.insert(0,str(S))
import owner_record
G=Path('/home/z/z/runtime/k126_reversal_bar_failure_20261021_v1')
sys.path.append(str(G))
import guard_exact_allocation_once as capacity
capacity.S=S;capacity.original.S=S;capacity.original.REQUESTS=0
PY='/home/z/z/venv/bin/python'
def now():return datetime.now(timezone.utc).isoformat()
def save(n,v):
 with (S/n).open('x') as f:json.dump(v,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
def main():
 with (S/'consume.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  out=S/'observer'
  if out.exists():raise RuntimeError('OBSERVER_PATH_EXISTS_REVIEW_BEFORE_REPLAY')
  pins=json.loads((S/'EXTRACT_RECEIPT.json').read_text())['files_sha256']
  for n,pin in pins.items():
   if hashlib.sha256((S/'work_c_exact'/n).read_bytes()).hexdigest()!=pin:raise RuntimeError('C_DELIVERY_CHANGED:'+n)
  busy,evidence=capacity.live_capacity();local=capacity.original.local_busy()
  if busy or local:
   save('CAPACITY_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json',{'at_utc':now(),'busy':busy,'local':local,'evidence':evidence,'source_replay_started':False})
   print('BUSY_NO_REPLAY_NO_DAEMON',json.dumps(busy),flush=True);return
  bound=owner_record.update('ACTIVE',{'phase_detail':'EXACT_INCUMBENT_C_ORIGIN_TRACE','economic_started':False,'new_policy_comparisons':0,'D_risk_required_input_does_not_block_C':True})
  save('OBSERVER_AUTHORITY.json',{'at_utc':now(),'owner':owner_record.OWNER,'owner_commit':bound['commit'],'source_commit':'77ce5616ed6e29c421592f319e7253b81dd79bdc','new_policy_comparisons':0,'single_candidate_cap':1,'orders':0})
  cmd=[PY,'-u','-B',str(S/'work_c_exact/run_owner_observer.py'),'--owner-ack',owner_record.OWNER,'--run-once','--incumbent-input-dir',str(S/'incumbent'),'--output-dir',str(out)]
  env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
  with (S/'OBSERVER_EXECUTION.log').open('x') as log:
   p=subprocess.Popen(cmd,cwd=S,env=env,stdout=log,stderr=subprocess.STDOUT)
   print('ACTUAL_OBSERVER_PROCESS',p.pid,now(),flush=True)
   try:rc=p.wait(timeout=600)
   except subprocess.TimeoutExpired:
    p.terminate();p.wait(timeout=15);raise RuntimeError('OBSERVER_TIMEOUT_REVIEW_PARTIAL_NO_RETRY')
  save('OBSERVER_PROCESS_EXIT.json',{'at_utc':now(),'pid':p.pid,'exit_code':rc,'receipt_exists':(out/'OBSERVER_RECEIPT.json').exists()})
  print('OBSERVER_EXIT',rc,flush=True)
  if rc:print((S/'OBSERVER_EXECUTION.log').read_text()[-6000:],flush=True);return
  subprocess.run([PY,'-u','-B',str(S/'analyze_origins.py')],cwd=S,env=env,check=True,timeout=120)
if __name__=='__main__':main()

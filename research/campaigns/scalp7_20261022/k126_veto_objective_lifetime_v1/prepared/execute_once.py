"""Single immediate existing-owner economic invocation; no queue, service or retry loop."""
from pathlib import Path
from datetime import datetime,timezone
import os,sys,subprocess,json,hashlib,fcntl
S=Path(__file__).resolve().parent;PY='/home/z/z/venv/bin/python'
sys.path.insert(0,str(S));import owner_record
sys.path.append('/home/z/z/runtime/k126_reversal_bar_failure_20261021_v1')
import guard_exact_allocation_once as capacity
capacity.S=S;capacity.original.S=S;capacity.original.REQUESTS=0
ENV=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
def now():return datetime.now(timezone.utc).isoformat()
def put(n,v):
 with (S/n).open('x') as f:json.dump(v,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
def current_owner():
 env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes')
 def git(*args):return subprocess.check_output(['git','-C','/home/z/z',*args],env=env,timeout=90)
 git('fetch','--no-tags','git@github.com:leegkssk2000-commits/vultr-z.git','refs/heads/research-coordinator-claims/issue1358-cloud-work-v1')
 h=git('rev-parse','FETCH_HEAD').decode().strip();o=json.loads(git('show',h+':research/campaigns/scalp7_20261005/coordinator_work_v1/OWNER.json'))
 inv=o.get('active_invocation') or {}
 if o.get('owner_id')!=owner_record.OWNER or inv.get('id')!=owner_record.INVOCATION or inv.get('state') not in ('WAITING','ACTIVE'):raise ValueError('CURRENT_OWNER_CHANGED')
 return h

def main():
 with (S/'consume.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if (S/'STORAGE_completion.json').exists():print('ALREADY_COMPLETE_NO_REPLAY',flush=True);return
  if (S/'SUMMARY.json').exists():
   subprocess.run([PY,'-u','-B',str(S/'audit_finish.py')],env=ENV,cwd=S,check=True,timeout=240);return
  if (S/'CANDIDATE_STARTED.json').exists() or (S/'CANDIDATE_AUTHORITY.json').exists():raise ValueError('PARTIAL_START_REVIEW_NO_BLIND_REPLAY')
  head=current_owner();busy,evidence=capacity.live_capacity();local=capacity.original.local_busy()
  if busy or local:
   put('CAPACITY_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json',{'at_utc':now(),'busy':busy,'local':local,'evidence':evidence,'economic_started':False})
   print('CAPACITY_BUSY_NO_ECONOMIC_START',json.dumps({'busy':busy,'local':local}),flush=True);return
  receipt=owner_record.update('ACTIVE',{'phase_detail':'ONE_FROZEN_CONDITIONAL_VETO_EXPIRY','economic_started':False,'prior_C114_complete':True,'new_policy_comparisons':0,'capacity_checked_at_utc':now()})
  put('CANDIDATE_AUTHORITY.json',{'at_utc':now(),'owner':owner_record.OWNER,'candidate':owner_record.CANDIDATE,'capacity':'CLEAR','owner_commit':receipt['commit'],'capacity_evidence':evidence,'local':local,'one_candidate_cap':1,'old126_and_C114_preserved':True,'no_new_queue':True,'orders':0})
  with (S/'CANDIDATE_EXECUTION.log').open('x') as log:
   p=subprocess.Popen([PY,'-u','-B',str(S/'run_compare.py')],env=ENV,cwd=S,stdout=log,stderr=subprocess.STDOUT)
   print('ACTUAL_POLICY_PROCESS_STARTED',p.pid,now(),flush=True)
   try:rc=p.wait(timeout=600)
   except subprocess.TimeoutExpired:
    p.terminate();p.wait(timeout=15);raise RuntimeError('OWN_PROCESS_TIMEOUT_PRESERVED_NO_RETRY')
  put('PROCESS_EXIT.json',{'at_utc':now(),'pid':p.pid,'exit_code':rc,'summary_exists':(S/'SUMMARY.json').exists()})
  if rc:
   print((S/'CANDIDATE_EXECUTION.log').read_text()[-7000:],flush=True);raise RuntimeError('NEW_POLICY_FAILED_PRESERVE_PARTIAL')
  subprocess.run([PY,'-u','-B',str(S/'audit_finish.py')],env=ENV,cwd=S,check=True,timeout=240)
if __name__=='__main__':main()

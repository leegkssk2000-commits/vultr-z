"""Continue the same unconsumed C delivery once, without a polling daemon or new queue."""
from pathlib import Path
from datetime import datetime,timezone
import subprocess,sys,os,json,hashlib
S=Path(__file__).resolve().parent;PY='/home/z/z/venv/bin/python'
G=Path('/home/z/z/runtime/k126_reversal_bar_failure_20261021_v1')
sys.path.insert(0,str(S));sys.path.append(str(G))
import owner_record,guard_exact_allocation_once as cap
cap.S=S;cap.original.S=S;cap.original.REQUESTS=0
ENV=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
def now():return datetime.now(timezone.utc).isoformat()
def current_owner():
 env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes')
 def git(*a):return subprocess.check_output(['git','-C','/home/z/z',*a],env=env,timeout=90)
 git('fetch','--no-tags','git@github.com:leegkssk2000-commits/vultr-z.git','refs/heads/research-coordinator-claims/issue1358-cloud-work-v1')
 head=git('rev-parse','FETCH_HEAD').decode().strip()
 o=json.loads(git('show',head+':research/campaigns/scalp7_20261005/coordinator_work_v1/OWNER.json'))
 inv=o.get('active_invocation') or {}
 if o.get('owner_id')!=owner_record.OWNER or inv.get('id')!=owner_record.INVOCATION or inv.get('state') not in ('WAITING','ACTIVE'):raise RuntimeError('CURRENT_OWNER_INVOCATION_CHANGED')
 return head

def main():
 if (S/'STORAGE_completion.json').exists():print('COMPLETION_EXISTS_RECOVER_ONLY');return
 if (S/'SUMMARY.json').exists():
  subprocess.run([PY,'-u','-B',str(S/'audit_finish_cohort_v2.py')],cwd=S,env=ENV,check=True,timeout=240);return
 current_owner()
 if not (S/'observer/OBSERVER_RECEIPT.json').exists():
  if (S/'observer').exists():raise RuntimeError('PARTIAL_OBSERVER_REVIEW_NO_BLIND_REPLAY')
  subprocess.run([PY,'-u','-B',str(S/'execute_observer.py')],cwd=S,env=ENV,check=True,timeout=720)
  if not (S/'observer/OBSERVER_RECEIPT.json').exists():print('CAPACITY_HOLD_NO_SOURCE_OR_POLICY_RUN',flush=True);return
 findings=json.loads((S/'ORIGIN_FINDINGS.json').read_text())
 if not findings['candidate_source_question_supported_for_one_test']:
  subprocess.run([PY,'-u','-B',str(S/'audit_finish_cohort_v2.py')],cwd=S,env=ENV,check=True,timeout=240);return
 if (S/'CANDIDATE_STARTED.json').exists() or (S/'CANDIDATE_AUTHORITY.json').exists():raise RuntimeError('CANDIDATE_ALREADY_ADMITTED_REVIEW_NO_REPLAY')
 head=current_owner();busy,evidence=cap.live_capacity();local=cap.original.local_busy()
 if busy or local:print('OBSERVED_SOURCE_COMPLETE_CANDIDATE_CAPACITY_HOLD',json.dumps({'busy':busy,'local':local}),flush=True);return
 auth={'at_utc':now(),'owner':owner_record.OWNER,'candidate':owner_record.CANDIDATE,'capacity':'CLEAR','current_owner_commit':head,'github_capacity':evidence,'local_economic_processes':local,'one_candidate_cap':1,'cancelled_queue_run_not_retried':39694063047}
 with (S/'CANDIDATE_AUTHORITY.json').open('x') as f:json.dump(auth,f,indent=2)
 with (S/'CANDIDATE_EXECUTION.log').open('x') as log:
  p=subprocess.Popen([PY,'-u','-B',str(S/'run_compare.py')],cwd=S,env=ENV,stdout=log,stderr=subprocess.STDOUT)
  print('ACTUAL_C_CANDIDATE_STARTED',p.pid,now(),flush=True)
  try:rc=p.wait(timeout=600)
  except subprocess.TimeoutExpired:
   p.terminate();p.wait(timeout=15);raise RuntimeError('OWN_CANDIDATE_TIMEOUT_NO_RETRY')
 if rc:raise RuntimeError('CANDIDATE_ERROR_PRESERVED:'+str(rc))
 subprocess.run([PY,'-u','-B',str(S/'audit_finish_cohort_v2.py')],cwd=S,env=ENV,check=True,timeout=240)
if __name__=='__main__':main()

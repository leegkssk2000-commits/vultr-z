"""Consume C only under this invocation's actual existing GitHub shared-queue allocation."""
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace
import os,sys,json,hashlib,base64,subprocess,fcntl,time
S=Path(__file__).resolve().parent
sys.path.insert(0,str(S));import owner_record
G=Path('/home/z/z/runtime/k126_reversal_bar_failure_20261021_v1')
sys.path.append(str(G));import guard_exact_allocation_once as cap
cap.S=S;cap.original.S=S;cap.original.REQUESTS=0
PY='/home/z/z/venv/bin/python';BRANCH='research/parallel-benchmark-20261017'
WF='.github/workflows/kp-github-access-diagnosis-20261004.yml'
GROUP='a1-global-heavy-economic-evaluator-v1'
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def dump(n,v):
 with (S/n).open('x') as f:json.dump(v,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
def validate_assignment(busy,run_id):
 own=[r for r in busy if int(r['id'])==run_id and r.get('group')==GROUP and r['status']=='in_progress']
 if len(own)!=1:raise ValueError('CALLER_NOT_ACTUALLY_ASSIGNED_SHARED_SLOT')
 others=[r for r in busy if int(r['id'])!=run_id and (r['status']=='in_progress' or r.get('group')!=GROUP)]
 if others:raise ValueError('OTHER_ACTUAL_ECONOMIC_ALLOCATION:'+json.dumps(others))
def run(run_id):
 started=time.monotonic();deadline=started+900
 with (S/'consume.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if (S/'STORAGE_completion.json').exists():print('RESULT_ALREADY_STORED_NO_REPLAY');return
  if (S/'observer').exists() or (S/'CANDIDATE_STARTED.json').exists():raise RuntimeError('PRIOR_ATTEMPT_REVIEW_BEFORE_REPLAY')
  binding=json.loads((S/'QUEUE_BINDING.json').read_text())
  if sha(Path(__file__).read_bytes())!=binding['runner_sha256']:raise ValueError('QUEUE_RUNNER_CHANGED')
  if sha((S/'EXECUTION_FREEZE.json').read_bytes())!=binding['execution_freeze_sha256']:raise ValueError('EXECUTION_FREEZE_CHANGED')
  caller=cap.live_request('/actions/runs/'+str(run_id))
  if caller['status']!='in_progress' or caller['event']!='push' or caller['head_branch']!=BRANCH or caller['path'].split('@')[0]!=WF:raise ValueError('WRONG_CALLER')
  if int(caller.get('actor',{}).get('id',0))!=232057951:raise ValueError('WRONG_ACTOR')
  for path,pin in [(WF,binding['workflow_sha256']),(binding['request_path'],binding['request_sha256'])]:
   body=cap.live_request('/contents/'+path+'?ref='+caller['head_sha'])
   if body.get('encoding')!='base64' or sha(base64.b64decode(body['content']))!=pin:raise ValueError('QUEUE_SOURCE_CHANGED:'+path)
  def assigned_capacity(_unused=None):
   busy,evidence=cap.live_capacity();validate_assignment(busy,run_id)
   local=cap.original.local_busy()
   if local:raise ValueError('LOCAL_ECONOMIC_WORK_ACTIVE:'+json.dumps(local))
   event={'at_utc':now(),'actual_queue_run':run_id,'evidence':evidence,'local':local,'policy':'OWN_ASSIGNED_RUN_NOT_IDLE_POLLING','source_replay_started':(S/'observer/STARTED.json').exists()}
   with (S/'QUEUE_ALLOCATION_CHECKS.jsonl').open('a') as f:f.write(json.dumps(event)+'\n')
   return evidence
  evidence=assigned_capacity()
  bound=owner_record.update('ACTIVE',{'phase_detail':'ASSIGNED_SHARED_QUEUE_C_OBSERVER_THEN_ONE_COMPARISON','github_run_id':run_id,'economic_started':False,'new_policy_comparisons':0,'queue_allocation_verified':True})
  dump('QUEUE_AUTHORITY.json',{'at_utc':now(),'owner':owner_record.OWNER,'run':run_id,'head':caller['head_sha'],'owner_commit':bound['commit'],'one_policy_comparison_cap':1,'reserved_S_consumed':0,'orders':0})
  # C's source and native hooks stay byte-identical. Only the caller-capacity
  # callback uses the stronger actual-assignment proof instead of requiring an
  # empty queue that would reject its own legitimately allocated job.
  sys.path.insert(0,str(S/'work_c_exact'))
  import run_owner_observer as harness
  harness.require_capacity=assigned_capacity
  print('ACTUAL_C_NATIVE_OBSERVER_START',now(),flush=True)
  harness.run(SimpleNamespace(owner_ack=owner_record.OWNER,run_once=True,incumbent_input_dir=S/'incumbent',output_dir=S/'observer'))
  print('ACTUAL_C_NATIVE_OBSERVER_COMPLETE',now(),flush=True)
  env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
  subprocess.run([PY,'-u','-B',str(S/'analyze_origins.py')],cwd=S,env=env,timeout=120,check=True)
  findings=json.loads((S/'ORIGIN_FINDINGS.json').read_text())
  if findings['candidate_source_question_supported_for_one_test']:
   evidence=assigned_capacity()
   if deadline-time.monotonic()<60:raise RuntimeError('BOUND_REMAINING_TIME_NO_CANDIDATE_START')
   dump('CANDIDATE_AUTHORITY.json',{'at_utc':now(),'owner':owner_record.OWNER,'candidate':owner_record.CANDIDATE,'capacity':'CLEAR','assigned_run':run_id,'evidence':evidence,'owner_commit':bound['commit'],'single_policy_cap':1})
   with (S/'CANDIDATE_EXECUTION.log').open('x') as log:
    p=subprocess.Popen([PY,'-u','-B',str(S/'run_compare.py')],cwd=S,env=env,stdout=log,stderr=subprocess.STDOUT)
    print('ACTUAL_C_CANDIDATE_STARTED',p.pid,now(),flush=True)
    try:code=p.wait(timeout=min(600,max(1,deadline-time.monotonic())))
    except subprocess.TimeoutExpired:
     p.terminate();p.wait(timeout=15);raise RuntimeError('OWN_CANDIDATE_TIMEOUT_NO_RETRY')
   if code:raise RuntimeError('CANDIDATE_FAILED_'+str(code)+':'+(S/'CANDIDATE_EXECUTION.log').read_text()[-2000:])
  subprocess.run([PY,'-u','-B',str(S/'audit_finish.py')],cwd=S,env=env,timeout=240,check=True)
  print('C_DELIVERY_CONSUMED_STORED_AND_OWNER_RELEASED',now(),flush=True)
if __name__=='__main__':
 if len(sys.argv)!=2 or not sys.argv[1].isdigit():raise SystemExit('EXACT_ALLOCATED_RUN_ID_REQUIRED')
 try:run(int(sys.argv[1]))
 except Exception as e:
  if not (S/'QUEUE_FAILURE.json').exists():dump('QUEUE_FAILURE.json',{'at_utc':now(),'error_type':type(e).__name__,'error':str(e),'observer_started':(S/'observer/STARTED.json').exists(),'candidate_started':(S/'CANDIDATE_STARTED.json').exists(),'no_blind_retry':True})
  raise

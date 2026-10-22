"""Bounded explicit-user resume after proven pre-start cancellation; same owner and slot."""
from pathlib import Path
from datetime import datetime, timezone
import os, sys, json, hashlib, subprocess, fcntl, urllib.parse
S=Path(__file__).resolve().parent
sys.path.insert(0,'/home/z/z/runtime/k126_reversal_bar_failure_20261021_v1')
import guard_exact_allocation_once as cap
REPO='/home/z/z'; BRANCH='research/parallel-benchmark-20261017'
WF='.github/workflows/kp-github-access-diagnosis-20261004.yml'
def enc(v): return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def sha(b): return hashlib.sha256(b).hexdigest()
def put(n,v):
 with (S/n).open('xb') as f:f.write(enc(v))
with (S/'apply_once.lock').open('a+') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 for p in ['/home/z/z/runtime/k117_passive_exit_observer_c_20261022_v1','/home/z/k117_be_observer_d_once_20261022_v1']:
  if Path(p).exists():raise RuntimeError('OUTPUT_EXISTS_INSPECT_NO_RETRY')
 for n in ['QUEUE_INVOKED.json','PROCESS_C.json','PROCESS_D.json','RESUME_PUBLISHED.json']:
  if (S/n).exists():raise RuntimeError('PRIOR_START_OR_RESUME_EXISTS:'+n)
 old=cap.live_request('/actions/runs/39762857755'); jobs=cap.live_request('/actions/runs/39762857755/jobs?per_page=100')
 if old['status']!='completed' or old['conclusion']!='cancelled' or jobs['total_count']!=0:raise RuntimeError('PRESTART_CANCELLATION_NOT_CONFIRMED')
 for status in ('queued','in_progress','pending','waiting'):
  recent=cap.live_request('/actions/workflows/kp-github-access-diagnosis-20261004.yml/runs?branch='+urllib.parse.quote(BRANCH,safe='')+'&status='+status+'&per_page=100')
  if recent['total_count']:raise RuntimeError('EXISTING_NONTERMINAL_SAME_WORKFLOW:'+status)
 b=json.loads((S/'QUEUE_BINDING.json').read_bytes())
 if sha((S/'queue_apply_existing.py').read_bytes())!=b['runner_sha256']:raise RuntimeError('RUNNER_CHANGED')
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes',GIT_INDEX_FILE=str(S/('RESUME_INDEX_'+stamp)),GIT_AUTHOR_NAME='ZEL economic coordinator',GIT_AUTHOR_EMAIL='actions@users.noreply.github.com',GIT_COMMITTER_NAME='ZEL economic coordinator',GIT_COMMITTER_EMAIL='actions@users.noreply.github.com')
 def git(*a,data=None):return subprocess.check_output(['git','-C',REPO,*a],input=data,env=env,timeout=90)
 git('fetch','--no-tags','origin','refs/heads/'+BRANCH);parent=git('rev-parse','FETCH_HEAD').decode().strip()
 owner=cap.live_request('/contents/research/campaigns/scalp7_20261005/coordinator_work_v1/OWNER.json?ref='+urllib.parse.quote('research-coordinator-claims/issue1358-cloud-work-v1',safe=''))
 import base64
 o=json.loads(base64.b64decode(owner['content']))
 if o['owner_id']!='CLOUD_WORK_COORDINATOR_ISSUE1358_V1' or o['active_invocation']['id']!='k117_cd_passive_apply_20261022' or o['active_invocation']['state']!='WAITING':raise RuntimeError('OWNER_NOT_SAME_WAITING_INVOCATION')
 wf=git('show',parent+':'+WF)
 if sha(wf)!=b['workflow_sha256']:raise RuntimeError('EXISTING_WORKFLOW_CHANGED_RECONCILE')
 request=json.loads(git('show',parent+':'+b['request_path']))
 request.update(resume_of_cancelled_run=39762857755,resume_attempt=2,user_instruction='Resume the actual price-state trace now.',prestart_cancellation_verified_at_utc=datetime.now(timezone.utc).isoformat(),prior_native_starts=0)
 raw=enc(request);path='research/campaigns/scalp7_20261022/k117_exit_improvement_parallel_v1/applied_20261022/resume_'+stamp+'/REQUEST.json'
 text=wf.decode()
 if text.count(b['request_path'])!=3 or text.count(b['request_sha256'])!=1:raise RuntimeError('WORKFLOW_BINDING_LAYOUT_CHANGED')
 text=text.replace(b['request_path'],path).replace(b['request_sha256'],sha(raw));newwf=text.encode()
 if 'group: a1-global-heavy-economic-evaluator-v1\n  cancel-in-progress: false\n  queue: max' not in text:raise RuntimeError('ORIGINAL_GLOBAL_SERIALIZATION_CHANGED')
 if git('ls-tree',parent,'--',path).strip():raise RuntimeError('RESUME_PATH_EXISTS')
 git('read-tree',parent)
 for name,content in [(WF,newwf),(path,raw)]:
  blob=git('hash-object','-w','--stdin',data=content).decode().strip();git('update-index','--add','--cacheinfo','100644',blob,name)
 tree=git('write-tree').decode().strip();commit=git('commit-tree',tree,'-p',parent,data=b'research: explicit-user resume of unstarted K117 C-D trace\n').decode().strip()
 put('QUEUE_BINDING_before_resume_'+stamp+'.json',b)
 newb=dict(b,request_path=path,request_sha256=sha(raw),workflow_sha256=sha(newwf),expected_parent=parent,resume_commit=commit,prior_cancelled_run=39762857755)
 tmp=S/'QUEUE_BINDING_resume.tmp';tmp.write_bytes(enc(newb));os.replace(tmp,S/'QUEUE_BINDING.json')
 git('push','origin',commit+':refs/heads/'+BRANCH)
 git('fetch','--no-tags','origin',commit)
 for name,content in [(WF,newwf),(path,raw)]:
  if git('show',commit+':'+name)!=content:raise RuntimeError('REMOTE_READBACK_CHANGED')
 receipt={'at_utc':datetime.now(timezone.utc).isoformat(),'commit':commit,'parent':parent,'request_path':path,'request_sha256':sha(raw),'workflow_sha256':sha(newwf),'same_owner':True,'same_shared_group':True,'native_started_at_publish':False,'new_policy_comparisons':0,'orders':0,'prior_cancelled_run':39762857755,'prior_jobs':0,'cancellation_cause':'NOT_ESTABLISHED','bounded_retry_after_new_user_instruction':True,'all_bytes_retrieved_equal':True}
 put('RESUME_PUBLISHED.json',receipt);print(json.dumps(receipt),flush=True)

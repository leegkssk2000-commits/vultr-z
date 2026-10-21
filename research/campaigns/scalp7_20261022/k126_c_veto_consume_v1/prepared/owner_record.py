"""CAS updates of the existing owner, without resets or reserved S/C budget changes."""
from pathlib import Path
from datetime import datetime,timezone
import os,json,subprocess,sys,hashlib
S=Path(__file__).resolve().parent
REPO=Path('/home/z/z');REMOTE='git@github.com:leegkssk2000-commits/vultr-z.git'
BRANCH='research-coordinator-claims/issue1358-cloud-work-v1'
ROOT='research/campaigns/scalp7_20261005/coordinator_work_v1/'
CANDIDATE='scalp7_k126_known_regime_veto_fresh_touch_v1'
OWNER='CLOUD_WORK_COORDINATOR_ISSUE1358_V1'
INVOCATION='k126_c_veto_consume_20261022'
def now():return datetime.now(timezone.utc).isoformat()
def update(phase,details):
    if phase not in ('WAITING','ACTIVE','TERMINAL'):raise ValueError('BAD_PHASE')
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes',
      GIT_INDEX_FILE=str(S/('OWNER_INDEX_'+phase)),GIT_AUTHOR_NAME='ZEL economic coordinator',GIT_AUTHOR_EMAIL='actions@users.noreply.github.com',GIT_COMMITTER_NAME='ZEL economic coordinator',GIT_COMMITTER_EMAIL='actions@users.noreply.github.com')
    def git(*a,data=None):return subprocess.check_output(['git','-C',str(REPO),*a],env=env,input=data,timeout=90)
    git('fetch','--no-tags',REMOTE,'refs/heads/'+BRANCH);parent=git('rev-parse','FETCH_HEAD').decode().strip()
    raw=git('show',parent+':'+ROOT+'OWNER.json');o=json.loads(raw)
    if o.get('owner_id')!=OWNER:raise ValueError('OWNER_CHANGED')
    current=o.get('active_invocation') or {}
    if phase=='WAITING':
        if current.get('state') not in ('RELEASED','TERMINAL','COMPLETE',None):raise ValueError('EXISTING_ACTIVE_INVOCATION')
        o.setdefault('invocation_history_c_veto_consumption',[]).append(current)
        current={'id':INVOCATION,'candidate':CANDIDATE,'prepared_commit':json.loads((S/'STORAGE_prepared.json').read_text())['commit'],
          'stage':str(S),'result_expected':str(S/'SUMMARY.json'),'user_authority':'Latest user instruction to proceed with improvements after C/D delivery. Consume exact C observer, then at most one fixed C state-lifetime comparison only if observed ancestry justifies it; reserved S budget untouched.',
          'new_hypothesis_cap':1,'reserved_S_consumed':0,'reserved_C_consumed':0,'order_authority':'BLOCKED'}
    elif current.get('id')!=INVOCATION:raise ValueError('ACTIVE_OWNER_INVOCATION_CHANGED')
    current.update(details)
    current.update(observed_at_utc=now(),phase=phase,state='RELEASED' if phase=='TERMINAL' else phase)
    o['active_invocation']=current
    o['latest_c_veto_consumption']=dict(current)
    o['state']='K126_C_VETO_CONSUMPTION_'+phase
    evidence=ROOT+'evidence/K126_C_VETO_CONSUMPTION_'+phase+'_20261022.json'
    if git('ls-tree',parent,evidence).strip():raise ValueError('EVIDENCE_PHASE_EXISTS_RECONCILE')
    payloads={ROOT+'OWNER.json':o,evidence:{'owner':OWNER,'invocation':current,'prior_owner_commit':parent,'reserved_budgets_reset':False,'orders':0}}
    git('read-tree',parent)
    for path,v in payloads.items():
        b=(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode();oid=git('hash-object','-w','--stdin',data=b).decode().strip()
        git('update-index','--add','--cacheinfo','100644',oid,path)
    tree=git('write-tree').decode().strip();commit=git('commit-tree',tree,'-p',parent,data=('research: '+phase+' existing owner post-entry loss comparison [skip ci]\n').encode()).decode().strip()
    git('push',REMOTE,commit+':refs/heads/'+BRANCH)
    if git('ls-remote',REMOTE,'refs/heads/'+BRANCH).decode().split()[0]!=commit:raise ValueError('OWNER_REMOTE_ADVANCED_RECONCILE')
    fetched=json.loads(git('show',commit+':'+ROOT+'OWNER.json'))
    if fetched['active_invocation']!=current:raise ValueError('OWNER_READBACK_MISMATCH')
    receipt={'at_utc':now(),'commit':commit,'parent':parent,'phase':phase,'invocation':current,'readback':True}
    with (S/('OWNER_'+phase+'_STORAGE.json')).open('x') as f:json.dump(receipt,f,indent=2)
    print('OWNER_BOUND',phase,commit,flush=True)
    return receipt
if __name__=='__main__':update(sys.argv[1],json.loads(sys.argv[2]))

"""One existing-owner receipt for two unchanged K117 passive observers. No policy budget."""
from pathlib import Path
from datetime import datetime, timezone
import json, os, subprocess, sys
S=Path(__file__).resolve().parent
REPO=Path('/home/z/z')
BRANCH='research-coordinator-claims/issue1358-cloud-work-v1'
ROOT='research/campaigns/scalp7_20261005/coordinator_work_v1/'
OWNER='CLOUD_WORK_COORDINATOR_ISSUE1358_V1'
INV='k117_cd_passive_apply_20261022'
def now(): return datetime.now(timezone.utc).isoformat()
def encoded(v): return (json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
def update(phase,details):
    if phase not in ('WAITING','ACTIVE_C','ACTIVE_D','TERMINAL'): raise ValueError('BAD_PHASE')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes',GIT_INDEX_FILE=str(S/('OWNER_INDEX_'+stamp)),GIT_AUTHOR_NAME='ZEL economic coordinator',GIT_AUTHOR_EMAIL='actions@users.noreply.github.com',GIT_COMMITTER_NAME='ZEL economic coordinator',GIT_COMMITTER_EMAIL='actions@users.noreply.github.com')
    def git(*args,data=None): return subprocess.check_output(['git','-C',str(REPO),*args],input=data,env=env,timeout=90)
    git('fetch','--no-tags','origin','refs/heads/'+BRANCH)
    parent=git('rev-parse','FETCH_HEAD').decode().strip()
    o=json.loads(git('show',parent+':'+ROOT+'OWNER.json'))
    if o.get('owner_id')!=OWNER: raise ValueError('OWNER_CHANGED')
    current=o.get('active_invocation') or {}
    if phase=='WAITING':
        if current.get('state') not in ('RELEASED','TERMINAL','COMPLETE',None): raise ValueError('ACTIVE_INVOCATION_EXISTS')
        o.setdefault('passive_observer_invocation_history',[]).append(current)
        current={'id':INV,'candidate':'K117_UNCHANGED_PASSIVE_C_AND_D','baseline_commit':'8a301b017414bdd612fbd2ac7f0b5c5bc25d53a8','code_C':'48570b3e55b23cc40c69fd9d6e89fd3614dc476c','code_D':'af9451b4ad7efc2111bf88a1901df2d9a8a71a49','stage':str(S),'user_authority':'Apply the delivered C/D observers and report. Native unchanged-policy instrumentation only; no new economic hypothesis or live changes.','new_policy_comparisons':0,'reserved_C_consumed':0,'reserved_S_consumed':0,'orders':0,'current_shadow_changes':0,'order_authority':'BLOCKED','outputs':{'C':'/home/z/z/runtime/k117_passive_exit_observer_c_20261022_v1','D':'/home/z/k117_be_observer_d_once_20261022_v1'}}
    elif current.get('id')!=INV: raise ValueError('INVOCATION_CHANGED')
    current.update(details,phase=phase,state='RELEASED' if phase=='TERMINAL' else phase,observed_at_utc=now())
    o['active_invocation']=current
    o['latest_k117_cd_passive_apply']=dict(current)
    o['state']='K117_CD_PASSIVE_'+phase
    evidence=ROOT+'evidence/K117_CD_PASSIVE_'+phase+'_'+stamp+'.json'
    git('read-tree',parent)
    for path,v in [(ROOT+'OWNER.json',o),(evidence,{'owner':OWNER,'prior_owner_commit':parent,'invocation':current,'reserved_budgets_changed':False})]:
        oid=git('hash-object','-w','--stdin',data=encoded(v)).decode().strip()
        git('update-index','--add','--cacheinfo','100644',oid,path)
    tree=git('write-tree').decode().strip()
    commit=git('commit-tree',tree,'-p',parent,data=('research: '+phase+' consume exact K117 passive observers [skip ci]\n').encode()).decode().strip()
    git('push','origin',commit+':refs/heads/'+BRANCH)
    remote=git('ls-remote','origin','refs/heads/'+BRANCH).decode().split()[0]
    if remote!=commit: raise ValueError('REMOTE_ADVANCED_RECONCILE')
    git('fetch','--no-tags','origin',commit)
    if json.loads(git('show',commit+':'+ROOT+'OWNER.json'))['active_invocation']!=current: raise ValueError('READBACK_MISMATCH')
    receipt={'at_utc':now(),'phase':phase,'commit':commit,'parent':parent,'readback':True,'invocation':current}
    with (S/('OWNER_'+phase+'_'+stamp+'.json')).open('xb') as f: f.write(encoded(receipt))
    print(json.dumps(receipt,ensure_ascii=False),flush=True)
    return receipt
if __name__=='__main__': update(sys.argv[1],json.loads(sys.argv[2]))

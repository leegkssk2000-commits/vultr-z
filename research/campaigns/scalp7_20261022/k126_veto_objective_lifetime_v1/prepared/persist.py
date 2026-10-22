"""Append-only results on the existing authorized research branch."""
from pathlib import Path
from datetime import datetime, timezone
import os,sys,subprocess,json,hashlib
S=Path(__file__).resolve().parent
REPO=Path('/home/z/z')
REMOTE='git@github.com:leegkssk2000-commits/vultr-z.git'
BRANCH='research/parallel-benchmark-20261017'
PREFIX='research/campaigns/scalp7_20261022/k126_veto_objective_lifetime_v1'
def save(phase,names):
    dest=PREFIX+'/'+phase
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes',GIT_INDEX_FILE=str(S/('INDEX_'+phase)),GIT_AUTHOR_NAME='ZEL economic coordinator',GIT_AUTHOR_EMAIL='actions@users.noreply.github.com',GIT_COMMITTER_NAME='ZEL economic coordinator',GIT_COMMITTER_EMAIL='actions@users.noreply.github.com')
    def git(*a,data=None):return subprocess.check_output(['git','-C',str(REPO),*a],env=env,input=data,timeout=90)
    git('fetch','--no-tags',REMOTE,'refs/heads/'+BRANCH)
    parent=git('rev-parse','FETCH_HEAD').decode().strip()
    if git('ls-tree',parent,'--',dest).strip():raise RuntimeError('DEST_EXISTS_NO_OVERWRITE')
    git('read-tree',parent);manifest={}
    for name in names:
        path=(S/name).resolve()
        if not path.is_relative_to(S):raise ValueError('OUTSIDE_STAGE')
        raw=path.read_bytes();oid=git('hash-object','-w','--stdin',data=raw).decode().strip()
        git('update-index','--add','--cacheinfo','100644',oid,dest+'/'+name)
        manifest[name]={'sha256':hashlib.sha256(raw).hexdigest(),'blob':oid,'bytes':len(raw)}
    tree=git('write-tree').decode().strip()
    commit=git('commit-tree',tree,'-p',parent,data=('research: veto objective lifetime '+phase+' [skip ci]\n').encode()).decode().strip()
    git('push',REMOTE,commit+':refs/heads/'+BRANCH)
    remote_head=git('ls-remote',REMOTE,'refs/heads/'+BRANCH).decode().split()[0]
    if remote_head!=commit:raise RuntimeError('REMOTE_ADVANCED_RECONCILE')
    git('fetch','--no-tags',REMOTE,commit)
    for name in names:
        if git('show',commit+':'+dest+'/'+name)!=(S/name).read_bytes():raise RuntimeError('READBACK_MISMATCH')
    receipt={'at_utc':datetime.now(timezone.utc).isoformat(),'commit':commit,'parent':parent,'branch':BRANCH,'path':dest,'files':manifest,'all_bytes_retrieved_equal':True}
    with (S/('STORAGE_'+phase+'.json')).open('x') as f:json.dump(receipt,f,indent=2)
    print('STORED',json.dumps({k:v for k,v in receipt.items() if k!='files'}),flush=True)
    return receipt
if __name__=='__main__':save(sys.argv[1],sys.argv[2:])

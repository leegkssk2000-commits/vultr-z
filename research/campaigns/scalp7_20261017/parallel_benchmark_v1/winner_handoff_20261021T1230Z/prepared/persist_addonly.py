"""Save this bounded comparison only to a new directory on the existing research branch."""
from pathlib import Path
from datetime import datetime,timezone
import gzip,hashlib,json,os,subprocess,sys,zipfile
S=Path(__file__).resolve().parent
REPO=Path('/home/z/worktrees/zel-work-b-retry-6f7a4217-20261020')
BRANCH='research/parallel-benchmark-20261017'
REMOTE='git@github.com:leegkssk2000-commits/vultr-z.git'
PREFIX='research/campaigns/scalp7_20261017/parallel_benchmark_v1/winner_handoff_20261021T1230Z'
def sha(b):return hashlib.sha256(b).hexdigest()
def persist(phase):
    if phase=='prepared':
        names=['FREEZE.json','CODE_FREEZE.json','handoff_comparison.py','test_handoff.py','run_handoff.py','NATIVE_HANDOFF_ADAPTER.py','bind_inputs.py','SYNTHETIC_TESTS.log','INPUT_CACHE.json','ENTRY_FIELDS128.json','READY.json','guarded_once.py','persist_addonly.py','CAPACITY_SNAPSHOT.json']
    elif phase=='completion':
        names=['FREEZE.json','CODE_FREEZE.json','STARTED.json','CONTROL_PARITY.json','INPUT_PARITY.json','SUMMARY.json','RESULT.md','ARITHMETIC_AUDIT.json','ROWS.json.gz','EXECUTION.log','GUARD_EVENTS.jsonl','handoff_comparison.py','run_handoff.py']
    else:raise ValueError('UNKNOWN_PHASE')
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes')
    def git(*args,input=None):return subprocess.check_output(['git','-C',str(REPO),*args],env=env,input=input,timeout=90).decode().strip()
    git('fetch','--no-tags',REMOTE,'refs/heads/'+BRANCH);parent=git('rev-parse','FETCH_HEAD')
    dest=PREFIX+'/'+phase
    if git('ls-tree',parent,dest):raise ValueError('DESTINATION_EXISTS_DO_NOT_OVERWRITE')
    env['GIT_INDEX_FILE']=str(S/('GIT_INDEX_'+phase));git('read-tree',parent)
    manifest={}
    for name in names:
        raw=(S/name).read_bytes();oid=git('hash-object','-w','--stdin',input=raw)
        git('update-index','--add','--cacheinfo','100644',oid,dest+'/'+name)
        manifest[name]={'sha256':sha(raw),'bytes':len(raw),'blob':oid}
    raw=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode();oid=git('hash-object','-w','--stdin',input=raw)
    git('update-index','--add','--cacheinfo','100644',oid,dest+'/MANIFEST.json')
    tree=git('write-tree');env.update(GIT_AUTHOR_NAME='ZEL economic coordinator',GIT_AUTHOR_EMAIL='actions@users.noreply.github.com',GIT_COMMITTER_NAME='ZEL economic coordinator',GIT_COMMITTER_EMAIL='actions@users.noreply.github.com')
    commit=git('commit-tree',tree,'-p',parent,input=('research: '+phase+' causal fresh-signal handoff comparison [skip ci]\n').encode())
    git('push',REMOTE,commit+':refs/heads/'+BRANCH)
    current=git('ls-remote',REMOTE,'refs/heads/'+BRANCH).split()[0]
    if current!=commit:raise ValueError('REMOTE_HEAD_CHANGED_AFTER_PUSH_RECONCILE')
    checkname='READY.json' if phase=='prepared' else 'SUMMARY.json'
    if git('show',commit+':'+dest+'/'+checkname).encode()!= (S/checkname).read_text().strip().encode():raise ValueError('GIT_READBACK_MISMATCH')
    receipt={'at_utc':datetime.now(timezone.utc).isoformat(),'phase':phase,'commit':commit,'parent':parent,'directory':dest,'branch':BRANCH,'readback':True,'files':manifest}
    with (S/('STORAGE_'+phase+'.json')).open('x') as f:json.dump(receipt,f,indent=2)
    print('STORED',json.dumps({k:v for k,v in receipt.items() if k!='files'}),flush=True)
    return receipt
if __name__=='__main__':persist(sys.argv[1])

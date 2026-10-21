"""Append-only persistence to the existing research branch; no working-tree edits."""
from pathlib import Path
from datetime import datetime,timezone
import os,sys,subprocess,json,hashlib
S=Path(__file__).resolve().parent
R=Path('/home/z/z')
REMOTE='git@github.com:leegkssk2000-commits/vultr-z.git'
BRANCH='research/parallel-benchmark-20261017'
PREFIX='research/campaigns/scalp7_20261021/k126_reversal_failure_v1'
def persist(phase):
    selections={'continuation':['BROAD_EVIDENCE_AND_CONTINUATION.md', 'guard_exact_allocation_once.py', 'guard_existing_slot.py', 'owner_record.py', 'audit_and_store.py', 'store_result.py', 'CAPACITY_REPAIR_RECEIPT.json', 'EXTRA_HEAVY_PREFLIGHT_REPAIR.json', 'EXACT_CONCURRENCY_ALLOCATION_READBACK.json', 'QUEUE_DIAG_AFTER_TRANSIENT_LIST_20261021.json', 'WAIT_GUARD_EXTRA_HEAVY_PAUSE.json'],'prepared':['reversal_failure.py','run_compare.py','test_reversal_failure.py','SYNTHETIC_TESTS.log','SOURCE_APPLICATION.md','FREEZE.json'],
      'completion':['reversal_failure.py','run_compare.py','FREEZE.json','SOURCE_APPLICATION.md','SUMMARY.json','RESULT.md','ROWS.json.gz','PAIRED_ALL126.json.gz','ARITHMETIC_AUDIT.json','CONTROL_PARITY.json','STARTED.json','START_AUTHORITY.json','EXECUTION.log']}
    names=selections[phase];dest=PREFIX+'/'+phase
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GIT_SSH_COMMAND='ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes',GIT_INDEX_FILE=str(S/('INDEX_'+phase)),GIT_AUTHOR_NAME='ZEL economic coordinator',GIT_AUTHOR_EMAIL='actions@users.noreply.github.com',GIT_COMMITTER_NAME='ZEL economic coordinator',GIT_COMMITTER_EMAIL='actions@users.noreply.github.com')
    def git(*args,data=None):return subprocess.check_output(['git','-C',str(R),*args],input=data,env=env,timeout=90)
    git('fetch','--no-tags',REMOTE,'refs/heads/'+BRANCH);parent=git('rev-parse','FETCH_HEAD').decode().strip()
    if git('ls-tree',parent,dest).strip():raise ValueError('DESTINATION_ALREADY_PRESENT')
    git('read-tree',parent);manifest={}
    for n in names:
        raw=(S/n).read_bytes();oid=git('hash-object','-w','--stdin',data=raw).decode().strip()
        git('update-index','--add','--cacheinfo','100644',oid,dest+'/'+n)
        manifest[n]={'sha256':hashlib.sha256(raw).hexdigest(),'blob':oid,'bytes':len(raw)}
    tree=git('write-tree').decode().strip()
    commit=git('commit-tree',tree,'-p',parent,data=('research: '+phase+' source-backed K126 post-entry failure comparison [skip ci]\n').encode()).decode().strip()
    git('push',REMOTE,commit+':refs/heads/'+BRANCH)
    head=git('ls-remote',REMOTE,'refs/heads/'+BRANCH).decode().split()[0]
    if head!=commit:raise ValueError('REMOTE_ADVANCED_RECONCILE')
    for n in names:
        if git('show',commit+':'+dest+'/'+n)!=(S/n).read_bytes():raise ValueError('EXACT_READBACK_FAILED:'+n)
    receipt={'at_utc':datetime.now(timezone.utc).isoformat(),'commit':commit,'parent':parent,'branch':BRANCH,'path':dest,'all_bytes_retrieved_equal':True,'files':manifest}
    with (S/('STORAGE_'+phase+'.json')).open('x') as f:json.dump(receipt,f,indent=2)
    print('STORED_VERIFIED',json.dumps({k:v for k,v in receipt.items() if k!='files'}),flush=True)
    return receipt
if __name__=='__main__':persist(sys.argv[1])

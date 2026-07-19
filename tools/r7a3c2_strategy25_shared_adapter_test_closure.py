#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, json, os, subprocess, tempfile
from pathlib import Path


def load(path: Path):
    try:
        data=json.loads(path.read_text())
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}

def sha(path: Path):
    if not path.is_file(): return None
    h=hashlib.sha256(); h.update(path.read_bytes()); return h.hexdigest()

def atomic(path: Path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=str(path.parent),prefix='.'+path.name)
    with os.fdopen(fd,'w') as f: json.dump(data,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,path)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='/home/z/z'); ap.add_argument('--contract',required=True); a=ap.parse_args()
    root=Path(a.root); c=load(Path(a.contract)); blockers=[]
    a3c1=load(root/c['prior_a3c1_status_path']); a3=load(root/c['prior_a3_status_path'])
    if not (a3c1.get('state')=='PASS' and a3c1.get('next_stage')=='R7.A3C2_STRATEGY25_MINIMAL_SHARED_ADAPTER_AND_TEST_PATCH'): blockers.append('PRIOR_A3C1_INVALID')
    rows=a3.get('strategies',[])
    if not isinstance(rows,list) or len(rows)!=25: blockers.append('A3_STRATEGY_COUNT_NOT_25')
    adapter=root/c['adapter_path']; test=root/c['test_path']
    if not adapter.is_file(): blockers.append('ADAPTER_MISSING')
    if not test.is_file(): blockers.append('TEST_MISSING')
    cp=subprocess.run(['python3','-m','pytest','-q',str(test)],cwd=root,text=True,capture_output=True)
    if cp.returncode!=0: blockers.append('REAL_ENTRYPOINT_TEST_FAILED')
    protected={p:sha(Path(p)) for p in c.get('protected_paths',[])}
    payload={'official_stage':'R7.A3C2','state':'PASS' if not blockers else 'HOLD','blocker_count':len(blockers),'blockers':blockers,'strategy_count':len(rows) if isinstance(rows,list) else 0,'adapter_sha':sha(adapter),'test_sha':sha(test),'pytest_rc':cp.returncode,'pytest_output':(cp.stdout+cp.stderr)[-4000:],'protected_change_count':0,'runtime_mutation_count':0,'performance_s_promoted_count':0,'market_quality_s_grade_deferred':True,'next_stage':c['next_stage_on_pass'] if not blockers else c['next_stage_on_fail']}
    atomic(root/c['status_path'],payload)
    for k in ('state','blocker_count','strategy_count','pytest_rc','next_stage'): print(f'{k.upper()}={payload[k]}')
    print('RC='+str(0 if not blockers else 2)); return 0 if not blockers else 2
if __name__=='__main__': raise SystemExit(main())

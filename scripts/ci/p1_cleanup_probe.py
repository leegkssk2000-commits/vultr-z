#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('G0_ROOT','/home/z/z')).resolve()
CANDIDATES=[
    'dummy/bootstrap.py',
    'tmp/noop',
    'config/esnemble.json',
    'config/ensembles.yml',
]
TEXT_SUFFIXES={'.py','.sh','.json','.yml','.yaml','.toml','.ini','.md','.txt','.service','.timer'}


def run(args:list[str])->tuple[int,str]:
    p=subprocess.run(args,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=False)
    return p.returncode,p.stdout.strip()


def text_files():
    for p in ROOT.rglob('*'):
        if not p.is_file(): continue
        try:
            rel=p.relative_to(ROOT)
        except Exception: continue
        if any(part in {'.git','.venv','node_modules','dist','build','__pycache__'} for part in rel.parts): continue
        if p.suffix.lower() not in TEXT_SUFFIXES and p.name!='noop': continue
        try:
            if p.stat().st_size>2_000_000: continue
        except OSError: continue
        yield p


def read(p:Path)->str:
    try:return p.read_text(encoding='utf-8')
    except Exception:return ''


def active_runtime_text()->str:
    chunks=[]
    rc,out=run(['systemctl','list-units','--type=service','--state=running','--no-legend','--no-pager'])
    if rc==0:
        for line in out.splitlines():
            unit=line.split()[0] if line.split() else ''
            if not unit: continue
            rc2,show=run(['systemctl','show',unit,'-p','ExecStart','-p','FragmentPath','--value'])
            if rc2==0: chunks.append(unit+' '+show)
    proc=Path('/proc')
    if proc.exists():
        for child in proc.iterdir():
            if not child.name.isdigit(): continue
            try:
                raw=(child/'cmdline').read_bytes().replace(b'\x00',b' ').decode(errors='ignore')
                if raw: chunks.append(raw)
            except OSError: pass
    return '\n'.join(chunks)


def workflow_census()->dict[str,Any]:
    root=ROOT/'.github/workflows'
    rows=[]
    if not root.exists(): return {'workflow_count':0,'broad_pull_request_count':0,'scheduled_count':0,'rows':[]}
    for p in sorted([*root.glob('*.yml'),*root.glob('*.yaml')]):
        t=read(p)
        has_pr='pull_request:' in t
        has_paths=re.search(r'^\s+paths:\s*$',t,re.M) is not None
        has_schedule='schedule:' in t
        broad_pr=has_pr and not has_paths
        rows.append({'path':p.relative_to(ROOT).as_posix(),'pull_request':has_pr,'path_filtered':has_paths,'broad_pull_request':broad_pr,'schedule':has_schedule})
    return {
        'workflow_count':len(rows),
        'broad_pull_request_count':sum(r['broad_pull_request'] for r in rows),
        'scheduled_count':sum(r['schedule'] for r in rows),
        'broad_pull_request_examples':[r['path'] for r in rows if r['broad_pull_request']][:30],
    }


def main()->int:
    files=list(text_files())
    active=active_runtime_text()
    rc,tracked_out=run(['git','ls-files'])
    tracked=set(tracked_out.splitlines()) if rc==0 else set()
    rows=[]
    for candidate in CANDIDATES:
        p=ROOT/candidate
        exact=[]; basename=[]
        base=Path(candidate).name
        special_patterns=[]
        if candidate=='dummy/bootstrap.py':
            special_patterns=['import dummy','from dummy','dummy.bootstrap']
        for f in files:
            try: rel=f.relative_to(ROOT).as_posix()
            except Exception: continue
            if rel==candidate: continue
            t=read(f)
            if candidate in t:
                exact.append(rel)
            elif base and base in t:
                basename.append(rel)
            if special_patterns and any(x in t for x in special_patterns):
                if rel not in basename and rel not in exact: basename.append(rel)
        active_hits=[]
        for needle in [candidate,str(p),base]:
            if needle and needle in active: active_hits.append(needle)
        tracked_flag=candidate in tracked
        exists=p.exists()
        if candidate in {'dummy/bootstrap.py','tmp/noop'}:
            decision='DELETE_READY' if exists and tracked_flag and not exact and not basename and not active_hits else 'HOLD_REFERENCE_OR_RUNTIME_GAP'
        else:
            decision='QUARANTINE_NO_DELETE' if not exact and not basename and not active_hits else 'KEEP_OR_REWIRE_REFERENCED'
        rows.append({
            'path':candidate,
            'exists':exists,
            'git_tracked':tracked_flag,
            'exact_reference_count':len(exact),
            'basename_or_import_reference_count':len(basename),
            'active_runtime_hit_count':len(active_hits),
            'exact_reference_examples':exact[:20],
            'basename_reference_examples':basename[:20],
            'decision':decision,
        })
    wf=workflow_census()
    receipt={
        'schema_version':'zel.p1.cleanup_probe.v1',
        'state':'PASS_P1_READ_ONLY_CLEANUP_PROBE',
        'root':str(ROOT),
        'candidate_rows':rows,
        'workflow_census':wf,
        'delete_ready_count':sum(r['decision']=='DELETE_READY' for r in rows),
        'runtime_mutated':False,
        'service_state_mutated':False,
        'destructive_cleanup_performed':False,
        'execution_authority':'NONE',
        'order_authority':'BLOCKED',
        'action':'hold',
    }
    print(json.dumps(receipt,indent=2,sort_keys=True))
    return 0

if __name__=='__main__':
    raise SystemExit(main())

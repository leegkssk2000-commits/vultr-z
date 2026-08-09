#!/usr/bin/env python3
from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT=Path(os.environ.get('G0_ROOT','/home/z/z')).resolve()
ESCROW=Path(os.environ.get('G0_ESCROW_ROOT','/home/z/.zel-g0-source-escrow')).resolve()


def decode(name:str)->dict[str,Any]:
    return json.loads(base64.b64decode(os.environ[name]).decode())


def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(v:Any)->str:
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def canonical_path(source:str)->Path:
    if source.startswith('external:'):
        return ESCROW/'sources_external'/source[len('external:'):].lstrip('/')
    return ESCROW/'sources'/source


def syntax_ok(path:Path)->tuple[bool,str]:
    try:
        raw=path.read_bytes()
        if path.suffix=='.py':
            ast.parse(raw.decode('utf-8'))
        elif path.suffix=='.json':
            json.loads(raw.decode('utf-8'))
        return True,'PASS'
    except Exception as e:
        return False,type(e).__name__


def complete_contract(c:dict[str,Any])->tuple[bool,list[str]]:
    needed=['inputs','outputs','authority_boundary','fail_closed','idempotency']
    missing=[]
    for k in needed:
        v=c.get(k)
        if v is None or v=='' or v==[]:
            missing.append(k)
    return not missing,missing


def main()->int:
    pin=decode('EXPECTED_PIN_B64')
    contracts=decode('CONTRACTS_B64')
    legacy=decode('LEGACY25_B64')
    alpha=decode('ALPHA_B64')
    offhost=decode('OFFHOST_B64')

    pin_sha=contracts['global_contract']['canonical_source_pin_sha256']
    offhost_pin=offhost.get('source',{}).get('canonical_source_pin_sha256')
    offhost_source_count=int(offhost.get('source',{}).get('source_path_count',0))
    offhost_module_count=int(offhost.get('source',{}).get('module_count',0))
    rollback_global=(offhost.get('state')=='PASS_OFFHOST_DURABLE_CANONICAL_BACKUP' and offhost_pin==pin_sha and offhost_source_count==84 and offhost_module_count==12)

    module_rows=[]
    total_source_count=0
    total_source_syntax=0
    for m in pin.get('modules',[]):
        mid=str(m.get('module_id'))
        c=contracts.get('components',{}).get(mid)
        files=[]
        present=syntax=0
        for source in m.get('source_paths',[]):
            total_source_count+=1
            p=canonical_path(str(source))
            exists=p.is_file()
            ok=False; detail='MISSING'
            if exists:
                present+=1
                ok,detail=syntax_ok(p)
                if ok:
                    syntax+=1; total_source_syntax+=1
            files.append({'source_path':source,'canonical_present':exists,'sha256':sha256_file(p) if exists else None,'syntax_or_json':detail})
        c_ok,c_missing=complete_contract(c or {})
        sources_ok=(present==len(m.get('source_paths',[])) and syntax==len(m.get('source_paths',[])))
        l2=sources_ok and c_ok and rollback_global
        module_rows.append({
            'component':mid,
            'source_count':len(m.get('source_paths',[])),
            'source_present_count':present,
            'source_syntax_valid_count':syntax,
            'contract_present':c is not None,
            'contract_missing_fields':c_missing,
            'authority_boundary':(c or {}).get('authority_boundary'),
            'fail_closed':(c or {}).get('fail_closed'),
            'idempotency':(c or {}).get('idempotency'),
            'rollback_anchor_verified':rollback_global,
            'L2_CONTRACT':'PASS' if l2 else 'HOLD',
            'files':files,
        })

    legacy_names=list(legacy.get('historical_implementation_inventory_25',[]))
    lib=contracts.get('libraries',{}).get('STRATEGY25',{})
    lib_ok,lib_missing=complete_contract(lib)
    legacy_sources=[]
    for name in legacy_names:
        source=f'backend/strategies/{name}.py'
        p=canonical_path(source)
        exists=p.is_file(); ok=False; detail='MISSING'
        if exists: ok,detail=syntax_ok(p)
        legacy_sources.append({'strategy':name,'source_path':source,'canonical_present':exists,'syntax':detail})
    strategy25_ok=(len(legacy_names)==25 and all(x['canonical_present'] and x['syntax']=='PASS' for x in legacy_sources) and lib_ok and rollback_global)
    strategy_library={
        'component':'STRATEGY25_LIBRARY',
        'strategy_count':len(legacy_names),
        'contract_missing_fields':lib_missing,
        'rollback_anchor_verified':rollback_global,
        'L2_CONTRACT':'PASS' if strategy25_ok else 'HOLD',
        'strategies':legacy_sources,
    }

    alpha_rows=[]
    for fam in alpha.get('alpha_engine',{}).get('allowlist',[]):
        c=contracts.get('alpha_families',{}).get(fam,{})
        c_ok,c_missing=complete_contract(c)
        declared=fam in alpha.get('alpha_engine',{}).get('base_contracts',{})
        ok=c_ok and declared and rollback_global
        alpha_rows.append({
            'family':fam,
            'base_contract_declared':declared,
            'contract_missing_fields':c_missing,
            'authority_boundary':c.get('authority_boundary'),
            'fail_closed':c.get('fail_closed'),
            'idempotency':c.get('idempotency'),
            'L2_CONTRACT':'PASS' if ok else 'HOLD',
        })

    statuses=[r['L2_CONTRACT'] for r in module_rows]+[strategy_library['L2_CONTRACT']]+[r['L2_CONTRACT'] for r in alpha_rows]
    state='PASS_G0B_L2_CONTRACT_CERTIFICATION' if len(statuses)==16 and all(x=='PASS' for x in statuses) else 'HOLD_G0B_L2_CONTRACT_GAPS'
    receipt={
        'schema_version':'zel.g0b.l2.contract_certification.v1',
        'state':state,
        'canonical_source_pin_sha256':pin_sha,
        'offhost_rollback_anchor_verified':rollback_global,
        'unique_pin_source_paths_expected':84,
        'pin_source_reference_count_with_module_reuse':total_source_count,
        'pin_source_reference_syntax_valid_count':total_source_syntax,
        'module_rows':module_rows,
        'strategy25_library':strategy_library,
        'alpha_family_rows':alpha_rows,
        'l2_pass_count':sum(x=='PASS' for x in statuses),
        'l2_total':len(statuses),
        'runtime_mutated':False,
        'service_state_mutated':False,
        'destructive_cleanup_authority':False,
        'selection_authority':False,
        'promotion_authority':False,
        'execution_authority':'NONE',
        'order_authority':'BLOCKED',
        'action':'hold',
    }
    receipt['receipt_sha256']=stable_sha(receipt)
    print(json.dumps(receipt,indent=2,sort_keys=True))
    return 0 if state.startswith('PASS_') else 2

if __name__=='__main__':
    raise SystemExit(main())
